# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""
Common Factory Flow Functions
This module contains shared functions for both switch and compute factory operations.
"""

import sys
import time
from typing import Any, Dict, Optional

from .utils import Utils


class CommonFactoryFlowMixin:
    """Mixin class providing common factory flow functionality for both switch and compute operations."""

    def _get_bmc_connection_details(self, device_type: str = None) -> Dict[str, str]:
        """
        Get BMC connection details from config.

        Args:
            device_type (str): Device type ("compute" or "switch"). If None, will try to auto-detect.

        Returns:
            Dict[str, str]: Dictionary containing ip, username, password, and protocol

        Raises:
            ValueError: If any required connection details are missing
        """
        # Auto-detect device type if not provided
        if device_type is None:
            # Try to determine from class name or config structure
            if hasattr(self, "__class__") and "Switch" in self.__class__.__name__:
                device_type = "switch"
            else:
                device_type = "compute"

        bmc_config = self.config.config.get("connection", {}).get(device_type, {}).get("bmc", {})
        self.logger.info("BMC config loaded")
        bmc_ip = bmc_config.get("ip")
        username = bmc_config.get("username")
        password = bmc_config.get("password")

        # if protocol is not set, set it to https
        if not bmc_config.get("protocol"):
            protocol = "https"
        else:
            protocol = bmc_config["protocol"].lower()

        self._validate_missing_credentials(bmc_ip, username, password, "BMC")

        return {
            "ip": bmc_ip,
            "username": username,
            "password": password,
            "protocol": protocol,
        }

    def _initialize_redfish_utils(self, device_type: str = None) -> None:
        """
        Initialize BMC redfish utils for power operations.

        Args:
            device_type (str): Device type ("compute" or "switch"). If None, will try to auto-detect.
        """
        try:
            bmc_config = self._get_bmc_connection_details(device_type)
            self.redfish_utils = Utils(
                dut_ip=bmc_config["ip"],
                dut_username=bmc_config["username"],
                dut_password=bmc_config["password"],
                dut_service_type=bmc_config["protocol"],
                logger=self.logger,
            )
            self.logger.info("BMC redfish utils initialized successfully")
        except Exception as e:
            self.logger.warning(f"Failed to initialize BMC redfish utils: {str(e)}. Power operations may not work.")
            self.redfish_utils = None

    def _join_url_path(self, base_uri: str, *path_parts: str) -> str:
        """
        Join base URI with path parts, handling trailing/leading slashes properly.

        Args:
            base_uri (str): Base URI that may or may not end with a slash
            *path_parts (str): Path parts to append

        Returns:
            str: Properly joined URL path
        """
        # Start with base_uri, remove trailing slash
        result = base_uri.rstrip("/")

        # Add each path part, ensuring single slashes
        for part in path_parts:
            if part:  # Skip empty parts
                result += "/" + part.strip("/")

        return result

    def _validate_missing_credentials(
        self, ip: str, username: str, password: str, connection_type: str = "connection"
    ) -> None:
        """
        Validate that required connection credentials are present.

        Args:
            ip (str): IP address or hostname
            username (str): Username
            password (str): Password
            connection_type (str): Type of connection for error messages (e.g., "BMC", "OS")

        Raises:
            ValueError: If any required credentials are missing
        """
        if not all([ip, username, password]):
            missing = []
            if not ip:
                missing.append("ip")
            if not username:
                missing.append("username")
            if not password:
                missing.append("password")
            raise ValueError(f"Missing required {connection_type} connection details: {', '.join(missing)}")

    def _handle_redfish_exceptions(self, operation_name: str) -> bool:
        """
        Common exception handling pattern for Redfish operations.
        This is a helper method to be used in try/except blocks.

        Args:
            operation_name (str): Name of the operation for logging context

        Returns:
            bool: Always returns False (for use in except blocks)
        """
        exc_type, exc_value, _ = sys.exc_info()

        if exc_type and issubclass(exc_type, ValueError):
            self.logger.error(f"BMC connection error in {operation_name}: {str(exc_value)}")
        else:
            self.logger.error(f"Unexpected error in {operation_name}: {str(exc_value)}")
        return False

    def _execute_redfish_operation_with_retry(self, operation_func, operation_name: str, *args, **kwargs):
        """
        Execute a Redfish operation with common exception handling.

        Args:
            operation_func: The function to execute
            operation_name (str): Name of the operation for logging
            *args: Arguments to pass to the operation function
            **kwargs: Keyword arguments to pass to the operation function

        Returns:
            The result of the operation function or False on error
        """
        try:
            return operation_func(*args, **kwargs)
        except ValueError as e:
            self.logger.error(f"BMC connection error in {operation_name}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error in {operation_name}: {str(e)}")
            return False

    def power_on(self, base_uri: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Power on the device using the ComputerSystem.Reset action and wait until power state is "On".

        Args:
            base_uri (str): Base URI for the Redfish endpoint
            data (Optional[Dict[str, Any]]): Optional data to override default request body

        Returns:
            bool: True if power on was successful and power state reached "On", False otherwise
        """
        timeout = 60
        check_interval = 5  # Check every 5 seconds

        try:
            # Prepare the data
            if data is None:
                data = {"ResetType": "On"}

            # Extract system URI from base_uri (e.g., /redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset -> /redfish/v1/Systems/System_0)
            system_uri = "/".join(
                base_uri.split("/")[:5]
            )  # Take first 5 parts: ['', 'redfish', 'v1', 'Systems', 'System_0']

            start_time = time.time()
            command_issued = False

            while True:
                # Check if we've exceeded the timeout
                if time.time() - start_time > timeout:
                    self.logger.error(f"Power on check timed out after {timeout} seconds")
                    return False

                # Issue power command if not yet done
                if not command_issued:
                    self.logger.info("Powering on device")
                    self.logger.info(f"Sending POST request to {base_uri} with data: {data}")
                    status, response = self.redfish_utils.post_request(base_uri, data)

                    # Check for success message in response
                    if not status or "error" in str(response).lower():
                        self.logger.error(f"Failed to power on device: {response}")
                        return False

                    self.logger.info("Successfully initiated power on (confirmed by response)")
                    command_issued = True

                    # Wait a moment for the command to take effect
                    time.sleep(2)

                # Check current power state
                status, response = self.redfish_utils.get_request(system_uri, timeout=30)

                if status and isinstance(response, dict):
                    power_state = response.get("PowerState")
                    self.logger.info(f"Current power state: {power_state}")

                    if power_state == "On":
                        self.logger.info("Device successfully powered on and confirmed in 'On' state")
                        return True
                    if power_state in ["PoweringOn"]:
                        self.logger.info(f"Device is powering on (state: {power_state}), continuing to wait...")
                    else:
                        # Unexpected power state - re-issue command
                        self.logger.warning(f"Unexpected power state: {power_state}, re-issuing power on command")
                        command_issued = False
                        continue
                else:
                    self.logger.error(f"Failed to check power state: {response}")

                # Wait before next check
                self.logger.info(f"Waiting {check_interval} seconds before next power state check")
                time.sleep(check_interval)

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("power_on")

    def power_off(
        self,
        base_uri: str,
        data: Optional[Dict[str, Any]] = None,
        check_volatile_dot: bool = False,
    ) -> bool:
        """
        Power off the device using the ComputerSystem.Reset action and wait until power state is "Off".

        Args:
            base_uri (str): Base URI for the Redfish endpoint
            data (Optional[Dict[str, Any]]): Optional data to override default request body
            check_volatile_dot (bool): If True, check DOT value in config and skip if not Volatile

        Returns:
            bool: True if power off was successful and power state reached "Off", False otherwise
        """
        # If check_volatile_dot is True, check the DOT value in config
        if check_volatile_dot:
            # Try to get DOT value from config - handle both compute and switch contexts
            dot_value = None
            if hasattr(self, "config") and hasattr(self.config, "config"):
                # Try compute context first
                dot_value = self.config.config.get("compute", {}).get("DOT")
                # If not found, try switch context
                if dot_value is None:
                    dot_value = self.config.config.get("switch", {}).get("DOT")

            if dot_value != "Volatile":
                self.logger.info("DOT is not set to 'Volatile', returning True")
                return True

        timeout = 30
        check_interval = 5  # Check every 5 seconds

        try:
            # Prepare the data
            if data is None:
                data = {"ResetType": "ForceOff"}

            # Extract system URI from base_uri (e.g., /redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset -> /redfish/v1/Systems/System_0)
            system_uri = "/".join(
                base_uri.split("/")[:5]
            )  # Take first 5 parts: ['', 'redfish', 'v1', 'Systems', 'System_0']

            start_time = time.time()
            command_issued = False

            while True:
                # Check if we've exceeded the timeout
                if time.time() - start_time > timeout:
                    self.logger.error(f"Power off check timed out after {timeout} seconds")
                    return False

                # Issue power command if not yet done
                if not command_issued:
                    self.logger.info("Powering off device")
                    status, response = self.redfish_utils.post_request(base_uri, data)

                    # Check for success message in response
                    if not status or "error" in str(response).lower():
                        self.logger.error(f"Failed to power off device: {response}")
                        return False

                    self.logger.info("Successfully initiated power off (confirmed by response)")
                    command_issued = True

                    # Wait a moment for the command to take effect
                    time.sleep(2)

                # Check current power state
                status, response = self.redfish_utils.get_request(system_uri, timeout=30)

                if status and isinstance(response, dict):
                    power_state = response.get("PowerState")
                    self.logger.info(f"Current power state: {power_state}")

                    if power_state == "Off":
                        self.logger.info("Device successfully powered off and confirmed in 'Off' state")
                        return True
                    if power_state in ["PoweringOff"]:
                        self.logger.info(f"Device is powering off (state: {power_state}), continuing to wait...")
                    else:
                        # Unexpected power state - re-issue command
                        self.logger.warning(f"Unexpected power state: {power_state}, re-issuing power off command")
                        command_issued = False
                        continue
                else:
                    self.logger.error(f"Failed to check power state: {response}")

                # Wait before next check
                self.logger.info(f"Waiting {check_interval} seconds before next power state check")
                time.sleep(check_interval)

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("power_off")
