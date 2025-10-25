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
Switch Factory Flow Functions
This module contains functions for managing switch factory operations including flashing, power management,
and firmware updates.
"""

import glob
import os
import shutil
import socket
import tempfile
import time
from typing import Any, Dict, Tuple, Union

import paramiko
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from FactoryMode.output_manager import setup_logging
from nvfwupd.deps.fwpkg_unpack import PLDMUnpack

from .base_connection_manager import BaseConnectionManager
from .common_factory_flow_functions import CommonFactoryFlowMixin
from .config_utils import ConfigLoader
from .shared_utils import validate_firmware_version_input
from .utils import Utils

# Disable SSL warnings for BMC connections
urllib3.disable_warnings(InsecureRequestWarning)


class SwitchFactoryFlowConfig:
    """Configuration manager for switch factory flow operations."""

    def __init__(self, config_path: str = "factory_flow_config.yaml"):
        """
        Initialize the configuration manager.

        Args:
            config_path (str): Path to the YAML configuration file
        """
        self.config_path = config_path
        self.config = ConfigLoader.load_config(config_path)
        self.connection = BaseConnectionManager(self.config, "switch")

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


class SwitchFactoryFlow(CommonFactoryFlowMixin):
    """Manages the switch factory update flow."""

    def __init__(self, config: SwitchFactoryFlowConfig, device_id: str, console_output: bool = False):
        """
        Initialize switch factory flow.

        Args:
            config (SwitchFactoryFlowConfig): Configuration manager
            device_id (str): Device identifier
            console_output (bool): Enable console logging output for LOG mode
        """
        self.config = config
        self.device_id = device_id
        # Setup module-specific logger
        self.logger = setup_logging("switch_factory_flow", console_output=console_output)

        # Initialize BMC redfish utils using shared method
        self._initialize_redfish_utils("switch")

    def _execute_nv_command(self, command: str, timeout: int = 60) -> Tuple[int, str, str]:
        """
        Execute an NV command via SSH.

        Args:
            command (str): The NV command to execute
            timeout (int): Command execution timeout in seconds

        Returns:
            Tuple[int, str, str]: (exit_code, stdout, stderr)
        """
        ssh = self.config.connection.get_ssh_client()
        _, stdout, stderr = ssh.exec_command(command, timeout=timeout)

        try:
            # Set a timeout for the channel operations
            stdout.channel.settimeout(timeout)

            # Read output while waiting for exit status
            stdout_data = stdout.read()
            stderr_data = stderr.read()

            # Get exit status - this will raise socket.timeout if it takes too long
            exit_code = stdout.channel.recv_exit_status()

            return exit_code, stdout_data.decode(), stderr_data.decode()

        except (OSError, paramiko.SSHException, socket.timeout) as e:
            # If we get a connection error or timeout while waiting for exit status,
            # it might be due to the remote system terminating the connection
            self.logger.warning(f"Connection terminated or timed out while waiting for command exit status: {str(e)}")
            self.config.connection.close()
            raise

    def _get_system_version(self) -> Dict[str, str]:
        """
        Internal method to execute 'nv show system version' command.
        This method can raise exceptions.

        Returns:
            Dict[str, str]: Dictionary containing version information

        Raises:
            RuntimeError: If the command fails
        """
        timeout = 10

        exit_code, stdout, stderr = self._execute_nv_command("nv show system version", timeout)
        if exit_code != 0:
            raise RuntimeError(f"Failed to get system version: {stderr}")
        self.logger.info(f"SwitchTray host OS version command: nv show system version returned exit code: {exit_code}")
        self.logger.info(f"SwitchTray host OS version command output: {stdout} stderr: {stderr}")
        # Parse the output into a dictionary
        version_info = {}
        for line in stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0]
                value = " ".join(parts[1:])  # Join all remaining parts as the value
                version_info[key.strip()] = value.strip()
        self.logger.info(f"SwitchTray host OS version: {version_info}")
        return version_info

    def show_system_version(self) -> Union[Dict[str, str], bool]:
        """
        Execute 'nv show system version' command.

        Returns:
            Union[Dict[str, str], bool]: Dictionary containing version information, or False if command fails
        """
        try:
            return self._get_system_version()
        except Exception as e:
            self.logger.error(f"Failed to get system version: {str(e)}")
            return False

    def _get_platform_firmware(self) -> Dict[str, str]:
        """
        Internal method to execute 'nv show platform firmware' command.
        This method can raise exceptions.

        Returns:
            Dict[str, str]: Dictionary containing firmware information

        Raises:
            RuntimeError: If the command fails
        """
        timeout = 60

        exit_code, stdout, stderr = self._execute_nv_command("nv show platform firmware", timeout)
        if exit_code != 0:
            raise RuntimeError(f"Failed to get platform firmware info: {stderr}")

        # Parse the output into a dictionary
        firmware_info = {}
        for line in stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0]
                value = parts[1]  # Join all remaining parts as the value
                firmware_info[key.strip()] = value.strip()
        self.logger.info(f"SwitchTray firmware version: {firmware_info}")
        return firmware_info

    def show_platform_firmware(self) -> Union[Dict[str, str], bool]:
        """
        Execute 'nv show platform firmware' command.

        Returns:
            Union[Dict[str, str], bool]: Dictionary containing firmware information, or False if command fails
        """
        try:
            return self._get_platform_firmware()
        except Exception as e:
            self.logger.error(f"Failed to get platform firmware info: {str(e)}")
            return False

    def _get_switch_os_home_directory(self) -> str:
        """
        Get the home directory path for switch OS connections.

        Returns:
            str: Home directory path, defaults to /home/{username} if not configured
        """
        switch_os_config = self.config.get_config("connection").get("switch", {}).get("os", {})
        username = switch_os_config.get("username", "")

        # Check if scp_target is configured (preferred)
        scp_target = switch_os_config.get("scp_target")
        if scp_target:
            return scp_target.rstrip("/")  # Remove trailing slash if present

        # Check if a custom home directory is configured (legacy)
        home_dir = switch_os_config.get("home_directory")
        if home_dir:
            return home_dir.rstrip("/")  # Remove trailing slash if present

        # Default to standard Linux home directory structure
        return f"/home/{username}" if username else "/tmp"

    def set_ssh_inactivity_timeout(self, timeout_seconds: int) -> bool:
        """
        Execute 'nv set system ssh-server inactivity-timeout' or 'nv set system ssh-server inactive-timeout' command.
        Tries both command variations to handle different system configurations gracefully.

        Args:
            timeout_seconds (int): SSH inactivity timeout in seconds

        Returns:
            bool: True if command was successful
        """
        timeout = 60

        # Try with 'inactivity-timeout' first
        command = f"nv set system ssh-server inactivity-timeout {timeout_seconds}"
        exit_code, stdout, stderr = self._execute_nv_command(command, timeout)
        self.logger.info(f"SwitchTray platform firmware command: {command} returned exit code: {exit_code}")
        self.logger.info(f"SwitchTray platform firmware command output: {stdout} stderr: {stderr}")

        # If first command fails, try with 'inactive-timeout'
        if exit_code != 0:
            self.logger.info("First command failed, trying alternative command variant")
            command = f"nv set system ssh-server inactive-timeout {timeout_seconds}"
            exit_code, stdout, stderr = self._execute_nv_command(command, timeout)
            self.logger.info(f"SwitchTray platform firmware command: {command} returned exit code: {exit_code}")
            self.logger.info(f"SwitchTray platform firmware command output: {stdout} stderr: {stderr}")

        if exit_code == 0:
            if self.apply_config():
                status = self.save_config()
                if status:
                    self.logger.info(
                        f"SSH inactivity timeout set to {timeout_seconds} seconds using command: {command}"
                    )
                    return True
                self.logger.error(f"Failed to save config: {stderr}")
                return False
            self.logger.error(f"Failed to apply config: {stderr}")
            return False
        self.logger.error(f"Failed to set SSH inactivity timeout with both command variants: {stderr}")
        return False

    def apply_config(self) -> bool:
        """
        Execute 'nv config apply' command.

        Returns:
            bool: True if command was successful
        """
        timeout = 300  # 5 minutes default

        exit_code, stdout, stderr = self._execute_nv_command("nv config apply", timeout)
        self.logger.info(f"SwitchTray platform firmware command: nv config apply returned exit code: {exit_code}")
        self.logger.info(f"SwitchTray platform firmware command output: {stdout} stderr: {stderr}")
        return exit_code == 0

    def save_config(self) -> bool:
        """
        Execute 'nv config save' command.

        Returns:
            bool: True if command was successful
        """
        timeout = 60

        exit_code, stdout, stderr = self._execute_nv_command("nv config save", timeout)
        self.logger.info(f"SwitchTray platform firmware command: nv config save returned exit code: {exit_code}")
        self.logger.info(f"SwitchTray platform firmware command output: {stdout} stderr: {stderr}")
        return exit_code == 0

    def fetch_and_install_switch_firmware(
        self,
        *,
        firmware_url: str,
        component: str,
        firmware_file_name: str = None,
        timeout: int = 900,
        reboot_config: str = "skip-reboot",
    ) -> bool:
        """
        Execute 'nv action fetch and install switch firmware' command.

        Args:
            firmware_url (str): URL of the firmware to fetch
            component (str): Component to install
            timeout (int): Command execution timeout in seconds
            reboot_config (str): Reboot configuration ("skip-reboot" or "reboot no")

        Returns:
            bool: True if command was successful
        """
        timeout = 900  # 15 minutes default

        # Determine the filename to use
        if firmware_file_name:
            # Use basename of provided firmware_file_name and construct file:// URL
            filename = os.path.basename(firmware_file_name)
            # Get switch OS home directory path
            home_path = self._get_switch_os_home_directory()
            full_url = f"file://{home_path}/{filename}"
        else:
            # Use firmware_url directly and extract filename from it
            full_url = firmware_url
            filename = firmware_url.split("/")[-1]

        command = f"nv action fetch platform firmware {component} {full_url}"
        exit_code, stdout, stderr = self._execute_nv_command(command, timeout)
        self.logger.info(f"Fetch switch firmware command: {command} returned exit code: {exit_code}")
        self.logger.info(f"Fetch command output: {stdout} stderr: {stderr}")
        if exit_code == 0:
            command = f"nv action install platform firmware {component} files {filename} {reboot_config}"
            self.logger.info(f"Executing install switch firmware command: {command}")
            exit_code, stdout, stderr = self._execute_nv_command(command, timeout)
            self.logger.info(f"Install switch firmware command returned exit code: {exit_code}")
            self.logger.info(f"Install command output: {stdout} stderr: {stderr}")
        return exit_code == 0

    def fetch_and_install_nvos(
        self, *, firmware_url: str, firmware_file_name: str = None, timeout: int = 900, reboot_config: str = "reboot no"
    ) -> bool:
        """
        Execute 'nv action fetch and install switch NVOS' command.

        Args:
            firmware_url (str): URL of the firmware to fetch
            firmware_file_name (str, optional): Firmware file name to use. If provided, basename is appended to URL
            timeout (int): Command execution timeout in seconds
            reboot_config (str): Reboot configuration ("skip-reboot" or "reboot no")

        Returns:
            bool: True if command was successful
        """
        timeout = 900  # 15 minutes default

        # Determine the filename to use
        if firmware_file_name:
            # Use basename of provided firmware_file_name and construct file:// URL
            filename = os.path.basename(firmware_file_name)
            # Get switch OS home directory path
            home_path = self._get_switch_os_home_directory()
            full_url = f"file://{home_path}/{filename}"
        else:
            # Use firmware_url directly and extract filename from it
            full_url = firmware_url
            filename = firmware_url.split("/")[-1]

        command = f"nv action fetch system image {full_url}"
        # logger.info(f"Executing fetch os image command: {command}")
        exit_code, stdout, stderr = self._execute_nv_command(command, timeout)
        self.logger.info(f"Fetch switch firmware command: {command} returned exit code: {exit_code}")
        self.logger.info(f"Fetch command output: {stdout} stderr: {stderr}")
        if exit_code == 0:
            command = f"nv action install system image files {filename} {reboot_config}"
            self.logger.info(f"Executing switch os command: {command}")
            exit_code, stdout, stderr = self._execute_nv_command(command, timeout)
            self.logger.info(f"Install switch os returned exit code: {exit_code}")
            self.logger.info(f"Install command output: {stdout} stderr: {stderr}")
        return exit_code == 0

    def fetch_platform_firmware(self, firmware_url: str) -> bool:
        """
        Execute 'nv action fetch platform firmware' command.

        Args:
            firmware_url (str): URL of the firmware to fetch

        Returns:
            bool: True if command was successful
        """
        timeout = 600  # 10 minutes default

        command = f"nv action fetch platform firmware {firmware_url}"
        exit_code, _, _ = self._execute_nv_command(command, timeout)
        return exit_code == 0

    def install_platform_firmware(self) -> bool:
        """
        Execute 'nv action install platform firmware' command.

        Returns:
            bool: True if command was successful
        """
        timeout = 900  # 15 minutes default

        exit_code, _, _ = self._execute_nv_command("nv action install platform firmware", timeout)
        return exit_code == 0

    def fetch_system_image(self, image_url: str) -> bool:
        """
        Execute 'nv action fetch system image files' command.

        Args:
            image_url (str): URL of the system image to fetch

        Returns:
            bool: True if command was successful
        """
        timeout = 600  # 10 minutes default

        command = f"nv action fetch system image files {image_url}"
        exit_code, _, _ = self._execute_nv_command(command, timeout)
        return exit_code == 0

    def install_system_image(self) -> bool:
        """
        Execute 'nv action install system image files' command.

        Returns:
            bool: True if command was successful
        """
        timeout = 900  # 15 minutes default

        exit_code, _, _ = self._execute_nv_command("nv action install system image files", timeout)
        return exit_code == 0

    def reboot_system(self, os_boot_timeout: int = 900) -> bool:
        """
        Execute 'nv action reboot system' command, wait 120 seconds, then call power_on
        to ensure the system is powering on. Then loop until SSH connection is established
        and show_system_version succeeds.
        Note: This command will terminate the SSH connection as the system reboots.

        Args:
            os_boot_timeout (int): Maximum time to wait for OS boot and SSH connectivity (default: 600 seconds / 10 minutes)

        Returns:
            bool: True if the reboot, power_on, and OS boot verification all succeed
        """
        timeout = 60

        try:
            # Execute reboot command - we don't expect a response since connection will be terminated
            self._execute_nv_command("nv action reboot system", timeout)
            self.logger.info("Reboot command sent successfully - connection will be terminated")
        except Exception as e:
            # Any other unexpected errors
            self.logger.error(f"Unexpected error during reboot: {str(e)}")
            self.logger.info("Attempting power cycle as backup recovery method")
            if not self.power_cycle_system():
                self.logger.error("Power cycle backup method also failed")
                return False
            self.logger.info("Power cycle completed successfully, continuing with regular flow")

        # Wait for 120 seconds after issuing reboot command
        self.logger.info("Waiting 120 seconds for system to reboot...")
        time.sleep(120)

        # Call power_on to ensure the system is powering on
        self.logger.info("Calling power_on to ensure system is powering on")
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        data = {"ResetType": "On"}

        power_on_success = self.power_on(base_uri, data)
        if not power_on_success:
            self.logger.error("System reboot completed but power_on failed")
            return False

        self.logger.info("Power_on completed successfully, now waiting for OS boot and SSH connectivity")

        # Loop until SSH connection is established and show_system_version succeeds
        start_time = time.time()
        check_interval = 10  # Check every 10 seconds

        while time.time() - start_time < os_boot_timeout:
            try:
                # Try to get system version - this will test SSH connectivity and OS readiness
                self.logger.info("Attempting to connect via SSH and run show_system_version")
                version_info = self.show_system_version()

                if version_info:
                    # show_system_version succeeded
                    elapsed_time = int(time.time() - start_time)
                    self.logger.info(
                        f"SSH connection established and show_system_version succeeded after {elapsed_time} seconds"
                    )
                    self.logger.info("System reboot, power_on, and OS boot verification completed successfully")
                    return True

                # show_system_version failed - SSH connection or OS not ready
                elapsed_time = int(time.time() - start_time)
                remaining_time = os_boot_timeout - elapsed_time
                self.logger.info(
                    f"SSH connection or OS not ready yet ({elapsed_time}s elapsed, {remaining_time}s remaining)"
                )

            except Exception as e:
                # Connection or other error occurred
                elapsed_time = int(time.time() - start_time)
                remaining_time = os_boot_timeout - elapsed_time
                self.logger.info(
                    f"Connection attempt failed: {str(e)} ({elapsed_time}s elapsed, {remaining_time}s remaining)"
                )

            # Wait before next attempt
            self.logger.info(f"Waiting {check_interval} seconds before next connection attempt")
            time.sleep(check_interval)

        # Timeout reached
        self.logger.error(f"SSH connectivity verification timed out after {os_boot_timeout} seconds")
        return False

    def power_cycle_system(self) -> bool:
        """
        Power cycle the system using redfish ComputerSystem.Reset action with PowerCycle.
        This is used as a backup method when regular reboot fails.

        Returns:
            bool: True if power cycle command was sent successfully, False otherwise
        """
        try:
            self.logger.info("Attempting system power cycle via redfish")
            base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
            data = {"ResetType": "PowerCycle"}

            self.logger.info(f"Sending POST request to {base_uri} with data: {data}")
            status, response = self.redfish_utils.post_request(base_uri, data)

            # Check for success message in response
            if not status or "error" in str(response).lower():
                self.logger.error(f"Failed to power cycle system: {response}")
                return False

            self.logger.info("Power cycle command sent successfully via redfish")
            return True

        except (ValueError, Exception):
            return self._handle_redfish_exceptions("power_cycle_system")

    def check_fw_versions(self, expected_versions, operator):
        """
        Check the versions of the components against the expected versions.
        """
        failures = []
        self.logger.info(f"Checking if system FW versions are {operator} than {expected_versions}")
        sys_versions = self.show_platform_firmware()
        if not sys_versions:
            failures.append("Failed to get system firmware versions")
            return False
        for component, expected_version in expected_versions.items():
            if not validate_firmware_version_input(component, expected_version, self.logger):
                continue
            current_version = sys_versions.get(component)
            if current_version is None:
                failures.append(f"FirmwareVersion not found in response for {component}")
            if not Utils.compare_versions(current_version, expected_version, operator):
                failures.append(
                    f"{component} firmware version comparison system: {current_version} {operator} expected: {expected_version} returned False"
                )
        if len(failures) > 0:
            self.logger.error(f"Firmware version check failures: {failures}")
            return False
        self.logger.info("Firmware version check passed for all components")
        return True

    def check_os_versions(self, expected_versions, operator):
        """
        Check the versions of the components against the expected versions.
        """
        self.logger.info(f"Checking if system OS versions are {operator} than {expected_versions}")
        sys_versions = self.show_system_version()
        if not sys_versions:
            self.logger.error("Failed to get system OS versions")
            return False

        # Try to get version from product-release first, then build-id, then image as fallback
        sys_version = sys_versions.get("product-release")
        if not sys_version:
            sys_version = sys_versions.get("build-id")
            if sys_version and sys_version.lower().startswith("nvos-"):
                # Strip the "nvos-" prefix to match expected version format
                sys_version = sys_version[5:]
        if not sys_version:
            sys_version = sys_versions.get("image")

        if not sys_version:
            self.logger.error("Failed to get system OS versions - none of product-release, build-id, or image found")
            return False

        expected_nvos_version = expected_versions.get("nvos")
        if expected_nvos_version is None or expected_nvos_version == "" or expected_nvos_version == "None":
            self.logger.info("Skipping firmware version check for NVOS because expected version is None or empty")
            return True
        if not Utils.compare_versions(sys_version, expected_nvos_version, operator):
            self.logger.error(
                f"System OS version comparison system: {sys_version} {operator} expected: {expected_versions} returned False"
            )
            return False
        self.logger.info(f"System OS version check passed for {sys_version}")
        return True

    def extract_scp_fetch_and_install_cpld_firmware(
        self, *, firmware_url: str, fwpkg_file_path: str, component: str
    ) -> bool:
        """
        Extract CPLD firmware from a firmware package, SCP it to the switch OS, and install it.

        This function unpacks a firmware package, finds the CPLD component file,
        transfers it to the switch OS home directory, and then calls fetch_and_install_switch_firmware
        to install the CPLD firmware using the extracted filename.

        Args:
            firmware_url (str): Base URL for firmware location (e.g., "file://", "scp://user:pass@host/path")
            fwpkg_file_path (str): Path to the firmware package file (.fwpkg)
            component (str): Component type for firmware installation

        Returns:
            bool: True if extraction, transfer, and installation were successful, False otherwise
        """
        self.logger.info(
            f"Extracting, transferring, and installing {component} from firmware package: {fwpkg_file_path}"
        )

        # Verify firmware package file exists
        if not os.path.exists(fwpkg_file_path):
            self.logger.error(f"Firmware package file not found: {fwpkg_file_path}")
            return False

        # Create temporary directory for unpacking
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="cpld_extract_")
            self.logger.debug(f"Created temporary directory: {temp_dir}")

            # Unpack firmware package
            pldm_unpacker = PLDMUnpack()
            pldm_unpacker.unpack = True
            pldm_unpacker.verbose = False

            self.logger.debug("Attempting to unpack firmware package using PLDMUnpack")
            try:
                result = pldm_unpacker.unpack_pldm_package(fwpkg_file_path, temp_dir)
                if not result:
                    self.logger.error(
                        f"PLDMUnpack failed to unpack firmware package: {fwpkg_file_path}. "
                        f"This could indicate a corrupted package, unsupported format, or insufficient permissions."
                    )
                    return False
                self.logger.debug(f"Successfully unpacked firmware package to {temp_dir}")
            except Exception as unpack_error:
                self.logger.error(
                    f"PLDMUnpack threw exception while unpacking {fwpkg_file_path}: {str(unpack_error)}. "
                    f"Check package integrity and format compatibility."
                )
                return False

            # Find CPLD file in unpacked files
            self.logger.debug(f"Searching for {component} file in unpacked directory: {temp_dir}")
            cpld_file = self._find_cpld_file(temp_dir)
            if not cpld_file:
                # List available files for debugging
                try:
                    available_files = os.listdir(temp_dir)
                    self.logger.error(
                        f"No {component} file found in unpacked firmware package. "
                        f"Available files in {temp_dir}: {available_files}. "
                        f"Check if the firmware package contains the expected {component} component."
                    )
                except OSError as list_error:
                    self.logger.error(
                        f"No {component} file found in unpacked firmware package and "
                        f"failed to list directory contents: {str(list_error)}"
                    )
                return False

            self.logger.info(f"Found {component} file: {os.path.basename(cpld_file)}")

            # SCP CPLD file to switch OS
            self.logger.debug(f"Transferring {component} file to switch OS: {cpld_file}")
            try:
                success = self._scp_cpld_file_to_switch_os(cpld_file)
                if not success:
                    self.logger.error(
                        f"Failed to transfer {component} file to switch OS. "
                        f"Check network connectivity, SSH credentials, and target directory permissions."
                    )
                    return False
            except Exception as scp_error:
                self.logger.error(
                    f"Exception occurred during {component} file transfer: {str(scp_error)}. "
                    f"Verify SSH configuration and network connectivity."
                )
                return False

            self.logger.info(f"Successfully transferred {component} file to switch OS")

            # Extract just the filename for use with fetch_and_install_switch_firmware
            firmware_filename = os.path.basename(cpld_file)
            self.logger.info(f"Calling fetch_and_install_switch_firmware with {component} file: {firmware_filename}")

            # Call fetch_and_install_switch_firmware with the extracted firmware filename
            try:
                install_success = self.fetch_and_install_switch_firmware(
                    firmware_url=firmware_url,
                    firmware_file_name=firmware_filename,
                    component=component,
                    timeout=900,
                    reboot_config="skip-reboot",
                )

                if install_success:
                    self.logger.info(f"Successfully installed {component} firmware")
                    return True

                self.logger.error(
                    f"Failed to install {component} firmware. "
                    f"The fetch_and_install_switch_firmware call returned False. "
                    f"Check switch connectivity, firmware compatibility, and installation logs."
                )
                return False
            except Exception as install_error:
                self.logger.error(
                    f"Exception occurred during {component} firmware installation: {str(install_error)}. "
                    f"Check switch state, command syntax, and system resources."
                )
                return False

        except Exception as e:
            self.logger.error(f"Exception occurred during {component} extraction, transfer, and installation: {str(e)}")
            return False

        finally:
            # Clean up temporary directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    self.logger.debug(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean up temporary directory {temp_dir}: {str(e)}")

    def _find_cpld_file(self, directory: str) -> str:
        """
        Find CPLD file in the unpacked firmware directory.

        Uses intelligent selection when multiple CPLD files are found:
        1. Prioritizes files with specific CPLD patterns
        2. Prefers common firmware extensions (.bin, .img, .hex)
        3. Selects the most likely candidate based on naming conventions

        Args:
            directory (str): Directory to search for CPLD files

        Returns:
            str: Path to CPLD file, empty string if not found
        """
        all_candidates = []

        # Common CPLD file patterns in order of preference
        cpld_patterns = [
            "*cpld*",
            "*CPLD*",
            "*_cpld_*",
            "*_CPLD_*",
        ]

        # Collect all matching files with their priority scores
        for priority, pattern in enumerate(cpld_patterns):
            matching_files = glob.glob(os.path.join(directory, pattern))
            for match in matching_files:
                if os.path.isfile(match):
                    all_candidates.append((match, priority, "pattern"))
                    self.logger.debug(f"Found CPLD candidate with pattern '{pattern}': {match}")

        # If no pattern matches found, look for common file extensions
        if not all_candidates:
            for ext in ["*.bin", "*.img", "*.hex"]:
                matching_files = glob.glob(os.path.join(directory, ext))
                for file_path in matching_files:
                    if os.path.isfile(file_path):
                        filename = os.path.basename(file_path).lower()
                        if "cpld" in filename:
                            # Assign priority based on extension preference
                            ext_priority = {"*.bin": 0, "*.img": 1, "*.hex": 2}.get(ext, 3)
                            all_candidates.append((file_path, ext_priority, "extension"))
                            self.logger.debug(f"Found CPLD candidate by extension and name: {file_path}")

        if not all_candidates:
            return ""

        # Select the best candidate
        if len(all_candidates) == 1:
            selected_file = all_candidates[0][0]
            self.logger.debug(f"Single CPLD file found: {selected_file}")
            return selected_file

        # Multiple candidates - select intelligently
        # Sort by priority (lower number = higher priority), then by method, then by filename
        all_candidates.sort(key=lambda x: (x[1], x[2], os.path.basename(x[0]).lower()))
        selected_file = all_candidates[0][0]

        self.logger.info(
            f"Multiple CPLD candidates found. Selected: {os.path.basename(selected_file)} "
            f"(priority: {all_candidates[0][1]}, method: {all_candidates[0][2]})"
        )

        # Log other candidates for troubleshooting
        other_candidates = [os.path.basename(candidate[0]) for candidate in all_candidates[1:]]
        if other_candidates:
            self.logger.debug(f"Other CPLD candidates not selected: {other_candidates}")

        return selected_file

    def _scp_cpld_file_to_switch_os(self, file_path: str) -> bool:
        """
        SCP a CPLD file to the switch OS home directory using shared SCP functionality.

        Args:
            file_path (str): Local file path to transfer

        Returns:
            bool: True if transfer was successful, False otherwise
        """
        # Get OS connection details from config
        os_config = self.config.config.get("connection", {}).get("switch", {}).get("os", {})

        # Use the shared SCP functionality from BaseConnectionManager
        return self.config.connection.scp_files_target(
            files=file_path,
            target_config=os_config,
            remote_base_path="",  # Default to user home
            set_executable=False,  # CPLD files don't need execute permissions
            logger=self.logger,
        )

    def scp_tool_to_os(self, tool_file_path: str) -> bool:
        """
        SCP a tool file to the switch OS home directory using configured credentials.

        Note: Only the basename of the file is transferred to the target home directory.
        For example, '/path/to/tools/file.tgz' becomes '~/file.tgz' on the target.

        Args:
            tool_file_path (str): Path to the tool file to transfer - basename will be extracted

        Returns:
            bool: True if transfer was successful, False otherwise
        """
        # Get OS connection details from config
        os_config = self.config.config.get("connection", {}).get("switch", {}).get("os", {})
        return self.config.connection.scp_tool_to_os(tool_file_path, os_config, logger=self.logger)
