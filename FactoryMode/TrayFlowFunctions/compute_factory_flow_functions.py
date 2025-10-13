# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Compute Factory Flow Functions
This module contains functions for managing compute factory operations including flashing, power management,
and firmware updates.
"""

import json
import os
import subprocess
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import paramiko
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from FactoryMode.output_manager import get_log_directory, setup_logging

from .base_connection_manager import BaseConnectionManager
from .common_factory_flow_functions import CommonFactoryFlowMixin
from .config_utils import ConfigLoader
from .hmc_redfish_utils import HMCRedfishUtils
from .shared_utils import validate_firmware_version_input
from .utils import Utils

# Disable SSL warnings for BMC connections
urllib3.disable_warnings(InsecureRequestWarning)


class HttpMethod(Enum):
    """HTTP methods supported by the curl helper."""

    GET = "GET"
    POST = "POST"
    PATCH = "PATCH"
    DELETE = "DELETE"


class ComputeFactoryFlowConfig:
    """Configuration manager for factory flow operations."""

    def __init__(self, config_path: str = "factory_flow_config.yaml"):
        """
        Initialize the configuration manager.

        Args:
            config_path (str): Path to the YAML configuration file
        """
        self.config_path = config_path
        self.config = ConfigLoader.load_config(config_path)
        # Validate configuration
        self._validate_config(self.config)
        self.connection = BaseConnectionManager(self.config, "compute")

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        Validate configuration for correctness and type safety.

        Args:
            config: The loaded configuration dictionary

        Raises:
            ValueError: If validation fails
        """
        # Validate settings section if present
        if "settings" in config:
            settings = config["settings"]

            # Validate retry count
            if "default_retry_count" in settings:
                retry_count = settings["default_retry_count"]
                if not isinstance(retry_count, int):
                    raise ValueError(
                        f"Invalid type for 'default_retry_count' in settings. "
                        f"Expected int, got {type(retry_count).__name__}: {retry_count}"
                    )
                if retry_count < 0:
                    raise ValueError(
                        f"Invalid value for 'default_retry_count' in settings. "
                        f"Must be non-negative, got: {retry_count}"
                    )

            # Validate wait times
            wait_fields = [
                "default_wait_after_seconds",
                "ssh_timeout",
                "redfish_timeout",
            ]
            for field in wait_fields:
                if field in settings:
                    value = settings[field]
                    if not isinstance(value, (int, float)):
                        raise ValueError(
                            f"Invalid type for '{field}' in settings. "
                            f"Expected numeric value, got {type(value).__name__}: {value}"
                        )
                    if value < 0:
                        raise ValueError(
                            f"Invalid value for '{field}' in settings. " f"Must be non-negative, got: {value}"
                        )

        # Validate connection section if present
        if "connection" in config and "compute" in config["connection"]:
            compute_conn = config["connection"]["compute"]

            # Validate BMC connection
            if "bmc" in compute_conn:
                bmc = compute_conn["bmc"]
                self._validate_connection_fields(bmc, "connection.compute.bmc")

            # Validate OS connection
            if "os" in compute_conn:
                os_conn = compute_conn["os"]
                self._validate_connection_fields(os_conn, "connection.compute.os")

        # Validate DOT configuration under compute section
        if "compute" in config:
            allowed_dot_values = {"Volatile", "Locking", "NoDOT"}
            dot_value = config["compute"].get("DOT")
            if dot_value not in allowed_dot_values:
                raise ValueError(
                    f"Invalid DOT configuration '{dot_value}'. DOT must be one of: Volatile, Locking, NoDOT"
                )

    def _validate_connection_fields(self, conn: Dict[str, Any], location: str) -> None:
        """Validate connection configuration fields."""
        # Validate IP
        if "ip" in conn and conn["ip"]:
            ip = conn["ip"]
            if not isinstance(ip, str):
                raise ValueError(f"Invalid type for 'ip' in {location}. Expected string, got {type(ip).__name__}")
            # Basic IP validation (not exhaustive)
            parts = ip.split(".")
            if len(parts) == 4:  # IPv4
                try:
                    for part in parts:
                        num = int(part)
                        if not 0 <= num <= 255:
                            raise ValueError(f"Invalid IP address in {location}: {ip}")
                except ValueError:
                    # Not a valid IPv4, might be hostname or IPv6
                    pass

        # Validate port
        if "port" in conn:
            port = conn["port"]
            if not isinstance(port, int):
                raise ValueError(
                    f"Invalid type for 'port' in {location}. " f"Expected int, got {type(port).__name__}: {port}"
                )
            if not 1 <= port <= 65535:
                raise ValueError(f"Invalid port number in {location}. " f"Must be between 1 and 65535, got: {port}")

        # Validate username/password are strings if present
        for field in ["username", "password"]:
            if field in conn and conn[field] is not None:
                if not isinstance(conn[field], str):
                    raise ValueError(
                        f"Invalid type for '{field}' in {location}. "
                        f"Expected string, got {type(conn[field]).__name__}"
                    )

    def get_config(self, section: str) -> Dict[str, Any]:
        """
        Get configuration for a specific section.

        Args:
            section (str): Configuration section name

        Returns:
            Dict[str, Any]: Configuration for the specified section
        """
        return self.config.get(section, {})

    def close(self):
        """Close all connections."""
        self.connection.close()


class ComputeFactoryFlow(CommonFactoryFlowMixin):
    """Manages the compute factory update flow."""

    def __init__(self, config: ComputeFactoryFlowConfig, device_id: str, console_output: bool = False):
        """
        Initialize compute factory flow.

        Args:
            config (ComputeFactoryFlowConfig): Configuration manager
            device_id (str): Device identifier
            console_output (bool): Enable console logging output for LOG mode
        """
        self.config = config
        self.device_id = device_id
        # Setup module-specific logger
        self.logger = setup_logging("compute_factory_flow", console_output=console_output)

        # Initialize resource tracking for automatic cleanup
        self._sol_processes = {}
        self._opened_resources = []  # Track any other resources that need cleanup

        # Initialize BMC redfish utils using shared method
        self._initialize_redfish_utils("compute")

        # Initialize HMC proxy - always available with default or configured IP
        hmc_config = self.config.config.get("connection", {}).get("compute", {}).get("hmc", {})
        hmc_ip = hmc_config.get("ip", "172.31.13.251")

        try:
            # Initialize HMC redfish utils using BMC as proxy
            bmc_config = self._get_bmc_connection_details("compute")
            self.hmc_redfish_utils = HMCRedfishUtils(bmc_connection=bmc_config, hmc_ip=hmc_ip, logger=self.logger)

            self.logger.info(f"HMC proxy initialized successfully for IP: {hmc_ip}")
        except Exception as e:
            self.logger.error(f"Failed to initialize HMC proxy: {str(e)}")
            self.hmc_redfish_utils = None

    def _get_os_connection_details(self) -> Dict[str, str]:
        """
        Get OS connection details from config.

        Returns:
            Dict[str, str]: Dictionary containing OS connection details

        Raises:
            ValueError: If any required connection details are missing
        """
        os_config = self.config.config.get("connection", {}).get("compute", {}).get("os", {})
        self.logger.info("OS config loaded")
        os_ip = os_config.get("ip")
        username = os_config.get("username")
        password = os_config.get("password")
        port = os_config.get("port", 22)

        self._validate_missing_credentials(os_ip, username, password, "OS")

        return {"ip": os_ip, "username": username, "password": password, "port": port}

    def _get_redfish_utils(self, redfish_target: str = "bmc") -> Utils:
        """
        Get appropriate redfish utils based on redfish_target.

        Args:
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            Utils: Appropriate redfish utils instance (Utils for BMC, HMCRedfishUtils for HMC proxy)

        Raises:
            ValueError: If HMC redfish_target is requested but HMC proxy initialization failed
        """
        if redfish_target == "hmc":
            if self.hmc_redfish_utils:
                return self.hmc_redfish_utils
            raise ValueError(
                "HMC redfish_target requested but HMC proxy initialization failed. Check BMC connectivity."
            )
        return self.redfish_utils

    def _pldm_fw_update_common(
        self,
        *,
        redfish_utils,
        bundle_path: str,
        base_uri: str,
        target_name: str,
        target_uris: Optional[List[str]] = None,
        force_update: bool = False,
        timeout: Optional[int] = None,
        update_method: str = "MultipartUpdate",
    ) -> bool:
        """
        Common PLDM firmware update logic.

        Args:
            redfish_utils: The redfish utils instance to use (BMC or HMC)
            bundle_path (str): Path to the firmware bundle
            base_uri (str): Base URI for the Redfish endpoint
            target_name (str): Name for logging (e.g., "BMC", "HMC")
            target_uris (Optional[List[str]]): List of target URIs for the update
            force_update (bool): Whether to force the update
            timeout (Optional[int]): Optional timeout in seconds
            update_method (str): Update method to use ("MultipartUpdate" or "HttpPushUpdate")

        Returns:
            bool: True if flash was successful, False otherwise
        """
        monitor_timeout = timeout if timeout is not None else 3600  # Default 1 hour
        check_interval = 30  # Check every 30 seconds

        # Prepare the UpdateParameters JSON
        targets = target_uris if target_uris else []
        update_params = {"Targets": targets}
        if force_update:
            update_params["ForceUpdate"] = True
        update_params_str = json.dumps(update_params)

        try:
            self.logger.info(f"Flashing PLDM bundle via {target_name}")
            status, response = redfish_utils.post_upload_request(
                url_path=base_uri,
                file_path=bundle_path,
                update_method=update_method,
                upd_params=update_params_str,
                timeout=timeout,
            )
            if not status:
                self.logger.error(f"PLDM bundle flash failed, response: {response}")
                return False

            task_uri = None
            if isinstance(response, dict) and "Task" in response.get("@odata.type", ""):
                task_uri = response.get("@odata.id", None)
            if not task_uri:
                self.logger.error(f"PLDM bundle flash did not return a task ID: {response}")
                return False

            self.logger.info(f"Monitoring task {task_uri} for completion")
            task_final_status, response = redfish_utils.monitor_job(
                uri=task_uri, timeout=monitor_timeout, check_interval=check_interval
            )
            if not task_final_status:
                self.logger.error(f"PLDM bundle flash failed to complete, response: {response}")
                return False

            # Check if we got a monitoring timeout warning
            if response.get("Message") == "Monitoring timeout reached":
                self.logger.warning("PLDM bundle flash monitoring timed out - task may have completed in background")
                return True

            # Check if task is still running (shouldn't happen with timeout logic, but safety check)
            if response.get("TaskState") == "Running":
                self.logger.error(f"PLDM bundle flash still running after monitoring timeout, response: {response}")
                return False

            self.logger.info(f"PLDM bundle flash completed successfully, response: {response}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to flash PLDM bundle via {target_name}: {str(e)}")
            return False

    def pldm_fw_update(
        self,
        *,
        bundle_path: str,
        base_uri: str,
        target_uris: Optional[List[str]] = None,
        force_update: bool = False,
        timeout: Optional[int] = None,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Flash PLDM firmware bundle to BMC or HMC.

        Args:
            bundle_path (str): Path to the firmware bundle
            base_uri (str): Base URI for the Redfish endpoint
            target_uris (Optional[List[str]]): List of target URIs for the update
            force_update (bool): Whether to force the update
            timeout (Optional[int]): Optional timeout in seconds
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy
            remote_path (str): Remote path on BMC for HMC updates (default: /tmp/firmware.pldm)

        Returns:
            bool: True if flash was successful, False otherwise
        """
        self.logger.info(f"pldm_fw_update called with redfish_target='{redfish_target}' (type: {type(redfish_target)})")

        if redfish_target == "hmc":
            self.logger.info("Taking HMC path for firmware update")
            return self._pldm_fw_update_hmc(
                bundle_path=bundle_path,
                target_uris=target_uris,
                force_update=force_update,
                timeout=timeout,
            )
        self.logger.info(f"Taking BMC path for firmware update (redfish_target was '{redfish_target}')")
        return self._pldm_fw_update_common(
            redfish_utils=self.redfish_utils,
            bundle_path=bundle_path,
            base_uri=base_uri,
            target_name="BMC",
            target_uris=target_uris,
            force_update=force_update,
            timeout=timeout,
            update_method="MultipartUpdate",
        )

    def _pldm_fw_update_hmc(
        self,
        *,
        bundle_path: str,
        target_uris: Optional[List[str]] = None,
        force_update: bool = False,
        timeout: Optional[int] = None,
    ) -> bool:
        """
        Private method to flash PLDM firmware bundle to HMC via SCP + HMC redfish utils.

        The remote path on BMC is determined by the scp_target configuration in
        connection.compute.bmc.scp_target (defaults to /tmp if not set).

        Args:
            bundle_path (str): Local path to the firmware bundle
            target_uris (Optional[List[str]]): List of target URIs for the update
            force_update (bool): Whether to force the update
            timeout (Optional[int]): Optional timeout in seconds

        Returns:
            bool: True if flash was successful, False otherwise
        """
        # Check if HMC redfish utils are available
        if not self.hmc_redfish_utils:
            self.logger.error("HMC redfish utils not initialized - cannot perform HMC firmware update")
            return False

        self.logger.info("Starting HMC firmware update via BMC proxy")

        try:
            # Get BMC connection configuration
            bmc_config_dict = self.config.config.get("connection", {}).get("compute", {}).get("bmc", {})

            # Get scp_target from BMC config, default to /tmp if not set
            scp_target = bmc_config_dict.get("scp_target", "/tmp")
            if not scp_target:
                scp_target = "/tmp"

            # Build the remote file path using scp_target directory
            firmware_filename = os.path.basename(bundle_path)
            remote_file_path = f"{scp_target.rstrip('/')}/{firmware_filename}"

            self.logger.info(f"Transferring firmware package to BMC: {bundle_path} -> {remote_file_path}")

            # Use the shared scp_files_target method from BaseConnectionManager
            bmc_config = self._get_bmc_connection_details("compute")

            if not self.config.connection.scp_files_target(
                files=bundle_path,
                target_config=bmc_config,
                remote_base_path=scp_target,  # Use configured scp_target
                set_executable=False,  # Firmware files don't need executable permissions
                logger=self.logger,
            ):
                self.logger.error("Failed to transfer firmware package to BMC")
                return False

            # Step 2: Use common PLDM update logic with HMC redfish utils
            return self._pldm_fw_update_common(
                redfish_utils=self.hmc_redfish_utils,
                bundle_path=remote_file_path,  # Use remote path on BMC
                base_uri="/redfish/v1/UpdateService/update",
                target_name="HMC",
                target_uris=target_uris,
                force_update=force_update,
                timeout=timeout,
                update_method="HttpPushUpdate",
            )

        except Exception as e:
            self.logger.error(f"Failed to transfer firmware package for HMC update: {str(e)}")
            return False

    def dot_cak_install(
        self,
        *,
        ap_name: str,
        pem_encoded_key: str,
        ap_firmware_signature: str,
        base_uri: str = "/redfish/v1/Chassis",
        check_volatile_dot: bool = True,
        data: Optional[Dict[str, Any]] = None,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Install DOT CAK on the device.

        Args:
            ap_name (str): AP identifier (e.g., "ERoT_CPU_0", "ERoT_CPU_1", etc.)
            pem_encoded_key (str): PEM encoded key to install
            ap_firmware_signature (str): Base64 encoded hash of the AP firmware signature
            base_uri (str): Base URI for the Redfish endpoint. Defaults to "/redfish/v1/Chassis"
            check_volatile_dot (bool): If True, check DOT value in config. Defaults to True.
            data (Optional[Dict[str, Any]]): Optional data to override default request body
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if CAK install was successful, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        # If check_volatile_dot is True, check the DOT value in config
        dot_value = self.config.config.get("compute", {}).get("DOT")
        self.logger.info(f"DOT value: {dot_value}")
        if check_volatile_dot:
            if dot_value != "Volatile":
                self.logger.info("DOT is not set to 'Volatile', returning True")
                return True

        if dot_value == "NoDOT":
            self.logger.info("DOT is 'NoDOT', skipping DOT CAK install and returning True")
            return True

        # Raise an error if pem_encoded_key or ap_firmware_signature is empty or None
        if (
            pem_encoded_key is None
            or pem_encoded_key == ""
            or ap_firmware_signature is None
            or ap_firmware_signature == ""
        ):
            error_msg = (
                f"PEM encoded key or AP firmware signature is empty for {ap_name}. " "DOT CAK install cannot proceed."
            )
            self.logger.error(error_msg)
            return False

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            uri = self._join_url_path(base_uri, ap_name, "actions/oem/CAKInstall")
            # Prepare the data
            if data is None:
                data = {
                    "CAKKey": pem_encoded_key,
                    "LockDisable": False,
                    "APFirmwareSignature": ap_firmware_signature,
                }

            self.logger.info(f"Installing DOT CAK on {ap_name} via {redfish_target.upper()}")
            status, response = redfish_utils.post_request(uri, data, timeout=redfish_timeout)
            if status:
                self.logger.info(f"Successfully installed DOT CAK on {ap_name}")
                return True
            self.logger.error(f"Failed to install DOT CAK on {ap_name}: response:{response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def dot_cak_lock(
        self,
        *,
        ap_name: str,
        pem_encoded_key: str,
        base_uri: str = "/redfish/v1/Chassis",
        check_locking_dot: bool = True,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Lock DOT CAK on the device.

        Args:
            ap_name (str): AP identifier (e.g., "ERoT_CPU_0", "ERoT_CPU_1", etc.)
            pem_encoded_key (str): PEM encoded key to lock
            base_uri (str): Base URI for the Redfish endpoint. Defaults to "/redfish/v1/Chassis"
            check_locking_dot (bool): If True, check DOT value in config. Defaults to True.
            target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if CAK lock was successful, False otherwise
        """
        # If check_locking_dot is True, check the DOT value in config
        if check_locking_dot:
            dot_value = self.config.config.get("compute", {}).get("DOT")
            if dot_value != "Locking":
                self.logger.info("DOT is not set to 'Locking', returning True")
                return True

        # Assumed skipping cak lock if pem encoded key is empty
        if pem_encoded_key is None or pem_encoded_key == "":
            self.logger.info(f"PEM encoded key is empty, skipping DOT CAK lock for {ap_name}")
            return True

        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            uri = self._join_url_path(base_uri, ap_name, "actions/oem/CAKLock")
            # Prepare the data
            data = {"key": pem_encoded_key}

            self.logger.info(f"Locking DOT CAK on {ap_name} via {redfish_target.upper()}")
            status, response = redfish_utils.post_request(uri, data, timeout=redfish_timeout)
            if status:
                self.logger.info(f"Successfully locked DOT CAK on {ap_name}")
                return True
            self.logger.error(f"Failed to lock DOT CAK on {ap_name}: response:{response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def reboot_bmc(
        self,
        base_uri: str,
        data: Optional[Dict[str, Any]] = None,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Reboot the Baseboard Management Controller or HMC.

        Args:
            base_uri (str): Base URI for the Redfish endpoint
            data (Optional[Dict[str, Any]]): Optional data to override default request body
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if reboot was successful, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)
        delay = 5

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            # Prepare the data
            if data is None:
                data = {"ResetType": "GracefulRestart"}

            self.logger.info(f"Rebooting {redfish_target.upper()}")
            status, response = redfish_utils.post_request(base_uri, data, timeout=redfish_timeout)

            # Check for success message in response
            if status and "error" not in str(response).lower():
                self.logger.info(f"Successfully initiated {redfish_target.upper()} reboot (confirmed by response)")
                time.sleep(delay)
                return True
            self.logger.error(f"Failed to reboot {redfish_target.upper()}: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def set_power_policy_always_off(self, base_uri: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Set power policy to always off.

        Args:
            base_uri (str): Base URI for the Redfish endpoint
            data (Optional[Dict[str, Any]]): Optional data to override default request body

        Returns:
            bool: True if policy was set successfully, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Prepare the data
            if data is None:
                data = {"PowerRestorePolicy": "AlwaysOff"}

            self.logger.info("Setting power policy to AlwaysOff")
            status, response = self.redfish_utils.patch_request(base_uri, data, timeout=redfish_timeout)
            if status:
                self.logger.info("Successfully set power policy to AlwaysOff")
                return True
            self.logger.error(f"Failed to set power policy: response:{response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def set_power_policy_always_on(self, base_uri: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Set power policy to always on.

        Args:
            base_uri (str): Base URI for the Redfish endpoint
            data (Optional[Dict[str, Any]]): Optional data to override default request body

        Returns:
            bool: True if policy was set successfully, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Prepare the data
            if data is None:
                data = {"PowerRestorePolicy": "AlwaysOn"}

            self.logger.info("Setting power policy to AlwaysOn")
            status, response = self.redfish_utils.patch_request(base_uri, data, timeout=redfish_timeout)
            if status:
                self.logger.info("Successfully set power policy to AlwaysOn")
                return True
            self.logger.error(f"Failed to set power policy: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def set_power_policy_last_state(self, base_uri: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Set power policy to last state.

        Args:
            base_uri (str): Base URI for the Redfish endpoint
            data (Optional[Dict[str, Any]]): Optional data to override default request body

        Returns:
            bool: True if policy was set successfully, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Prepare the data
            if data is None:
                data = {"PowerRestorePolicy": "LastState"}

            self.logger.info("Setting power policy to LastState")
            status, response = self.redfish_utils.patch_request(base_uri, data, timeout=redfish_timeout)
            if status:
                self.logger.info("Successfully set power policy to LastState")
                return True
            self.logger.error(f"Failed to set power policy: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def check_power_policy(self, checked_state: str, base_uri: str) -> bool:
        """
        Check if the PowerRestorePolicy matches the checked_state.

        Args:
            checked_state (str): The expected value for PowerRestorePolicy (e.g., "AlwaysOff", "AlwaysOn")

        Returns:
            bool: True if PowerRestorePolicy matches checked_state, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            self.logger.info(f"Checking PowerRestorePolicy for state '{checked_state}'")
            status, response = self.redfish_utils.get_request(base_uri, timeout=redfish_timeout)

            # Check if response contains the correct PowerRestorePolicy
            if status and isinstance(response, dict):
                # Try to get PowerRestorePolicy from the response
                policy = response.get("PowerRestorePolicy")
                if policy == checked_state:
                    self.logger.info(f"PowerRestorePolicy is '{checked_state}' as expected.")
                    return True
                self.logger.warning(f"PowerRestorePolicy is '{policy}', expected '{checked_state}'.")
                return False
            self.logger.error(f"Unexpected response format: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def ac_cycle(
        self,
        base_uri: str,
        data: Optional[Dict[str, Any]] = None,
        check_volatile_dot: bool = False,
    ) -> bool:
        """
        Perform an AC power cycle on the device.

        Args:
            base_uri (str): Base URI for the Redfish endpoint
            data (Optional[Dict[str, Any]]): Optional data to override default request body

        Returns:
            bool: True if cycle was successful, False otherwise
        """
        # If check_volatile_dot is True, check the DOT value in config
        if check_volatile_dot:
            volatile_dot = self.config.config.get("compute", {}).get("DOT")
            if volatile_dot != "Volatile":
                self.logger.info("DOT is not set to 'Volatile', returning True")
                return True

        delay_before = 5
        delay_after = 10

        try:
            # Prepare the data
            if data is None:
                data = {"ResetType": "AuxPowerCycle"}

            self.logger.info("Performing AC power cycle")

            # Wait before cycle if specified
            if delay_before > 0:
                time.sleep(delay_before)

            status, response = self.redfish_utils.post_request(base_uri, data)

            # Check for success message in response
            if status and "error" not in str(response).lower():
                self.logger.info("Successfully initiated AC power cycle (confirmed by response)")
                # Wait after cycle if specified
                if delay_after > 0:
                    time.sleep(delay_after)
                return True
            self.logger.error(f"Failed to perform AC power cycle: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def wait_ap_ready(
        self,
        *,
        ap_name: Union[str, List[str]],
        base_uri: str,
        timeout: Optional[int] = None,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Check if HMC (Hardware Management Console) is ready by verifying
        the presence of one or more AP names in the firmware inventory.

        Args:
            ap_name (Union[str, List[str]]): AP identifier or list of identifiers to check for
            base_uri (str): Base URI for the Redfish endpoint
            timeout (Optional[int]): Override the default timeout in seconds for the entire operation
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if all specified AP names are found, False otherwise
        """
        timeout = timeout if timeout is not None else 120
        check_interval = 10  # Check every 10 seconds

        # Normalize ap_name to a list
        if isinstance(ap_name, str):
            ap_names = [ap_name]
        else:
            ap_names = list(ap_name)

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")
            start_time = time.time()

            while True:
                # Check if we've exceeded the timeout
                if time.time() - start_time > timeout:
                    self.logger.error(f"AP readiness check timed out after {timeout} seconds")
                    return False

                self.logger.info(f"Checking HMC readiness for {ap_names}")
                redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)
                status, response = redfish_utils.get_request(base_uri, timeout=redfish_timeout)

                # Check if response contains all requested AP names
                if status and isinstance(response, dict):
                    response_str = json.dumps(response)
                    missing = [name for name in ap_names if name not in response_str]
                    if not missing:
                        self.logger.info(f"All APs ready: {ap_names} (found in {base_uri})")
                        return True
                    self.logger.warning(f"APs not ready (not found in {base_uri}): {missing}")
                    # Continue looping to check again
                else:
                    self.logger.error(f"Failed to check HMC readiness: {response}")
                    # Continue looping to check again

                # Wait for the check interval before next attempt
                self.logger.info(f"Waiting {check_interval} seconds before next AP readiness check")
                time.sleep(check_interval)

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def hmc_factory_reset(
        self,
        base_uri: str,
        data: Optional[Dict[str, Any]] = None,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Perform factory reset on HMC using the ResetToDefaults action.

        Args:
            base_uri (str): Base URI for the Redfish endpoint
            data (Optional[Dict[str, Any]]): Optional data to override default request body.
                                           Defaults to {"ResetToDefaultsType": "ResetAll"}
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if reset was successful, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            # Prepare the data
            if data is None:
                data = {"ResetToDefaultsType": "ResetAll"}

            self.logger.info(f"Performing HMC factory reset via {redfish_target.upper()}")
            status, response = redfish_utils.post_request(base_uri, data, timeout=redfish_timeout)

            # Check for success message in response
            if status and "error" not in str(response).lower():
                self.logger.info("Successfully initiated HMC factory reset (confirmed by response)")
                return True
            self.logger.error(f"Failed to perform HMC factory reset: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def nvflash_check_vbios(self) -> bool:
        """
        Check VBIOS versions using nvflash by:
        1. Removing NVIDIA kernel modules
        2. Running nvflash -v --list

        Returns:
            bool: True if check was successful, False otherwise
        """
        try:
            # Get OS connection details from config
            os_config = self.config.config.get("connection", {}).get("compute", {}).get("os", {})
            if not all(
                [
                    os_config.get("ip"),
                    os_config.get("username"),
                    os_config.get("password"),
                ]
            ):
                self.logger.error("Missing required OS connection details in config")
                return False

            # Create SSH client
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                ssh_timeout = self.config.config.get("settings", {}).get("ssh_timeout", 30)

                # Connect to OS
                self.logger.info(f"Connecting to OS at {os_config['ip']} (timeout: {ssh_timeout}s)")
                ssh_client.connect(
                    hostname=os_config["ip"],
                    port=os_config.get("port", 22),
                    username=os_config["username"],
                    password=os_config["password"],
                    timeout=ssh_timeout,
                )

                # Remove NVIDIA kernel modules
                self.logger.info("Removing NVIDIA kernel modules")
                rmmod_cmd = "rmmod nvidia_drm nvidia_modeset nvidia_urm nvidia"
                _, stdout, stderr = ssh_client.exec_command(rmmod_cmd)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error = stderr.read().decode().strip()
                    self.logger.warning(f"Warning: Failed to remove some NVIDIA modules: {error}")
                    # Continue anyway as some modules might not be loaded

                # Run nvflash command
                self.logger.info("Running nvflash -v --list")
                nvflash_cmd = "sudo ./nvflash -v --list"
                _, stdout, stderr = ssh_client.exec_command(nvflash_cmd)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error = stderr.read().decode().strip()
                    self.logger.error(f"Failed to run nvflash: {error}")
                    return False

                # Get and log output
                output = stdout.read().decode().strip()
                self.logger.info(f"VBIOS Information:\n{output}")
                return True

            except Exception as e:
                self.logger.error(f"Failed to check VBIOS: {str(e)}")
                return False

            finally:
                ssh_client.close()

        except Exception as e:
            self.logger.error(f"Unexpected error during VBIOS check: {str(e)}")
            return False

    def nvflash_flash_vbios(self, vbios_bundle: str, upgrade_only: bool = False) -> bool:
        """
        Flash VBIOS using nvflash by:
        1. Removing NVIDIA kernel modules
        2. Running nvflash with the specified bundle

        Args:
            vbios_bundle (str): Name of the VBIOS standalone bundle to flash
            upgrade_only (bool): If True, adds --upgradeonly flag to nvflash command. Defaults to False.

        Returns:
            bool: True if flash was successful, False otherwise
        """
        try:
            # Get OS connection details from config
            os_config = self.config.config.get("connection", {}).get("compute", {}).get("os", {})
            if not all(
                [
                    os_config.get("ip"),
                    os_config.get("username"),
                    os_config.get("password"),
                ]
            ):
                self.logger.error("Missing required OS connection details in config")
                return False

            # Create SSH client
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                ssh_timeout = self.config.config.get("settings", {}).get("ssh_timeout", 30)

                # Connect to OS
                self.logger.info(f"Connecting to OS at {os_config['ip']} (timeout: {ssh_timeout}s)")
                ssh_client.connect(
                    hostname=os_config["ip"],
                    port=os_config.get("port", 22),
                    username=os_config["username"],
                    password=os_config["password"],
                    timeout=ssh_timeout,
                )

                # Remove NVIDIA kernel modules
                self.logger.info("Removing NVIDIA kernel modules")
                rmmod_cmd = "rmmod nvidia_drm nvidia_modeset nvidia_urm nvidia"
                _, stdout, stderr = ssh_client.exec_command(rmmod_cmd)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error = stderr.read().decode().strip()
                    self.logger.warning(f"Warning: Failed to remove some NVIDIA modules: {error}")
                    # Continue anyway as some modules might not be loaded

                # Run nvflash command
                upgrade_flag = "--upgradeonly " if upgrade_only else ""
                self.logger.info(f"Running nvflash with bundle: {vbios_bundle} (upgrade_only: {upgrade_only})")
                nvflash_cmd = f"sudo ./nvflash {vbios_bundle} {upgrade_flag}--auto"
                _, stdout, stderr = ssh_client.exec_command(nvflash_cmd)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error = stderr.read().decode().strip()
                    self.logger.error(f"Failed to flash VBIOS: {error}")
                    return False

                # Get and log output
                output = stdout.read().decode().strip()
                self.logger.info(f"VBIOS Flash Output:\n{output}")
                return True

            except Exception as e:
                self.logger.error(f"Failed to flash VBIOS: {str(e)}")
                return False

            finally:
                ssh_client.close()

        except Exception as e:
            self.logger.error(f"Unexpected error during VBIOS flash: {str(e)}")
            return False

    def monitor_background_copy(
        self,
        *,
        ap_name: Union[str, List[str]],
        base_uri: str,
        timeout: Optional[int] = None,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Monitor background copy operation for one or more APs.

        Args:
            ap_name (Union[str, List[str]]): Name(s) of the AP(s) to monitor (e.g., "AP_0", ["AP_0", "AP_1"])
            base_uri (str): Base URI for the Redfish endpoint
            timeout (Optional[int]): Optional timeout in seconds. If provided, will check every 30 seconds
                                   until timeout is reached. If None, will only check once.
            target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if background copy is completed for all specified APs, False otherwise
        """
        check_interval = 30  # Check every 30 seconds if timeout is provided

        # Normalize ap_name to a list
        if isinstance(ap_name, str):
            ap_names = [ap_name]
        else:
            ap_names = list(ap_name)

        # Normalize ap_name to a list
        if isinstance(ap_name, str):
            ap_names = [ap_name]
        else:
            ap_names = list(ap_name)

        # Normalize ap_name to a list
        if isinstance(ap_name, str):
            ap_names = [ap_name]
        else:
            ap_names = list(ap_name)

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            start_time = time.time()

            while True:
                # Check if we've exceeded the timeout
                if timeout is not None and time.time() - start_time > timeout:
                    self.logger.error(f"Background copy monitoring timed out after {timeout} seconds")
                    return False

                self.logger.info(f"Checking background copy status for {ap_names}")

                completed_aps = []
                failed_aps = []
                pending_aps = []

                # Check each AP individually
                redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)
                for ap in ap_names:
                    status, response = redfish_utils.get_request(
                        self._join_url_path(base_uri, ap), timeout=redfish_timeout
                    )

                    if status and isinstance(response, dict):
                        # Convert response to string for searching
                        response_str = json.dumps(response)
                        if '"BackgroundCopyStatus": "Completed"' in response_str:
                            completed_aps.append(ap)
                        else:
                            pending_aps.append(ap)
                    else:
                        self.logger.error(f"Failed to check background copy status for {ap}: {response}")
                        failed_aps.append(ap)

                # Log status of all APs
                if completed_aps:
                    self.logger.info(f"Background copy completed for: {completed_aps}")
                if pending_aps:
                    self.logger.warning(f"Background copy not completed for: {pending_aps}")
                if failed_aps:
                    self.logger.error(f"Failed to check background copy status for: {failed_aps}")

                # Check if all APs are completed
                if len(completed_aps) == len(ap_names):
                    self.logger.info(f"Background copy completed for all APs: {ap_names}")
                    return True

                # If any failed and we're only checking once, return False
                if timeout is None:
                    return False

                # If we have failures and timeout is specified, also return False
                if failed_aps:
                    return False

                # Wait for the check interval before next attempt
                self.logger.info(f"Waiting {check_interval} seconds before next background copy status check")
                time.sleep(check_interval)

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def check_manual_boot_mode(
        self,
        *,
        ap_name: str,
        base_uri: str,
        checked_state: str = "true",
        check_volatile_dot: bool = True,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Check if manual boot mode matches the expected state for a specific AP.

        Args:
            ap_name (str): AP identifier (e.g., "ERoT_CPU_0", "ERoT_CPU_1")
            base_uri (str): Base URI for the Redfish endpoint
            checked_state (str): The expected value for ManualBootModeEnabled ("True"/"False", "true"/"false" or boolean-equivalent). Defaults to "true".
            check_volatile_dot (bool): If True, check DOT value in config. Defaults to True.
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if manual boot mode matches checked_state, False otherwise
        """
        # If check_volatile_dot is True, check the DOT value in config
        if check_volatile_dot:
            volatile_dot = self.config.config.get("compute", {}).get("DOT")
            if volatile_dot != "Volatile":
                self.logger.info("DOT is not set to 'Volatile', checking for False")
                checked_state = "False"
            else:
                checked_state = "True"

        # Normalize expected to boolean
        if isinstance(checked_state, bool):
            expected_bool = checked_state
        elif isinstance(checked_state, str):
            expected_bool = checked_state.strip().lower() == "true"
        else:
            self.logger.error(f"Unexpected type for 'checked_state': {type(checked_state)}")
            return False

        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            self.logger.info(
                f"Checking manual boot mode for {ap_name} via {redfish_target.upper()} for state '{'True' if expected_bool else 'False'}'"
            )
            status, response = redfish_utils.get_request(
                self._join_url_path(base_uri, ap_name), timeout=redfish_timeout
            )

            # Check if response contains ManualBootModeEnabled
            if status and isinstance(response, dict):
                # Prefer structured access first
                actual_value = None
                try:
                    actual_value = response.get("Oem", {}).get("Nvidia", {}).get("ManualBootModeEnabled", None)
                    if actual_value is None:
                        actual_value = response.get("ManualBootModeEnabled", None)
                except Exception:
                    actual_value = None

                # If not found structurally, fallback to string search tolerant of True/true
                if actual_value is None:
                    response_str = json.dumps(response)
                    if '"ManualBootModeEnabled": true' in response_str:
                        actual_bool = True
                    elif '"ManualBootModeEnabled": false' in response_str:
                        actual_bool = False
                    else:
                        self.logger.error("ManualBootModeEnabled not found in response")
                        return False
                else:
                    # Coerce to bool if it came back as string
                    if isinstance(actual_value, bool):
                        actual_bool = actual_value
                    elif isinstance(actual_value, str):
                        actual_bool = actual_value.strip().lower() == "true"
                    else:
                        actual_bool = bool(actual_value)

                if actual_bool == expected_bool:
                    self.logger.info(
                        f"Manual boot mode is '{'True' if actual_bool else 'False'}' for {ap_name} as expected"
                    )
                    return True

                self.logger.warning(
                    f"Manual boot mode is '{'True' if actual_bool else 'False'}' for {ap_name}, expected '{'True' if expected_bool else 'False'}'"
                )
                return False
            self.logger.error(f"Failed to check manual boot mode: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def set_manual_boot_mode(
        self,
        *,
        ap_name: str,
        base_uri: str,
        state: str = "true",
        check_volatile_dot: bool = True,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Set manual boot mode for a specific AP to the specified state or based on DOT configuration.

        Args:
            ap_name (str): AP identifier (e.g., "ERoT_CPU_0", "ERoT_CPU_1")
            base_uri (str): Base URI for the Redfish endpoint
            state (str): The value to set for ManualBootModeEnabled (accepts "True"/"False", "true"/"false", or boolean). Defaults to "true".
            check_volatile_dot (bool): If True, check DOT value in config and override state. Defaults to True.
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if manual boot mode was set successfully, False otherwise
        """
        # Determine the manual boot mode value
        if check_volatile_dot:
            volatile_dot = self.config.config.get("compute", {}).get("DOT")
            if volatile_dot != "Volatile":
                self.logger.info("DOT is not set to 'Volatile', setting manual boot mode to False ")
                state = "False"
            else:
                self.logger.info("DOT is set to 'Volatile', setting manual boot mode to True")
                state = "True"

        # Convert state to boolean for the API
        if isinstance(state, bool):
            manual_boot_enabled = state
        elif isinstance(state, str):
            manual_boot_enabled = state.strip().lower() == "true"
        else:
            self.logger.error(f"Unexpected type for 'state': {type(state)}, defaulting to False")
            return False

        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            # Prepare the data
            data = {"Oem": {"Nvidia": {"ManualBootModeEnabled": manual_boot_enabled}}}

            self.logger.info(
                f"Setting manual boot mode to '{'True' if manual_boot_enabled else 'False'}' for {ap_name} via {redfish_target.upper()}"
            )
            status, response = redfish_utils.patch_request(
                self._join_url_path(base_uri, ap_name), data, timeout=redfish_timeout
            )

            if status:
                self.logger.info(
                    f"Successfully set manual boot mode to '{'True' if manual_boot_enabled else 'False'}' for {ap_name}"
                )
                return True
            self.logger.error(f"Failed to set manual boot mode for {ap_name}: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def send_boot_ap(
        self,
        *,
        ap_name: str,
        base_uri: str,
        check_volatile_dot: bool = True,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Send boot command to a specific AP.

        Args:
            ap_name (str): AP identifier (e.g., "ERoT_CPU_0", "ERoT_CPU_1")
            base_uri (str): Base URI for the Redfish endpoint
            check_volatile_dot (bool): If True, check DOT value in config. Defaults to True.
            data (Optional[Dict[str, Any]]): Optional data to override default request body
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if boot command was sent successfully, False otherwise
        """
        # If check_volatile_dot is True, check the DOT value in config
        if check_volatile_dot:
            dot_value = self.config.config.get("compute", {}).get("DOT")
            if dot_value != "Volatile":
                self.logger.info("DOT is not set to 'Volatile', returning True")
                return True

        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Prepare the data
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            self.logger.info(f"Sending boot command to {ap_name} via {redfish_target.upper()}")
            status, response = redfish_utils.post_request(
                self._join_url_path(base_uri, ap_name, "Actions/Oem/NvidiaChassis.BootProtectedDevice"),
                timeout=redfish_timeout,
            )

            if status and "error" not in str(response).lower():
                self.logger.info(f"Successfully sent boot command to {ap_name}")
                return True
            self.logger.error(f"Failed to send boot command to {ap_name}: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def check_boot_progress(
        self,
        *,
        base_uri: str,
        state: Union[str, List[str]],
        timeout: Optional[int] = None,
        check_interval: int = 30,
    ) -> bool:
        """
        Check the boot progress state of the system.

        Args:
            base_uri (str): Base URI for the Redfish endpoint (e.g., /redfish/v1/Systems/System_0)
            state (Union[str, List[str]]): Desired boot state(s) to wait for. Can be a single string like "OSRunning"
                                         or a list like ["OSRunning", "OSBootStarted"]
            timeout (Optional[int]): Maximum time in seconds to wait for boot progress to reach desired state.
                                   If None, will only check once.
            check_interval (int): Polling interval between checks

        Returns:
            bool: True if LastState inside BootProgress matches any of the desired states, False otherwise
        """
        # Normalize state to a list
        if isinstance(state, str):
            target_states = [state]
        else:
            target_states = list(state)

        try:
            start_time = time.time()
            consecutive_none_count = 0

            while True:
                # Check if we've exceeded the timeout
                if timeout is not None and time.time() - start_time > timeout:
                    self.logger.error(f"Boot progress check timed out after {timeout} seconds")
                    return False

                self.logger.info(f"Checking boot progress for states: {target_states}")
                status, response = self.redfish_utils.get_request(base_uri, timeout=timeout)

                # Check if response contains BootProgress with LastState
                if status and isinstance(response, dict):
                    boot_progress = response.get("BootProgress")
                    if not isinstance(boot_progress, dict):
                        self.logger.error("BootProgress not found or not a dictionary in response")
                        consecutive_none_count += 1
                        if consecutive_none_count >= 2:
                            self.logger.error("BootProgress returned None twice in a row - failing")
                            return False
                        if timeout is None:
                            return False
                        # Continue looping if timeout is specified
                    else:
                        last_state = boot_progress.get("LastState")
                        if last_state is None or (isinstance(last_state, str) and last_state == "None"):
                            self.logger.error(f"LastState is None (consecutive count: {consecutive_none_count + 1})")
                            consecutive_none_count += 1
                            if consecutive_none_count >= 2:
                                self.logger.error("LastState returned None twice in a row - failing")
                                return False
                            if timeout is None:
                                return False
                            # Continue looping if timeout is specified
                        elif last_state in target_states:
                            self.logger.info(f"Boot progress is in desired state: {last_state}")
                            return True
                        else:
                            # Reset counter on valid response
                            consecutive_none_count = 0
                            self.logger.warning(
                                f"Boot progress is in state: {last_state}, waiting for: {target_states}"
                            )
                            if timeout is None:
                                return False
                            # Continue looping if timeout is specified
                else:
                    self.logger.error("Unexpected response format from system")
                    if timeout is None:
                        return False
                    # Continue looping if timeout is specified

                # If we're not using timeout, we've already returned False
                if timeout is None:
                    return False

                # Wait for the check interval before next attempt
                self.logger.info(f"Waiting {check_interval} seconds before next boot progress check")
                time.sleep(check_interval)

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def execute_script(self, command: str) -> bool:
        """
        Execute an arbitrary command as a subprocess.

        Args:
            command (str): The command to execute

        Returns:
            bool: True if command executed successfully (return code 0), False otherwise
        """
        try:
            self.logger.info(f"Executing command: {command}")

            # Execute the command as a subprocess
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)

            # Log the output
            if result.stdout:
                self.logger.info(f"Command stdout: {result.stdout}")
            if result.stderr:
                self.logger.warning(f"Command stderr: {result.stderr}")

            # Check return code
            if result.returncode == 0:
                self.logger.info("Command executed successfully")
                return True
            self.logger.error(f"Command failed with return code: {result.returncode}")
            return False

        except Exception as e:
            self.logger.error(f"Failed to execute command: {str(e)}")
            return False

    def bmc_preflight_check(self):
        """
        1. check if BMC is reachable
        2. Check if BMC rf service is reachable
        """
        ping_status = self.redfish_utils.ping_dut()
        if ping_status != 0:
            self.logger.error("BMC is not reachable")
            return False
        rf_status, _ = self.redfish_utils.get_request("/redfish/v1/")
        if not rf_status:
            self.logger.error("BMC rf service is not reachable")
            return False
        return True

    def close(self):
        """Close all connections and clean up resources."""
        try:
            self.logger.info("Closing compute factory flow connections")

            # Stop any running SOL logging processes
            if hasattr(self, "_sol_processes") and self._sol_processes:
                for log_file_path in list(self._sol_processes.keys()):
                    self.logger.info(f"Cleaning up SOL logging for {log_file_path}")
                    try:
                        self.stop_sol_logging(log_file_path)
                    except Exception as e:
                        self.logger.error(f"Error stopping SOL logging for {log_file_path}: {e}")

            # Clean up any other tracked resources
            if hasattr(self, "_opened_resources"):
                for resource in self._opened_resources:
                    try:
                        if hasattr(resource, "close"):
                            resource.close()
                    except Exception as e:
                        self.logger.error(f"Error closing resource: {e}")
                self._opened_resources.clear()

            # Close HMC proxy connections if available
            if hasattr(self, "hmc_redfish_utils") and self.hmc_redfish_utils:
                try:
                    self.hmc_redfish_utils.close()
                except Exception as e:
                    self.logger.error(f"Error closing HMC connection: {e}")

            self.logger.info("All connections closed successfully")
        except Exception as e:
            self.logger.error(f"Error closing connections: {str(e)}")

    def __del__(self):
        """Destructor to ensure cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            # Suppress errors during garbage collection
            pass

    def scp_tool_to_os(self, tool_file_path: str) -> bool:
        """
        SCP a tool file to the OS home directory using configured credentials.

        Note: Only the basename of the file is transferred to the target home directory.
        For example, '/path/to/tools/file.tgz' becomes '~/file.tgz' on the target.

        Args:
            tool_file_path (str): Path to the tool file to transfer - basename will be extracted

        Returns:
            bool: True if transfer was successful, False otherwise
        """

        # Get OS connection details from config
        os_config = self.config.config.get("connection", {}).get("compute", {}).get("os", {})
        return self.config.connection.scp_tool_to_os(tool_file_path, os_config, logger=self.logger)

    def check_gpu_inband_update_policy(self, base_uri: str, ap_name: str, redfish_target: str = "bmc") -> bool:
        """
        Check if inband update policy is enabled for a specific GPU.

        Args:
            base_uri (str): Base URI for the Redfish endpoint (e.g., "/redfish/v1/Chassis")
            ap_name (str): AP identifier (e.g., "HGX_IRoT_GPU_0")
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if inband update policy is enabled, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            self.logger.info(f"Checking inband update policy for {ap_name} via {redfish_target.upper()}")

            # Use redfish_utils.get_request
            status, response = redfish_utils.get_request(
                self._join_url_path(base_uri, ap_name), timeout=redfish_timeout
            )

            # Check if response contains InbandUpdatePolicyEnabled
            if status and isinstance(response, dict):
                # Convert response to string for searching
                response_str = json.dumps(response)
                if '"InbandUpdatePolicyEnabled": true' in response_str:
                    self.logger.info(f"Inband update policy is enabled for {ap_name}")
                    return True
                self.logger.warning(f"Inband update policy is not enabled for {ap_name}")
                return False
            self.logger.error(f"Failed to check inband update policy: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def set_gpu_inband_update_policy(
        self,
        *,
        base_uri: str,
        ap_name: str,
        data: Optional[Dict[str, Any]] = None,
        redfish_target: str = "bmc",
    ) -> bool:
        """
        Set the inband update policy for a specific GPU.

        Args:
            base_uri (str): Base URI for the Redfish endpoint (e.g., "/redfish/v1/Chassis")
            ap_name (str): AP identifier (e.g., "HGX_IRoT_GPU_0")
            data (Optional[Dict[str, Any]]): Optional data to override default request body.
                                           Defaults to {"Oem": {"Nvidia": {"InbandUpdatePolicyEnabled": true}}}
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy

        Returns:
            bool: True if policy was set successfully, False otherwise
        """
        redfish_timeout = self.config.config.get("settings", {}).get("redfish_timeout", 30)

        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            # Prepare the data
            if data is None:
                data = {"Oem": {"Nvidia": {"InbandUpdatePolicyEnabled": True}}}

            self.logger.info(f"Setting inband update policy for {ap_name} via {redfish_target.upper()}")

            # Use redfish_utils.patch_request
            status, response = redfish_utils.patch_request(
                self._join_url_path(base_uri, ap_name), data, timeout=redfish_timeout
            )

            if status:
                self.logger.info(f"Successfully set inband update policy for {ap_name}")
                return True
            self.logger.error(f"Failed to set inband update policy for {ap_name}: {response}")
            return False

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("redfish_operation")

    def execute_os_command(
        self,
        *,
        command: str,
        timeout: Optional[int] = None,
        use_sudo: bool = False,
        saved_stdout: Optional[Dict[str, str]] = None,
        saved_stderr: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Execute a command on the compute OS using SSH.

        Args:
            command (str): The command to execute
            timeout (Optional[int]): Optional timeout in seconds for the command execution
            use_sudo (bool): If True, executes the command with sudo. Defaults to False.
            saved_stdout (Optional[Dict[str, str]]): If provided, this dictionary will be updated with the command's stdout output
                                                   using the key 'output'.
            saved_stderr (Optional[Dict[str, str]]): If provided, this dictionary will be updated with the command's stderr output
                                                   using the key 'output'.

        Returns:
            bool: True if command executed successfully (return code 0), False otherwise
        """
        try:
            # Get OS connection details from config
            os_config = self.config.config.get("connection", {}).get("compute", {}).get("os", {})
            if not all(
                [
                    os_config.get("ip"),
                    os_config.get("username"),
                    os_config.get("password"),
                ]
            ):
                self.logger.error("Missing required OS connection details in config")
                return False

            # Create SSH client
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                ssh_timeout = self.config.config.get("settings", {}).get("ssh_timeout", 30)

                # Connect to OS
                self.logger.info(f"Connecting to OS at {os_config['ip']} (timeout: {ssh_timeout}s)")
                ssh_client.connect(
                    hostname=os_config["ip"],
                    port=os_config.get("port", 22),
                    username=os_config["username"],
                    password=os_config["password"],
                    timeout=ssh_timeout,
                )

                # print command being ran here, otherwise if sudo is used, the password will be printed
                self.logger.info(f"Executing command: {command}")
                # Modify command if sudo is needed
                if use_sudo:
                    # Escape special characters in the password
                    escaped_password = os_config["password"].replace('"', '\\"').replace("$", "\\$")
                    # Create the sudo command with password
                    command = f'echo "{escaped_password}" | sudo -S {command}'

                _, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)

                # Get output
                stdout_output = stdout.read().decode().strip()
                stderr_output = stderr.read().decode().strip()
                exit_status = stdout.channel.recv_exit_status()

                if saved_stdout is not None:
                    saved_stdout["output"] = stdout_output
                if saved_stderr is not None:
                    saved_stderr["output"] = stderr_output

                # Log output
                if stdout_output:
                    self.logger.info(f"Command stdout: {stdout_output}")
                if stderr_output:
                    self.logger.warning(f"Command stderr: {stderr_output}")

                # Check return code
                if exit_status == 0:
                    self.logger.info("Command executed successfully")
                    return True
                self.logger.error(f"Command failed with return code: {exit_status}")
                return False

            except Exception as e:
                error_msg = f"Failed to execute command: {str(e)}"
                self.logger.error(error_msg)
                return False

            finally:
                ssh_client.close()

        except Exception as e:
            error_msg = f"Unexpected error during command execution: {str(e)}"
            self.logger.error(error_msg)
            return False

    def flint_verify(self, named_device: str, file_name: str, use_sudo: bool = True, timeout: int = 300) -> bool:
        """
        Verify firmware using flint for a specific device.

        Args:
            named_device (str): The device name to search for in mst status output (e.g., "BlueField3")
            file_name (str): The firmware file path - basename will be extracted and assumed to be in target home directory
            use_sudo (bool): Whether to use sudo for commands. Defaults to True.
            timeout (int): Timeout in seconds for verify operations. Defaults to 300 (5 minutes).

        Returns:
            bool: True if all verifications passed, False otherwise
        """
        try:
            # Extract basename from file_name and assume it's in the target home directory
            firmware_basename = os.path.basename(file_name)
            firmware_path = f"~/{firmware_basename}"

            # Get device paths from mst status (use short timeout for quick command)
            mst_cmd = f"mst status -v | grep '{named_device}' | awk '{{print $2}}'"
            saved_stdout = {"output": ""}  # Use a dictionary to store the output
            if not self.execute_os_command(command=mst_cmd, use_sudo=use_sudo, saved_stdout=saved_stdout, timeout=30):
                self.logger.error(f"Failed to get device paths for {named_device}")
                return False

            self.logger.info(f"Saved stdout: {saved_stdout['output']}")
            # Get device paths from saved output
            device_paths = saved_stdout["output"].strip().split("\n")

            # Filter out paths ending with .N (where N is a number)
            device_paths = [path for path in device_paths if not any(path.endswith(f".{i}") for i in range(10))]

            if not device_paths:
                self.logger.error(f"No valid device paths found for {named_device}")
                return False

            # Verify each device
            all_verified = True
            for device_path in device_paths:
                verify_cmd = f"flint -d {device_path} -i {firmware_path} verify"
                self.logger.info(f"Verifying {device_path} with timeout of {timeout} seconds")
                if not self.execute_os_command(command=verify_cmd, use_sudo=use_sudo, timeout=timeout):
                    self.logger.error(f"Verification failed for device {device_path}")
                    all_verified = False

            return all_verified

        except Exception as e:
            self.logger.error(f"Unexpected error during flint verification: {str(e)}")
            return False

    def flint_flash(self, *, named_device: str, file_name: str, use_sudo: bool = True, timeout: int = 1800) -> bool:
        """
        Flash firmware using flint for a specific device.

        Args:
            named_device (str): The device name to search for in mst status output (e.g., "BlueField3")
            file_name (str): The firmware file path - basename will be extracted and assumed to be in target home directory
            use_sudo (bool): Whether to use sudo for commands. Defaults to True.
            timeout (int): Timeout in seconds for flash operations. Defaults to 1800 (30 minutes).

        Returns:
            bool: True if all images flashed successfully, False otherwise
        """
        try:
            # Extract basename from file_name and assume it's in the target home directory
            firmware_basename = os.path.basename(file_name)
            firmware_path = f"~/{firmware_basename}"

            # Get device paths from mst status (use short timeout for quick command)
            mst_cmd = f"mst status -v | grep '{named_device}' | awk '{{print $2}}'"
            saved_stdout = {"output": ""}  # Use a dictionary to store the output
            if not self.execute_os_command(command=mst_cmd, use_sudo=use_sudo, saved_stdout=saved_stdout, timeout=30):
                self.logger.error(f"Failed to get device paths for {named_device}")
                return False

            self.logger.info(f"Saved stdout: {saved_stdout['output']}")
            # Get device paths from saved output
            device_paths = saved_stdout["output"].strip().split("\n")
            self.logger.info(f"Device paths before filtering: {device_paths}")

            # Filter out paths ending with .N (where N is a number)
            device_paths = [path for path in device_paths if not any(path.endswith(f".{i}") for i in range(10))]
            self.logger.info(f"Device paths after filtering: {device_paths}")

            if not device_paths:
                self.logger.error(f"No valid device paths found for {named_device}")
                return False

            # Flash each device
            all_flashed = True
            for device_path in device_paths:
                flash_cmd = f"flint -d {device_path} --yes -i {firmware_path} b"
                saved_stdout = {"output": ""}
                saved_stderr = {"output": ""}

                self.logger.info(f"Flashing {device_path} with timeout of {timeout} seconds")
                if not self.execute_os_command(
                    command=flash_cmd,
                    use_sudo=use_sudo,
                    saved_stdout=saved_stdout,
                    saved_stderr=saved_stderr,
                    timeout=timeout,
                ):
                    # Check if the error is the "already updated" case, which should be treated as success
                    # The message can appear in either stdout or stderr
                    stdout_output = saved_stdout.get("output", "")
                    stderr_output = saved_stderr.get("output", "")

                    if (
                        "The firmware image was already updated on flash" in stdout_output
                        or "The firmware image was already updated on flash" in stderr_output
                    ):
                        self.logger.info(f"Device {device_path} firmware already up to date - treating as success")
                        continue

                    self.logger.error(f"Flash failed for device {device_path}")
                    all_flashed = False
                else:
                    self.logger.info(f"Flash completed successfully for device {device_path}")

            return all_flashed

        except Exception as e:
            self.logger.error(f"Unexpected error during flint flashing: {str(e)}")
            return False

    def execute_ipmitool_command(
        self,
        *,
        command: str,
        use_lanplus: bool = True,
        use_bmc_credentials: bool = True,
        timeout: Optional[int] = None,
        saved_stdout: Optional[Dict[str, str]] = None,
        saved_stderr: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Execute an ipmitool command locally using connection details from config.

        Args:
            command (str): The ipmitool command to execute (e.g., "chassis bootdev none clear-cmos=yes")
            use_sudo (bool): If True, executes the command with sudo. Defaults to False.
            use_lanplus (bool): If True, uses -I lanplus interface. Defaults to True.
            use_bmc_credentials (bool): If True, uses BMC credentials. If False, uses OS credentials. Defaults to True.
            timeout (Optional[int]): Optional timeout in seconds for the command execution
            saved_stdout (Optional[Dict[str, str]]): If provided, this dictionary will be updated with the command's stdout output
                                                   using the key 'output'.
            saved_stderr (Optional[Dict[str, str]]): If provided, this dictionary will be updated with the command's stderr output
                                                   using the key 'output'.

        Returns:
            bool: True if command executed successfully (return code 0), False otherwise
        """
        try:
            # Get connection details based on credential choice
            if use_bmc_credentials:
                cred_config = self.config.config.get("connection", {}).get("compute", {}).get("bmc", {})
                cred_type = "BMC"
            else:
                cred_config = self.config.config.get("connection", {}).get("compute", {}).get("os", {})
                cred_type = "OS"

            if not all(
                [
                    cred_config.get("ip"),
                    cred_config.get("username"),
                    cred_config.get("password"),
                ]
            ):
                self.logger.error(f"Missing required {cred_type} connection details in config")
                return False

            # Build the ipmitool command
            cmd = ["ipmitool"]

            # Add cipher suite (default to 17 as shown in example)
            cmd.extend(["-C", "17"])

            # Add interface
            if use_lanplus:
                cmd.extend(["-I", "lanplus"])

            # Add connection details
            cmd.extend(["-H", cred_config["ip"]])
            cmd.extend(["-U", cred_config["username"]])
            cmd.extend(["-P", cred_config["password"]])

            # Add the specific command (split it to handle arguments properly)
            cmd.extend(command.split())

            # Create a sanitized version of the command for logging (hide IP, username, password)
            log_cmd = []
            skip_next = False
            for _, arg in enumerate(cmd):
                if skip_next:
                    skip_next = False
                    if arg == cmd[cmd.index("-H") + 1]:  # IP address
                        log_cmd.append("[IP hidden]")
                    elif arg == cmd[cmd.index("-U") + 1]:  # username
                        log_cmd.append("[username hidden]")
                    elif arg == cmd[cmd.index("-P") + 1]:  # password
                        log_cmd.append("[password hidden]")
                    else:
                        log_cmd.append(arg)
                elif arg in ["-H", "-U", "-P"]:
                    log_cmd.append(arg)
                    skip_next = True
                else:
                    log_cmd.append(arg)

            self.logger.info(f"Executing ipmitool command locally using {cred_type} credentials: {' '.join(log_cmd)}")

            try:
                # Execute command locally
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)

                # Get output
                stdout_output = result.stdout.strip()
                stderr_output = result.stderr.strip()
                exit_status = result.returncode

                if saved_stdout is not None:
                    saved_stdout["output"] = stdout_output
                if saved_stderr is not None:
                    saved_stderr["output"] = stderr_output

                # Log output
                if stdout_output:
                    self.logger.info(f"ipmitool stdout: {stdout_output}")
                if stderr_output:
                    self.logger.warning(f"ipmitool stderr: {stderr_output}")

                # Check return code
                if exit_status == 0:
                    self.logger.info("ipmitool command executed successfully")
                    return True
                # Special case: sol deactivate can return exit code 1 with "already de-activated" message
                cmd_string = " ".join(cmd)
                sol_deactivate_in_cmd = "sol deactivate" in cmd_string
                already_deactivated_in_stderr = "already de-activated" in stderr_output

                if sol_deactivate_in_cmd and already_deactivated_in_stderr:
                    self.logger.info("SOL session was already deactivated (expected)")
                    return True
                self.logger.error(f"ipmitool command failed with return code: {exit_status}")
                return False

            except subprocess.TimeoutExpired:
                self.logger.error(f"ipmitool command timed out after {timeout} seconds")
                return False
            except Exception as e:
                error_msg = f"Failed to execute ipmitool command: {str(e)}"
                self.logger.error(error_msg)
                return False

        except Exception as e:
            error_msg = f"Unexpected error during ipmitool command execution: {str(e)}"
            self.logger.error(error_msg)
            return False

    def _start_ipmi_sol_logging(self, timestamp: str) -> Optional[str]:
        """
        Start IPMI SOL logging (single socket).

        Uses Python threading for output processing.

        Args:
            timestamp (str): Timestamp string in format YYYYMMDD_HHMMSS

        Returns:
            Optional[str]: log_file_path if successful, None otherwise
        """
        try:
            log_dir = get_log_directory()
            log_file_path = str(log_dir / f"boot_{timestamp}.log")

            self.logger.info(f"Starting IPMI SOL logging to {log_file_path}")

            # Remove existing log file if it exists
            if os.path.exists(log_file_path):
                os.remove(log_file_path)

            # First deactivate any existing SOL sessions
            self.logger.info("Deactivating any existing SOL sessions")
            _ = self.execute_ipmitool_command(command="sol deactivate", timeout=10)

            # Get BMC connection details
            bmc_config = self._get_bmc_connection_details("compute")

            # Build ipmitool sol activate command
            sol_cmd = [
                "ipmitool",
                "-C",
                "17",
                "-I",
                "lanplus",
                "-H",
                bmc_config["ip"],
                "-U",
                bmc_config["username"],
                "-P",
                bmc_config["password"],
                "sol",
                "activate",
            ]

            # Start SOL capture in background with timestamp processing
            log_file = open(log_file_path, "w", encoding="utf-8")

            try:
                # Create process that captures SOL output and adds timestamps
                sol_process = subprocess.Popen(
                    sol_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    bufsize=1,
                )

                # Thread to process SOL output and add timestamps
                def process_sol_output():
                    try:
                        for line in iter(sol_process.stdout.readline, ""):
                            if line:
                                # Remove carriage returns and add timestamp
                                clean_line = line.replace("\r", "").rstrip("\n")
                                timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
                                log_file.write(f"{timestamp} {clean_line}\n")
                                log_file.flush()
                    except Exception as e:
                        self.logger.error(f"Error processing SOL output: {e}")
                    finally:
                        log_file.close()

                # Start output processing thread
                output_thread = threading.Thread(target=process_sol_output, daemon=True)
                output_thread.start()

                # Store process info for cleanup
                self._sol_processes[log_file_path] = {
                    "process": sol_process,
                    "thread": output_thread,
                    "log_file": log_file,
                    "mode": "ipmi",
                }

                self.logger.info(f"IPMI SOL logging started successfully (PID: {sol_process.pid})")
                return log_file_path

            except Exception:
                # Close the file if we opened it but failed to start the process
                log_file.close()
                raise

        except Exception as e:
            self.logger.error(f"Failed to start IPMI SOL logging: {str(e)}")
            return None

    def _start_ssh_sol_logging(self, base_timestamp: str) -> Optional[str]:
        """
        Start SSH-based SOL logging for 1 or 2 sockets with matching timestamps.

        Uses Python threading for output processing (similar to IPMI SOL).

        Args:
            base_timestamp (str): Timestamp string used in filenames (YYYYMMDD_HHMMSS)

        Returns:
            Optional[str]: base_timestamp if successful, None otherwise
        """
        try:
            log_dir = get_log_directory()

            # Get BMC connection details
            bmc_config = self._get_bmc_connection_details("compute")
            bmc_ip = bmc_config["ip"]
            bmc_username = bmc_config["username"]
            bmc_password = bmc_config["password"]

            # Determine number of sockets (1P or 2P configuration)
            # Default to 2 sockets; future enhancement: auto-detect from system config
            socket_count = 2

            # Socket 0 (primary) - port 2200
            socket_0_log_path = str(log_dir / f"post_log_{base_timestamp}.txt")
            success_0 = self._start_ssh_sol_socket(
                log_file_path=socket_0_log_path,
                bmc_ip=bmc_ip,
                bmc_username=bmc_username,
                bmc_password=bmc_password,
                port=2200,
                socket_name="socket_0",
            )

            if not success_0:
                return None

            # Socket 1 (secondary) - port 2203
            if socket_count == 2:
                socket_1_log_path = str(log_dir / f"post_log_2_{base_timestamp}.txt")
                success_1 = self._start_ssh_sol_socket(
                    log_file_path=socket_1_log_path,
                    bmc_ip=bmc_ip,
                    bmc_username=bmc_username,
                    bmc_password=bmc_password,
                    port=2203,
                    socket_name="socket_1",
                )

                if not success_1:
                    # Clean up socket 0 if socket 1 fails
                    self.stop_sol_logging(socket_0_log_path)
                    return None

            return base_timestamp

        except Exception as e:
            self.logger.error(f"Failed to start SSH SOL logging: {str(e)}")
            return None

    def _start_ssh_sol_socket(
        self,
        *,
        log_file_path: str,
        bmc_ip: str,
        bmc_username: str,
        bmc_password: str,
        port: int,
        socket_name: str,
    ) -> bool:
        """
        Start SSH SOL logging for a single socket using paramiko.

        Uses the same process_sol_output pattern as IPMI SOL logging.

        Args:
            log_file_path (str): Path to the log file
            bmc_ip (str): BMC IP address
            bmc_username (str): BMC username
            bmc_password (str): BMC password
            port (int): SSH port (2200 for socket_0, 2203 for socket_1)
            socket_name (str): Socket identifier for logging

        Returns:
            bool: True if started successfully, False otherwise
        """
        try:
            self.logger.info(f"Starting SSH SOL logging for {socket_name} (port {port}) to {log_file_path}")

            # Remove existing log file if it exists
            if os.path.exists(log_file_path):
                os.remove(log_file_path)

            # Open log file
            log_file = open(log_file_path, "w", encoding="utf-8")

            try:
                # Create SSH client for this SOL port
                ssh_client = paramiko.SSHClient()
                ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # Connect to BMC SOL port
                self.logger.debug(f"Connecting to {bmc_username}@{bmc_ip}:{port}")
                ssh_client.connect(
                    hostname=bmc_ip,
                    port=port,
                    username=bmc_username,
                    password=bmc_password,
                    timeout=20,
                    look_for_keys=False,
                    allow_agent=False,
                )

                # Use invoke_shell() for interactive serial console stream
                # BMC SOL ports stream console output when a shell session is opened
                channel = ssh_client.invoke_shell()
                channel.setblocking(False)  # Non-blocking mode for reading

                # Thread to process SOL output and add timestamps
                # Same pattern as IPMI SOL logging
                def process_sol_output():
                    try:
                        buffer = ""
                        while True:
                            try:
                                # Read available data (non-blocking)
                                if channel.recv_ready():
                                    data = channel.recv(4096).decode("utf-8", errors="replace")
                                    if data:
                                        buffer += data
                                        # Process complete lines
                                        while "\n" in buffer:
                                            line, buffer = buffer.split("\n", 1)
                                            # Remove carriage returns and add timestamp
                                            clean_line = line.replace("\r", "").rstrip()
                                            if clean_line:  # Only log non-empty lines
                                                timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
                                                log_file.write(f"{timestamp} {clean_line}\n")
                                                log_file.flush()
                                else:
                                    # No data available, sleep briefly
                                    time.sleep(0.1)

                                # Check if channel is still open
                                if channel.closed:
                                    break
                            except Exception as e:
                                self.logger.debug(f"Error in SSH SOL read loop for {socket_name}: {e}")
                                time.sleep(0.1)
                    except Exception as e:
                        self.logger.error(f"Error processing SSH SOL output for {socket_name}: {e}")
                    finally:
                        # Write any remaining buffer content
                        if buffer.strip():
                            clean_line = buffer.replace("\r", "").rstrip()
                            timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
                            log_file.write(f"{timestamp} {clean_line}\n")
                        log_file.close()

                # Start output processing thread
                output_thread = threading.Thread(target=process_sol_output, daemon=True)
                output_thread.start()

                # Store connection info for cleanup
                self._sol_processes[log_file_path] = {
                    "ssh_client": ssh_client,
                    "channel": channel,
                    "thread": output_thread,
                    "log_file": log_file,
                    "mode": "ssh",
                    "socket": socket_name,
                }

                self.logger.info(f"SSH SOL connection established for {socket_name}")
                return True

            except paramiko.AuthenticationException:
                self.logger.error(f"SSH authentication failed for {socket_name}")
                log_file.close()
                return False
            except paramiko.SSHException as e:
                self.logger.error(f"SSH protocol error for {socket_name}: {str(e)}")
                log_file.close()
                return False
            except Exception:
                # Close the file if we opened it but failed to connect
                log_file.close()
                raise

        except Exception as e:
            self.logger.error(f"Failed to start SSH SOL for {socket_name}: {str(e)}")
            return False

    def stop_sol_logging(self, log_file_path: str) -> bool:
        """
        Stop SOL logging for the specified log file or timestamp.

        For IPMI mode: Pass the log file path
        For SSH mode: Pass the base timestamp string

        Args:
            log_file_path (str): Path to log file (IPMI) or base timestamp (SSH)

        Returns:
            bool: True if SOL logging stopped successfully, False otherwise
        """
        try:
            if not hasattr(self, "_sol_processes"):
                self.logger.warning("No SOL processes to stop")
                return True

            # For SSH mode, stop all processes matching the timestamp
            # A timestamp has no path separators (/ or \) and looks like: "20250107_143022"
            if "/" not in log_file_path and "\\" not in log_file_path and "_" in log_file_path:
                # Looks like a timestamp without path
                return self._stop_ssh_sol_logging_by_timestamp(log_file_path)

            # For IPMI mode or direct file path
            if log_file_path not in self._sol_processes:
                self.logger.warning(f"No SOL logging process found for {log_file_path}")
                return True

            process_info = self._sol_processes[log_file_path]
            mode = process_info.get("mode", "ipmi")

            if mode == "ipmi":
                return self._stop_ipmi_sol_logging(log_file_path, process_info)
            return self._stop_ssh_sol_logging(log_file_path, process_info)

        except Exception as e:
            self.logger.error(f"Failed to stop SOL logging: {str(e)}")
            return False

    def _stop_ipmi_sol_logging(self, log_file_path: str, process_info: Dict) -> bool:
        """Stop IPMI SOL logging."""
        try:
            sol_process = process_info["process"]
            log_file = process_info.get("log_file")
            thread = process_info.get("thread")

            self.logger.info(f"Stopping IPMI SOL logging for {log_file_path} (PID: {sol_process.pid})")

            # Terminate the SOL process
            try:
                sol_process.terminate()
                sol_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sol_process.kill()
                sol_process.wait()

            # Wait for the thread to finish
            if thread and thread.is_alive():
                thread.join(timeout=2.0)

            # Close log file if still open
            if log_file:
                try:
                    if not log_file.closed:
                        log_file.close()
                except Exception:
                    pass

            # Deactivate SOL session
            self.execute_ipmitool_command(command="sol deactivate", timeout=10)

            # Remove from tracking
            del self._sol_processes[log_file_path]

            self.logger.info("IPMI SOL logging stopped successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to stop IPMI SOL logging: {str(e)}")
            return False

    def _stop_ssh_sol_logging(self, log_file_path: str, process_info: Dict) -> bool:
        """Stop single SSH SOL logging connection (uses same pattern as IPMI)."""
        try:
            ssh_client = process_info.get("ssh_client")
            channel = process_info.get("channel")
            log_file = process_info.get("log_file")
            thread = process_info.get("thread")
            socket_name = process_info.get("socket", "unknown")

            self.logger.info(f"Stopping SSH SOL logging for {socket_name}")

            # Close the channel first
            if channel and not channel.closed:
                try:
                    channel.close()
                    self.logger.debug(f"SSH channel closed for {socket_name}")
                except Exception as e:
                    self.logger.warning(f"Error closing SSH channel: {str(e)}")

            # Close the SSH connection
            if ssh_client:
                try:
                    ssh_client.close()
                    self.logger.debug(f"SSH connection closed for {socket_name}")
                except Exception as e:
                    self.logger.warning(f"Error closing SSH connection: {str(e)}")

            # Wait for the thread to finish
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
                if thread.is_alive():
                    self.logger.warning(f"Thread did not finish within timeout for {socket_name}")

            # Close log file if still open
            if log_file:
                try:
                    if not log_file.closed:
                        log_file.close()
                except Exception:
                    pass

            # Remove from tracking
            del self._sol_processes[log_file_path]

            self.logger.info(f"SSH SOL logging stopped for {socket_name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to stop SSH SOL logging: {str(e)}")
            return False

    def _stop_ssh_sol_logging_by_timestamp(self, timestamp: str) -> bool:
        """Stop all SSH SOL processes matching the timestamp."""
        try:
            log_dir = get_log_directory()
            socket_0_log = str(log_dir / f"post_log_{timestamp}.txt")
            socket_1_log = str(log_dir / f"post_log_2_{timestamp}.txt")

            stopped_count = 0

            # Stop socket 0 if exists
            if socket_0_log in self._sol_processes:
                if self._stop_ssh_sol_logging(socket_0_log, self._sol_processes[socket_0_log]):
                    stopped_count += 1

            # Stop socket 1 if exists
            if socket_1_log in self._sol_processes:
                if self._stop_ssh_sol_logging(socket_1_log, self._sol_processes[socket_1_log]):
                    stopped_count += 1

            self.logger.info(f"Stopped {stopped_count} SSH SOL process(es)")
            return stopped_count > 0

        except Exception as e:
            self.logger.error(f"Failed to stop SSH SOL logging by timestamp: {str(e)}")
            return False

    def wait_for_boot(
        self,
        *,
        power_on_uri: str,
        system_uri: str,
        state: Union[str, List[str]],
        power_on_data: Optional[Dict[str, Any]] = None,
        timeout: int = 600,
    ) -> bool:
        """
        Boot system and wait for specific boot state with optional SOL logging.

        POST logging configuration is read from global compute config:
        - compute.post_logging_enabled: Enable/disable POST logging
        - compute.use_ssh_sol: Use SSH (true) or IPMI (false) for SOL

        Args:
            power_on_uri (str): Base URI for power control
            system_uri (str): Base URI for boot progress monitoring
            state (Union[str, List[str]]): Desired boot state(s) to wait for. Can be a single string like "OSRunning"
                                         or a list like ["OSRunning", "OSBootStarted"]
            power_on_data (Optional[Dict[str, Any]]): Optional data for power on command
            timeout (int): Maximum time to wait for boot (default: 600 seconds)

        Returns:
            bool: True if system successfully reached desired boot state, False otherwise
        """
        try:
            # Normalize state to a list for logging
            if isinstance(state, str):
                target_states = [state]
            else:
                target_states = list(state)

            # Get POST logging configuration from global config
            post_logging_enabled = self.config.config.get("compute", {}).get("post_logging_enabled", False)
            use_ssh_sol = self.config.config.get("compute", {}).get("use_ssh_sol", False)

            self.logger.info(
                f"Starting boot sequence waiting for states: {target_states} "
                f"(POST logging: {'SSH' if use_ssh_sol else 'IPMI'} - {'enabled' if post_logging_enabled else 'disabled'})"
            )

            # Generate timestamp once for matching log files
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_identifier = None

            if post_logging_enabled:
                try:
                    if use_ssh_sol:
                        log_identifier = self._start_ssh_sol_logging(timestamp)
                    else:
                        log_identifier = self._start_ipmi_sol_logging(timestamp)

                    if not log_identifier:
                        return False
                    self.logger.info(f"POST logging started: {log_identifier}")

                except Exception as e:
                    self.logger.error(f"Failed to setup POST logging: {str(e)}")
                    return False

            # Power on the system
            power_on_success = self.power_on(power_on_uri, power_on_data)
            if not power_on_success:
                if post_logging_enabled and log_identifier:
                    self.stop_sol_logging(log_identifier)
                return False

            # Check boot progress until desired state
            self.logger.info(f"Waiting for system to reach boot states: {target_states}...")
            boot_success = self.check_boot_progress(base_uri=system_uri, state=state, timeout=timeout)

            # Stop logging
            if post_logging_enabled and log_identifier:
                self.stop_sol_logging(log_identifier)

            if boot_success:
                self.logger.info(f"System has reached desired boot state from: {target_states}")
                return True

            self.logger.error(f"Timeout waiting for boot states {target_states} after {timeout} seconds")
            return False

        except Exception as e:
            self.logger.error(f"Error during boot sequence: {str(e)}")
            if post_logging_enabled and log_identifier:
                self.stop_sol_logging(log_identifier)
            return False

    def check_versions(
        self,
        *,
        expected_versions,
        operator,
        base_uri="/redfish/v1/UpdateService/FirmwareInventory/",
        redfish_target: str = "bmc",
    ):
        """
        Check the versions of the components against the expected versions.
        """
        # Get appropriate redfish utils
        try:
            redfish_utils = self._get_redfish_utils(redfish_target)
        except ValueError as e:
            self.logger.error(str(e))
            return False

        self.logger.info(
            f"Checking if system FW versions are {operator} than {expected_versions} via {redfish_target.upper()}"
        )
        failures = []
        for component, expected_version in expected_versions.items():
            if not validate_firmware_version_input(component, expected_version, self.logger):
                continue

            self.logger.info(f"Checking firmware version for {component} with base_uri: {base_uri}")
            status, response = redfish_utils.get_request(self._join_url_path(base_uri, component))
            self.logger.info(f"Response: {response}")
            if status and isinstance(response, dict):
                current_version = response.get("Version")
                self.logger.info(f"Current version on system for {component} is {current_version}")
                if current_version is None:
                    failures.append(f"FirmwareVersion not found in response for {component}")
                elif not Utils.compare_versions(current_version, expected_version, operator):
                    failures.append(
                        f"{component} firmware version comparison system: {current_version} {operator} expected: {expected_version} returned False"
                    )
                else:
                    self.logger.info(
                        f"{component} firmware version check system: {current_version} {operator} expected: {expected_version} : PASS"
                    )
            else:
                failures.append(f"Unexpected response format from {component}: {response}")
        if len(failures) > 0:
            self.logger.error(f"Firmware version check failures: {failures}")
            return False
        self.logger.info("Firmware version check passed for all tested components")
        return True

    def check_boot_status_code(
        self,
        *,
        ap_name: str,
        base_uri: str,
        timeout: Optional[int] = None,
        redfish_target: str = "bmc",
        check_interval: int = 30,
    ) -> bool:
        """
        Check the boot status code for a specific AP and monitor until it reaches 0x11 or times out.

        Args:
            ap_name (str): AP identifier (e.g., "HGX_ERoT_CPU_0")
            base_uri (str): Base URI for the Redfish endpoint
            timeout (Optional[int]): Maximum time in seconds to wait for boot status code to reach 0x11.
                                   If None, will only check once.
            redfish_target (str): "bmc" for direct BMC operations, "hmc" for HMC operations via BMC proxy
            check_interval (int): Polling interval between checks

        Returns:
            bool: True if boot status code is 0x11, False otherwise
        """
        try:
            # Get appropriate redfish utils
            try:
                redfish_utils = self._get_redfish_utils(redfish_target)
            except ValueError:
                return self._handle_redfish_exceptions("get_redfish_utils")

            start_time = time.time()

            while True:
                # Check if we've exceeded the timeout
                if timeout is not None and time.time() - start_time > timeout:
                    self.logger.error(f"Boot status code check timed out after {timeout} seconds")
                    return False

                self.logger.info(f"Checking boot status code for {ap_name}")
                status, response = redfish_utils.get_request(
                    self._join_url_path(base_uri, ap_name, "Oem/NvidiaRoT/RoTProtectedComponents/Self")
                )

                # Check if response contains BootStatusCode
                if status and isinstance(response, dict):
                    boot_status = response.get("BootStatusCode")
                    if boot_status is None:
                        self.logger.error("BootStatusCode not found in response")
                        if timeout is None:
                            return False
                        # Continue looping if timeout is specified
                    else:
                        # Extract the second byte (characters 15-16)
                        try:
                            second_byte = boot_status[14:16]
                            self.logger.info(f"Boot status code second byte: {second_byte}")

                            if second_byte == "11":
                                self.logger.info("Boot status code is 0x11 - Completed")
                                return True
                            self.logger.warning(f"Boot status code is not 0x11 (got 0x{second_byte}) - In Progress")
                            self.logger.warning(f"Entire boot status code: {boot_status}")
                            if timeout is None:
                                return False
                            # Continue looping if timeout is specified
                        except IndexError:
                            self.logger.error(f"Invalid boot status code format: {boot_status}")
                            if timeout is None:
                                return False
                            # Continue looping if timeout is specified
                else:
                    self.logger.error(f"Failed to get boot status code: {response}")
                    if timeout is None:
                        return False
                    # Continue looping if timeout is specified

                # If we're not using timeout, we've already returned False
                if timeout is None:
                    return False

                # Wait for the check interval before next attempt
                self.logger.info(f"Waiting {check_interval} seconds before next boot status code check")
                time.sleep(check_interval)

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("set_power_policy_always_off")

    def pass_test(self, message: str = "Test passed") -> bool:
        """
        Pass test operation - logs success message and returns True.
        Used in exit flows for successful state verification.

        Args:
            message (str): Success message to log. Defaults to "Test passed"

        Returns:
            bool: Always returns True
        """
        self.logger.info(f"PASS: {message}")
        return True

    def fail_test(self, message: str = "Test failed") -> bool:
        """
        Fail test operation - logs failure message and returns False.
        Used in exit flows for failed state verification.

        Args:
            message (str): Failure message to log. Defaults to "Test failed"

        Returns:
            bool: Always returns False
        """
        self.logger.error(f"FAIL: {message}")
        return False

    def install_mft_tools(self, tool_file_path: str) -> bool:
        """
        Install MFT tools by SCPing, extracting, and installing in a single operation.

        This function replaces the 3-step process of scp_mft_to_os, untar_mft, and install_mft.
        It handles dependency conflicts that can occur during MFT installation.

        Args:
            tool_file_path (str): Path to the MFT tool file (with or without .tgz extension)

        Returns:
            bool: True if installation was successful, False otherwise
        """
        self.logger.info(f"Installing MFT tools from: {tool_file_path}")

        # Extract basename and handle .tgz extension
        tool_basename = os.path.basename(tool_file_path)
        if not tool_basename.endswith(".tgz") and ".tgz" not in tool_file_path:
            # If no .tgz extension provided, assume it should be added
            tool_file_with_ext = tool_file_path + ".tgz" if not tool_file_path.endswith(".tgz") else tool_file_path
            tool_basename_with_ext = os.path.basename(tool_file_with_ext)
        else:
            tool_file_with_ext = tool_file_path
            tool_basename_with_ext = tool_basename

        # Extract base name without .tgz for directory operations
        if tool_basename_with_ext.endswith(".tgz"):
            tool_basename_no_ext = tool_basename_with_ext[:-4]  # Remove .tgz
        else:
            tool_basename_no_ext = tool_basename_with_ext

        self.logger.info(f"Using tool file: {tool_file_with_ext}")
        self.logger.info(f"Tool basename: {tool_basename_with_ext}")
        self.logger.info(f"Tool directory name: {tool_basename_no_ext}")

        try:
            # Step 1: SCP MFT tool to OS
            self.logger.info("Step 1: Transferring MFT tool to switch OS")
            if not self.scp_tool_to_os(tool_file_with_ext):
                self.logger.error("Failed to transfer MFT tool to switch OS")
                return False
            self.logger.info("Successfully transferred MFT tool to switch OS")

            # Step 2: Extract MFT tarball
            self.logger.info("Step 2: Extracting MFT tarball")
            extract_command = f"tar -xzf ~/{tool_basename_with_ext}"
            if not self.execute_os_command(command=extract_command, timeout=120):
                self.logger.error("Failed to extract MFT tarball")
                return False
            self.logger.info("Successfully extracted MFT tarball")

            # Step 3: Install MFT with dependency handling
            self.logger.info("Step 3: Installing MFT tools")

            # Generate install command using the extracted directory pattern
            # Pattern: ~/mft-4.32.0-*/install.sh
            mft_prefix = tool_basename_no_ext.split("-")[:3]  # Get first 3 parts (e.g., mft-4.32.0)
            mft_dir_pattern = "-".join(mft_prefix) + "-*"
            install_command = f"~/{mft_dir_pattern}/install.sh"

            self.logger.info(f"Attempting MFT installation with command: {install_command}")
            install_success = self.execute_os_command(command=install_command, use_sudo=True, timeout=300)

            # Check if installation succeeded
            if install_success:
                self.logger.info("MFT tools installation completed successfully")
                return True

            self.logger.error("MFT tools installation failed")
            return False

        except Exception as e:
            self.logger.error(f"Exception occurred during MFT tools installation: {str(e)}")
            return False
