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
Base classes and utilities for device integration testing.

This module provides common functionality for testing real device flow implementations
with mocked external dependencies (Redfish, SSH, subprocess, etc.).
"""

import os
import shutil
import subprocess

# Add the parent directory to the path
import sys
import tempfile
import unittest
from typing import Dict, List, Optional, Tuple, Union
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from FactoryMode.TestFiles.test_mocks import MockUtils


class IntegrationTestBase(unittest.TestCase):
    """Base class for device integration tests with common mocking patterns."""

    def setUp(self):
        """Set up common test fixtures and mocks."""
        # Create temporary directory for test files
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.test_dir, ignore_errors=True))

        # Mock logger
        self.mock_logger = MagicMock()

        # Create MockUtils instance - this replaces the old mock_redfish_utils
        self.mock_utils = MockUtils()

        # For backward compatibility, also expose as mock_redfish_utils
        self.mock_redfish_utils = self.mock_utils

        # Mock SSH client
        self.mock_ssh_client = MagicMock()

        # Mock SCP client
        self.mock_scp_client = MagicMock()

        # Standard patches that should be applied
        self.patches = []

        # Automatically patch Utils for all device types
        self.utils_patches = {
            "compute": patch(
                "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.Utils",
                MockUtils,
            ),
            "switch": patch(
                "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.Utils",
                MockUtils,
            ),
            "common": patch(
                "FactoryMode.TrayFlowFunctions.common_factory_flow_functions.Utils",
                MockUtils,
            ),
            # Power shelf uses direct requests instead of Utils, so no patching needed
        }

        # Also patch HMCRedfishUtils to use MockUtils
        self.hmc_patches = {
            "compute": patch(
                "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.HMCRedfishUtils",
                MockUtils,
            ),
        }

        # Start all patches
        for patch_obj in self.utils_patches.values():
            patch_obj.start()
            self.patches.append(patch_obj)

        for patch_obj in self.hmc_patches.values():
            patch_obj.start()
            self.patches.append(patch_obj)

    def tearDown(self):
        """Clean up patches and resources."""
        for patcher in self.patches:
            patcher.stop()

    def create_test_config_file(self, device_type: str = "compute", custom_config: Optional[Dict] = None) -> str:
        """Create a test configuration file with standard structure.

        Args:
            device_type: Type of device config to create (compute, switch, power_shelf)
            custom_config: Optional custom configuration to merge

        Returns:
            str: Path to the created config file
        """
        base_config = {
            "connection": {
                device_type: {
                    "bmc": {
                        "ip": "192.168.1.100",
                        "username": "root",
                        "password": "test123",
                        "port": 443,
                        "protocol": "https",
                    },
                    "os": {
                        "ip": "192.168.1.101",
                        "username": "root",
                        "password": "test123",
                        "port": 22,
                    },
                    "hmc": {
                        "ip": "192.168.1.102",
                        "username": "root",
                        "password": "test123",
                        "port": 22,
                    },
                }
            },
            "settings": {
                "default_retry_count": 2,
                "default_wait_after_seconds": 1,
                "default_wait_between_retries_seconds": 2,
            },
        }

        # Add compute-specific configuration
        if device_type == "compute":
            base_config["compute"] = {
                "DOT": "NoDOT",
                "post_logging_enabled": False,
                "use_ssh_sol": False,
            }

        # For switch and power_shelf, adjust connection structure
        if device_type == "switch":
            base_config["connection"] = {
                "switch": {
                    "ip": "192.168.1.200",
                    "username": "admin",
                    "password": "test123",
                    "port": 22,
                }
            }
        elif device_type == "power_shelf":
            base_config["connection"] = {
                "power_shelf": {
                    "bmc": {
                        "ip": "192.168.1.300",
                        "username": "admin",
                        "password": "test123",
                        "port": 443,
                        "protocol": "https",
                    }
                }
            }

        # Merge custom config if provided
        if custom_config:
            self._deep_merge(base_config, custom_config)

        # Write to file
        config_file = os.path.join(self.test_dir, "test_config.yaml")
        import yaml

        with open(config_file, "w") as f:
            yaml.dump(base_config, f)

        return config_file

    def _deep_merge(self, base: Dict, update: Dict) -> Dict:
        """Deep merge two dictionaries."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    def create_mock_redfish_response(
        self,
        status_code: int = 200,
        json_data: Optional[Dict] = None,
        text: str = "",
        headers: Optional[Dict] = None,
    ) -> MagicMock:
        """Create a mock HTTP response object for Redfish operations.

        Args:
            status_code: HTTP status code
            json_data: Optional JSON response data
            text: Response text
            headers: Optional response headers

        Returns:
            MagicMock: Mock response object
        """
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = text
        mock_response.headers = headers or {}

        if json_data is not None:
            mock_response.json.return_value = json_data
        else:
            mock_response.json.side_effect = ValueError("No JSON data")

        return mock_response

    def create_mock_ssh_session(self, exec_results: Optional[List[Tuple[str, str, int]]] = None) -> MagicMock:
        """Create a mock SSH session with predefined command results.

        Args:
            exec_results: List of (stdout, stderr, exit_code) tuples for commands

        Returns:
            MagicMock: Mock SSH client
        """
        mock_ssh = MagicMock()

        if exec_results:
            # Create mock stdin/stdout/stderr for each result
            exec_returns = []
            for stdout, stderr, exit_code in exec_results:
                mock_stdin = MagicMock()
                mock_stdout = MagicMock()
                mock_stderr = MagicMock()

                mock_stdout.read.return_value = stdout.encode()
                mock_stderr.read.return_value = stderr.encode()
                mock_stdout.channel.recv_exit_status.return_value = exit_code

                exec_returns.append((mock_stdin, mock_stdout, mock_stderr))

            mock_ssh.exec_command.side_effect = exec_returns

        return mock_ssh

    def create_mock_subprocess_result(
        self, returncode: int = 0, stdout: str = "", stderr: str = ""
    ) -> subprocess.CompletedProcess:
        """Create a mock subprocess result.

        Args:
            returncode: Process return code
            stdout: Standard output
            stderr: Standard error

        Returns:
            subprocess.CompletedProcess: Mock process result
        """
        return subprocess.CompletedProcess(args=["mock_command"], returncode=returncode, stdout=stdout, stderr=stderr)

    def create_test_file(self, filename: str, content: Union[str, bytes] = b"TEST_DATA") -> str:
        """Create a test file in the temporary directory.

        Args:
            filename: Name of the file to create
            content: File content (string or bytes)

        Returns:
            str: Full path to the created file
        """
        file_path = os.path.join(self.test_dir, filename)

        if isinstance(content, str):
            with open(file_path, "w") as f:
                f.write(content)
        else:
            with open(file_path, "wb") as f:
                f.write(content)

        return file_path

    def assert_logger_has_error(self, error_substring: str):
        """Assert that an error was logged containing the substring."""
        for call in self.mock_logger.error.call_args_list:
            if error_substring in str(call):
                return
        self.fail(f"Expected error log containing '{error_substring}' not found")

    def assert_logger_has_warning(self, warning_substring: str):
        """Assert that a warning was logged containing the substring."""
        for call in self.mock_logger.warning.call_args_list:
            if warning_substring in str(call):
                return
        self.fail(f"Expected warning log containing '{warning_substring}' not found")

    def assert_logger_has_info(self, info_substring: str):
        """Assert that an info message was logged containing the substring."""
        for call in self.mock_logger.info.call_args_list:
            if info_substring in str(call):
                return
        self.fail(f"Expected info log containing '{info_substring}' not found")


class RedfishResponseBuilder:
    """Builder class for creating complex Redfish responses."""

    @staticmethod
    def task_response(
        task_id: str = "0",
        state: str = "Running",
        percent: int = 0,
        messages: Optional[List[Dict]] = None,
    ) -> Dict:
        """Build a Redfish task response.

        Args:
            task_id: Task identifier
            state: Task state (Running, Completed, Exception, etc.)
            percent: Percent complete
            messages: Optional list of message dicts

        Returns:
            Dict: Task response structure
        """
        response = {
            "@odata.id": f"/redfish/v1/TaskService/Tasks/{task_id}",
            "@odata.type": "#Task.v1_4_3.Task",
            "Id": task_id,
            "TaskState": state,
            "TaskStatus": "OK" if state != "Exception" else "Critical",
            "PercentComplete": percent,
        }

        if messages:
            response["Messages"] = messages

        return response

    @staticmethod
    def firmware_inventory_response(members: List[str]) -> Dict:
        """Build a firmware inventory collection response.

        Args:
            members: List of firmware component names

        Returns:
            Dict: Firmware inventory collection
        """
        return {
            "@odata.id": "/redfish/v1/UpdateService/FirmwareInventory",
            "@odata.type": "#SoftwareInventoryCollection.SoftwareInventoryCollection",
            "Members": [{"@odata.id": f"/redfish/v1/UpdateService/FirmwareInventory/{name}"} for name in members],
        }

    @staticmethod
    def firmware_component_response(name: str, version: str) -> Dict:
        """Build a firmware component response.

        Args:
            name: Component name
            version: Firmware version

        Returns:
            Dict: Firmware component details
        """
        return {
            "@odata.id": f"/redfish/v1/UpdateService/FirmwareInventory/{name}",
            "@odata.type": "#SoftwareInventory.v1_2_3.SoftwareInventory",
            "Id": name,
            "Name": name,
            "Version": version,
            "Status": {"State": "Enabled", "Health": "OK"},
        }

    @staticmethod
    def power_state_response(state: str = "On") -> Dict:
        """Build a system power state response.

        Args:
            state: Power state (On, Off, etc.)

        Returns:
            Dict: Power state response
        """
        return {
            "@odata.id": "/redfish/v1/Systems/System_0",
            "@odata.type": "#ComputerSystem.v1_13_0.ComputerSystem",
            "PowerState": state,
            "Status": {"State": "Enabled", "Health": "OK"},
        }


class MockTaskMonitor:
    """Mock task monitor that simulates progressive task completion."""

    def __init__(self, final_state: str = "Completed", steps: Optional[List[int]] = None):
        """Initialize task monitor.

        Args:
            final_state: Final task state
            steps: List of progress percentages (default: [0, 25, 50, 75, 100])
        """
        self.final_state = final_state
        self.steps = steps or [0, 25, 50, 75, 100]
        self.current_step = 0

    def get_next_response(self) -> Tuple[bool, Dict]:
        """Get the next task response in the progression.

        Returns:
            Tuple[bool, Dict]: (success, response_dict)
        """
        if self.current_step < len(self.steps):
            percent = self.steps[self.current_step]
            state = "Running" if percent < 100 else self.final_state

            response = RedfishResponseBuilder.task_response(
                task_id="0",
                state=state,
                percent=percent,
                messages=[{"Message": f"Progress: {percent}%"}],
            )

            self.current_step += 1
            return (True, response)

        # Return final state
        return (
            True,
            RedfishResponseBuilder.task_response(
                task_id="0",
                state=self.final_state,
                percent=100,
                messages=[{"Message": "Task completed"}],
            ),
        )
