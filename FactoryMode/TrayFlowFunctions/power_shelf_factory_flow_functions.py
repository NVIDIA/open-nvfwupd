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
Power Shelf Factory Flow Functions
This module contains functions for managing power shelf factory operations including power management,
firmware updates, and health monitoring.
"""

from typing import Any, Dict, Optional

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from .base_connection_manager import BaseConnectionManager
from .config_utils import ConfigLoader

# Disable SSL warnings for BMC connections
urllib3.disable_warnings(InsecureRequestWarning)


class PowerShelfFactoryFlowConfig:
    """Configuration manager for power shelf factory flow operations."""

    def __init__(self, config_path: str = "factory_flow_config.yaml"):
        """
        Initialize the configuration manager.

        Args:
            config_path (str): Path to the YAML configuration file
        """
        self.config_path = config_path
        self.config = ConfigLoader.load_config(config_path)
        self.connection = BaseConnectionManager(self.config, "power_shelf")

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


class PowerShelfFactoryFlow:
    """Manages the power shelf factory update flow."""

    def __init__(self, config: PowerShelfFactoryFlowConfig, device_id: str):
        """
        Initialize power shelf factory flow.

        Args:
            config (PowerShelfFactoryFlowConfig): Configuration manager
            device_id (str): Device identifier
        """
        self.config = config
        self.device_id = device_id

    def _execute_bmc_command(self, endpoint: str, method: str = "GET", data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute a command via BMC REST API.

        Args:
            endpoint (str): API endpoint
            method (str): HTTP method (GET, POST, PUT)
            data (Optional[Dict]): Request data for POST/PUT methods

        Returns:
            Dict[str, Any]: Response data
        """
        session = self.config.connection.get_bmc_session()
        url = self.config.connection.get_bmc_url(endpoint)

        try:
            if method == "GET":
                response = session.get(url)
            elif method == "POST":
                response = session.post(url, json=data)
            elif method == "PUT":
                response = session.put(url, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"BMC command failed: {str(e)}") from e

    def update_firmware(self, firmware_path: str) -> bool:
        """
        Update the power shelf firmware.

        Args:
            firmware_path (str): Path to the firmware file

        Returns:
            bool: True if update was successful
        """
        timeout = 900  # 15 minutes default

        try:
            with open(firmware_path, "rb") as f:
                firmware_data = f.read()

            session = self.config.connection.get_bmc_session()
            url = self.config.connection.get_bmc_url("redfish/v1/UpdateService/update")

            response = session.post(
                url,
                files={"UpdateFile": firmware_data},
                headers={"Content-Type": "multipart/form-data"},
                timeout=timeout,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            raise RuntimeError(f"Firmware update failed: {str(e)}") from e

    def _get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Internal method to get the status of a specific task.
        This method can raise exceptions.

        Args:
            task_id (str): The ID of the task to check

        Returns:
            Dict[str, Any]: Dictionary containing task status information

        Raises:
            RuntimeError: If the task is not found or request fails
        """
        try:
            return self._execute_bmc_command(f"redfish/v1/TaskService/Tasks/{task_id}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise RuntimeError(f"Task {task_id} not found") from e
            raise RuntimeError(f"Failed to get task status: {str(e)}") from e

    def _get_pmc_version(self) -> Dict[str, str]:
        """
        Internal method to check the version of the Power Management Controller (PMC).
        This method can raise exceptions.

        Returns:
            Dict[str, str]: Dictionary containing PMC version information

        Raises:
            RuntimeError: If PMC information is not found or request fails
        """
        try:
            response = self._execute_bmc_command("redfish/v1/Chassis/PowerShelf/Managers/PMC")
            return {
                "version": response.get("FirmwareVersion", "Unknown"),
                "model": response.get("Model", "Unknown"),
                "manufacturer": response.get("Manufacturer", "Unknown"),
            }
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise RuntimeError("PMC information not found") from e
            raise RuntimeError(f"Failed to get PMC version: {str(e)}") from e

    def check_pmc_version(self) -> Dict[str, str]:
        """
        Check the version of the Power Management Controller (PMC).

        Returns:
            Dict[str, str]: Dictionary containing PMC version information, or False if PMC not found or request fails
        """
        try:
            return self._get_pmc_version()
        except Exception as e:
            # Log the error details for debugging
            print(f"Failed to get PMC version: {str(e)}")
            return False

    def _get_psu_health_version(self, psu_id: int) -> Dict[str, Any]:
        """
        Internal method to check the health and version information of a specific Power Supply Unit (PSU).
        This method can raise exceptions.

        Args:
            psu_id (int): The ID of the PSU to check

        Returns:
            Dict[str, Any]: Dictionary containing PSU health and version information

        Raises:
            RuntimeError: If PSU is not found or request fails
        """
        try:
            response = self._execute_bmc_command(f"redfish/v1/Chassis/PowerShelf/PowerSupplies/{psu_id}")
            return {
                "version": response.get("FirmwareVersion", "Unknown"),
                "health": response.get("Status", {}).get("Health", "Unknown"),
                "state": response.get("Status", {}).get("State", "Unknown"),
                "model": response.get("Model", "Unknown"),
                "manufacturer": response.get("Manufacturer", "Unknown"),
                "serial_number": response.get("SerialNumber", "Unknown"),
                "part_number": response.get("PartNumber", "Unknown"),
                "power_capacity_watts": response.get("PowerCapacityWatts", 0),
                "power_supply_type": response.get("PowerSupplyType", "Unknown"),
                "line_input_voltage": response.get("LineInputVoltage", 0),
                "line_input_voltage_type": response.get("LineInputVoltageType", "Unknown"),
            }
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise RuntimeError(f"PSU {psu_id} not found") from e
            raise RuntimeError(f"Failed to get PSU health and version: {str(e)}") from e

    def check_psu_health_version(self, psu_id: int) -> Dict[str, Any]:
        """
        Check the health and version information of a specific Power Supply Unit (PSU).

        Args:
            psu_id (int): The ID of the PSU to check

        Returns:
            Dict[str, Any]: Dictionary containing PSU health and version information, or False if PSU not found or request fails
        """
        try:
            return self._get_psu_health_version(psu_id)
        except Exception as e:
            # Log the error details for debugging
            print(f"Failed to get PSU {psu_id} health and version: {str(e)}")
            return False
