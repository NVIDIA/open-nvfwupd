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
Power Shelf Device Integration Tests

This module provides integration-level testing for power shelf device operations,
focusing on complete operation flows with mocked hardware dependencies.
Tests cover PSU firmware updates, health monitoring, task management, and error scenarios.
"""

import os

# Add the parent directory to the path
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from FactoryMode.TrayFlowFunctions.power_shelf_factory_flow_functions import (
    PowerShelfFactoryFlow,
    PowerShelfFactoryFlowConfig,
)

from .integration_test_base import IntegrationTestBase, RedfishResponseBuilder

# Mark all tests in this file
pytestmark = [pytest.mark.device, pytest.mark.power_shelf]


class TestPowerShelfIntegration(IntegrationTestBase):
    """Integration tests for PowerShelfFactoryFlow operations with mocked hardware."""

    def setUp(self):
        """Set up test fixtures and mocks."""
        super().setUp()

        # Create test configuration
        self.config_file = self.create_test_config_file("power_shelf")
        self.config = PowerShelfFactoryFlowConfig(self.config_file)

        # Create flow instance
        self.flow = PowerShelfFactoryFlow(self.config, "power_shelf1")

        # Mock the BMC session
        self.mock_session = MagicMock()
        self.config.connection.bmc_session = self.mock_session

    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self.config, "close"):
            self.config.close()
        super().tearDown()

    # Test 1: PSU firmware update complete flow
    def test_psu_firmware_update_flow(self):
        """Test complete PSU firmware update process."""
        # Create test firmware file
        firmware_path = self.create_test_file("test_psu_fw.bin", b"FAKE_PSU_FIRMWARE")

        # Mock successful firmware update response
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        self.mock_session.post.return_value = mock_response

        # Execute firmware update
        result = self.flow.update_firmware(firmware_path)

        # Verify success
        self.assertTrue(result)

        # Verify firmware upload was called with correct parameters
        self.mock_session.post.assert_called_once()
        call_args = self.mock_session.post.call_args
        self.assertEqual(call_args[0][0], "https://192.168.1.300:443/redfish/v1/UpdateService/update")
        self.assertIn("UpdateFile", call_args[1]["files"])

    # Test 2: Health monitoring across all PSUs
    def test_health_monitoring_all_psus(self):
        """Test health check across multiple PSUs."""
        # Mock responses for different PSUs
        psu_responses = {
            1: {
                "FirmwareVersion": "1.2.3",
                "Status": {"Health": "OK", "State": "Enabled"},
                "Model": "PSU2000W",
                "Manufacturer": "NVIDIA",
                "SerialNumber": "SN001",
                "PartNumber": "PN001",
                "PowerCapacityWatts": 2000,
                "PowerSupplyType": "AC",
                "LineInputVoltage": 240,
                "LineInputVoltageType": "AC",
            },
            2: {
                "FirmwareVersion": "1.2.3",
                "Status": {"Health": "Warning", "State": "Enabled"},
                "Model": "PSU2000W",
                "Manufacturer": "NVIDIA",
                "SerialNumber": "SN002",
                "PartNumber": "PN001",
                "PowerCapacityWatts": 2000,
                "PowerSupplyType": "AC",
                "LineInputVoltage": 220,
                "LineInputVoltageType": "AC",
            },
        }

        def mock_get_response(url, *args, **kwargs):
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None

            if "/PowerSupplies/1" in url:
                mock_response.json.return_value = psu_responses[1]
            elif "/PowerSupplies/2" in url:
                mock_response.json.return_value = psu_responses[2]
            else:
                mock_response.json.return_value = {}

            return mock_response

        self.mock_session.get.side_effect = mock_get_response

        # Check PSU 1 health
        result1 = self.flow.check_psu_health_version(1)
        self.assertEqual(result1["health"], "OK")
        self.assertEqual(result1["version"], "1.2.3")
        self.assertEqual(result1["power_capacity_watts"], 2000)

        # Check PSU 2 health
        result2 = self.flow.check_psu_health_version(2)
        self.assertEqual(result2["health"], "Warning")
        self.assertEqual(result2["version"], "1.2.3")
        self.assertEqual(result2["line_input_voltage"], 220)

        # Verify both calls were made
        self.assertEqual(self.mock_session.get.call_count, 2)

    # Test 3: Task monitoring and completion
    def test_task_monitoring_completion(self):
        """Test Redfish task monitoring until completion."""
        task_id = "12345"

        # Mock task responses showing progression
        task_responses = [
            RedfishResponseBuilder.task_response(task_id=task_id, state="Running", percent=25),
            RedfishResponseBuilder.task_response(task_id=task_id, state="Running", percent=75),
            RedfishResponseBuilder.task_response(task_id=task_id, state="Completed", percent=100),
        ]

        call_count = 0

        def mock_get_task_response(url, *args, **kwargs):
            nonlocal call_count
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = task_responses[min(call_count, len(task_responses) - 1)]
            call_count += 1
            return mock_response

        self.mock_session.get.side_effect = mock_get_task_response

        # Execute task status checking
        result = self.flow._get_task_status(task_id)

        # Should return the first task response
        self.assertEqual(result["TaskState"], "Running")
        self.assertEqual(result["PercentComplete"], 25)

        # Get final task status
        final_result = self.flow._get_task_status(task_id)
        self.assertEqual(final_result["TaskState"], "Running")
        self.assertEqual(final_result["PercentComplete"], 75)

    # Test 4: PMC version checking
    def test_pmc_version_check(self):
        """Test Power Management Controller version verification."""
        # Mock PMC response
        pmc_response = {
            "FirmwareVersion": "2.1.0",
            "Model": "PMC_v2",
            "Manufacturer": "NVIDIA",
        }

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = pmc_response
        self.mock_session.get.return_value = mock_response

        # Execute PMC version check
        result = self.flow.check_pmc_version()

        # Verify result
        self.assertEqual(result["version"], "2.1.0")
        self.assertEqual(result["model"], "PMC_v2")
        self.assertEqual(result["manufacturer"], "NVIDIA")

        # Verify correct endpoint was called
        self.mock_session.get.assert_called_once()
        call_args = self.mock_session.get.call_args[0][0]
        self.assertIn("redfish/v1/Chassis/PowerShelf/Managers/PMC", call_args)

    # Test 5: Firmware update with error handling
    def test_firmware_update_error_scenarios(self):
        """Test firmware update error handling."""
        # Create test firmware file
        firmware_path = self.create_test_file("test_fw.bin", b"FIRMWARE")

        # Test 1: HTTP error during upload
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Server Error")
        self.mock_session.post.return_value = mock_response

        with self.assertRaises(RuntimeError) as context:
            self.flow.update_firmware(firmware_path)

        self.assertIn("Firmware update failed", str(context.exception))

        # Test 2: Connection timeout
        self.mock_session.post.side_effect = requests.exceptions.Timeout("Connection timeout")

        with self.assertRaises(RuntimeError) as context:
            self.flow.update_firmware(firmware_path)

        self.assertIn("Firmware update failed", str(context.exception))

    # Test 6: Task not found error handling
    def test_task_not_found_error(self):
        """Test task status check when task doesn't exist."""
        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = requests.exceptions.HTTPError("Not Found")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        self.mock_session.get.return_value = mock_response

        # Execute task status check
        with self.assertRaises(RuntimeError) as context:
            self.flow._get_task_status("non_existent_task")

        self.assertIn("BMC command failed", str(context.exception))

    # Test 7: PSU not found error handling
    def test_psu_not_found_error(self):
        """Test PSU health check when PSU doesn't exist."""
        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = requests.exceptions.HTTPError("Not Found")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        self.mock_session.get.return_value = mock_response

        # Execute PSU health check
        result = self.flow.check_psu_health_version(99)
        self.assertFalse(result)

    # Test 8: PMC not found error handling
    def test_pmc_not_found_error(self):
        """Test PMC version check when PMC endpoint doesn't exist."""
        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = requests.exceptions.HTTPError("Not Found")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        self.mock_session.get.return_value = mock_response

        # Execute PMC version check
        result = self.flow.check_pmc_version()
        self.assertFalse(result)

    # Test 9: Multiple PSU parallel operations simulation
    def test_parallel_psu_operations(self):
        """Test simulated parallel PSU operations."""
        # Mock responses for multiple PSUs
        psu_data = {}
        for psu_id in range(1, 5):  # PSUs 1-4
            psu_data[psu_id] = {
                "FirmwareVersion": f"1.{psu_id}.0",
                "Status": {"Health": "OK", "State": "Enabled"},
                "Model": f"PSU2000W_{psu_id}",
                "SerialNumber": f"SN00{psu_id}",
            }

        def mock_parallel_response(url, *args, **kwargs):
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None

            for psu_id, data in psu_data.items():
                if f"/PowerSupplies/{psu_id}" in url:
                    mock_response.json.return_value = data
                    return mock_response

            mock_response.json.return_value = {}
            return mock_response

        self.mock_session.get.side_effect = mock_parallel_response

        # Execute health checks for all PSUs
        results = []
        for psu_id in range(1, 5):
            result = self.flow.check_psu_health_version(psu_id)
            results.append(result)
            self.assertEqual(result["version"], f"1.{psu_id}.0")
            self.assertEqual(result["health"], "OK")

        # Verify all calls were made
        self.assertEqual(self.mock_session.get.call_count, 4)

    # Test 10: Connection management and session handling
    def test_session_management(self):
        """Test session lifecycle management."""
        # Test connection configuration
        connection = self.config.connection

        # Test BMC URL generation
        url = connection.get_bmc_url("test/endpoint")
        self.assertEqual(url, "https://192.168.1.300:443/test/endpoint")

        # Test session creation with fresh session
        connection.bmc_session = None  # Reset to test fresh creation
        session = connection.get_bmc_session()
        self.assertIsNotNone(session)
        # Note: In our mock environment, verify will be a MagicMock, not False
        # In real environment, it would be False

        # Test session reuse
        session2 = connection.get_bmc_session()
        self.assertIs(session, session2)  # Should return same session

        # Test connection cleanup
        connection.close()

    # Test 11: Comprehensive PSU status validation
    def test_comprehensive_psu_status_validation(self):
        """Test comprehensive PSU status checking with various states."""
        test_cases = [
            {
                "psu_id": 1,
                "response": {
                    "FirmwareVersion": "1.0.0",
                    "Status": {"Health": "OK", "State": "Enabled"},
                    "Model": "PSU2000W",
                    "Manufacturer": "NVIDIA",
                    "SerialNumber": "SN001",
                    "PartNumber": "PN001",
                    "PowerCapacityWatts": 2000,
                    "PowerSupplyType": "AC",
                    "LineInputVoltage": 240,
                    "LineInputVoltageType": "AC120-240",
                },
                "expected_health": "OK",
                "expected_state": "Enabled",
            },
            {
                "psu_id": 2,
                "response": {
                    "FirmwareVersion": "1.1.0",
                    "Status": {"Health": "Warning", "State": "StandbyOffline"},
                    "Model": "PSU3000W",
                    "Manufacturer": "NVIDIA",
                    "SerialNumber": "SN002",
                    "PartNumber": "PN002",
                    "PowerCapacityWatts": 3000,
                    "PowerSupplyType": "DC",
                    "LineInputVoltage": 48,
                    "LineInputVoltageType": "DC48",
                },
                "expected_health": "Warning",
                "expected_state": "StandbyOffline",
            },
        ]

        for test_case in test_cases:
            # Reset mock for each test case
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = test_case["response"]
            self.mock_session.get.return_value = mock_response

            # Execute PSU status check
            result = self.flow.check_psu_health_version(test_case["psu_id"])

            # Verify all expected fields
            self.assertEqual(result["health"], test_case["expected_health"])
            self.assertEqual(result["state"], test_case["expected_state"])
            self.assertEqual(result["version"], test_case["response"]["FirmwareVersion"])
            self.assertEqual(result["model"], test_case["response"]["Model"])
            self.assertEqual(
                result["power_capacity_watts"],
                test_case["response"]["PowerCapacityWatts"],
            )
            self.assertEqual(result["power_supply_type"], test_case["response"]["PowerSupplyType"])

    def test_post_and_get_request_exception_paths(self):
        """Cover POST/GET exception handling via _execute_bmc_command wrappers."""
        # Simulate GET raising a requests exception via session.get
        from requests import exceptions as rex

        self.mock_session.get.side_effect = rex.RequestException("bad get")
        result = self.flow.check_psu_health_version(1)
        self.assertFalse(result)
        # Simulate POST raising in update_firmware
        self.mock_session.get.side_effect = None
        # Create firmware file
        fw = self.create_test_file("fw.bin", b"FW")
        self.mock_session.post.side_effect = rex.RequestException("bad post")
        with self.assertRaises(RuntimeError):
            self.flow.update_firmware(fw)

    def test_task_error_state_and_generic_http_error(self):
        """Cover non-404 HTTP error path in get_task_status."""
        import requests

        mock_response = MagicMock()
        mock_response.status_code = 500
        http_error = requests.exceptions.HTTPError("Server Error")
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        self.mock_session.get.return_value = mock_response
        with self.assertRaises(RuntimeError) as cm:
            self.flow._get_task_status("t1")
        self.assertIn("BMC command failed", str(cm.exception))


class TestPowerShelfFlow(unittest.TestCase):
    def setUp(self):
        # Minimal config file
        self.config_path = self._write_config()
        self.config = PowerShelfFactoryFlowConfig(self.config_path)
        self.flow = PowerShelfFactoryFlow(self.config, "shelf1")
        # Patch session
        self.session = MagicMock()
        self.config.connection.get_bmc_session = MagicMock(return_value=self.session)
        self.config.connection.get_bmc_url = MagicMock(side_effect=lambda ep: f"https://bmc/{ep}")

    def tearDown(self):
        try:
            os.remove(self.config_path)
        except FileNotFoundError:
            pass

    def _write_config(self):
        import tempfile

        import yaml

        d = tempfile.mkdtemp()
        p = os.path.join(d, "ps.yaml")
        cfg = {
            "connection": {
                "power_shelf": {
                    "bmc": {
                        "ip": "1.1.1.1",
                        "username": "u",
                        "password": "p",
                        "port": 443,
                        "protocol": "https",
                    }
                }
            }
        }
        with open(p, "w") as f:
            yaml.dump(cfg, f)
        return p

    def test_execute_bmc_command_methods_and_unsupported(self):
        self.session.get.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        self.session.post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        self.session.put.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        # GET
        out = self.flow._execute_bmc_command("x", method="GET")
        self.assertTrue(out["ok"])
        # POST
        out = self.flow._execute_bmc_command("x", method="POST", data={})
        self.assertTrue(out["ok"])
        # PUT
        out = self.flow._execute_bmc_command("x", method="PUT", data={})
        self.assertTrue(out["ok"])
        # Unsupported
        with self.assertRaises(ValueError):
            self.flow._execute_bmc_command("x", method="DELETE")

    def test_execute_bmc_command_request_exception(self):
        import requests

        self.session.get.side_effect = requests.exceptions.RequestException("boom")
        with self.assertRaises(RuntimeError):
            self.flow._execute_bmc_command("x")

    def test_update_firmware_exception(self):
        # Create dummy path but patch open to raise
        with patch("builtins.open", side_effect=OSError("no file")):
            with self.assertRaises(RuntimeError):
                self.flow.update_firmware("/missing.bin")

    def test_get_task_status_404_and_other(self):
        import requests

        # Prepare a response that raises for status
        resp = MagicMock()
        resp.status_code = 404
        http_err_404 = requests.exceptions.HTTPError(response=resp)
        # Make session.get return a response that raises this error when raise_for_status called
        self.session.get.side_effect = http_err_404
        with self.assertRaises(RuntimeError):
            self.flow._get_task_status("0")
        # Other HTTP error
        resp2 = MagicMock()
        resp2.status_code = 500
        self.session.get.side_effect = requests.exceptions.HTTPError(response=resp2)
        with self.assertRaises(RuntimeError):
            self.flow._get_task_status("0")

    def test_check_pmc_version_404_and_other(self):
        import requests

        # 404 path
        resp = MagicMock()
        resp.status_code = 404
        self.session.get.side_effect = requests.exceptions.HTTPError(response=resp)
        result = self.flow.check_pmc_version()
        self.assertFalse(result)
        # other error
        resp2 = MagicMock()
        resp2.status_code = 500
        self.session.get.side_effect = requests.exceptions.HTTPError(response=resp2)
        result = self.flow.check_pmc_version()
        self.assertFalse(result)

    def test_check_psu_health_version_404_and_other(self):
        import requests

        # 404 path
        resp = MagicMock()
        resp.status_code = 404
        self.session.get.side_effect = requests.exceptions.HTTPError(response=resp)
        result = self.flow.check_psu_health_version(psu_id=0)
        self.assertFalse(result)
        # other error
        resp2 = MagicMock()
        resp2.status_code = 500
        self.session.get.side_effect = requests.exceptions.HTTPError(response=resp2)
        result = self.flow.check_psu_health_version(psu_id=0)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
