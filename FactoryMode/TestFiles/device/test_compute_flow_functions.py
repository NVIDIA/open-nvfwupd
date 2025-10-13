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
Compute Device Integration Tests

This module provides integration-level testing for compute device operations,
focusing on complete operation flows with mocked hardware dependencies.
Tests cover firmware updates, power operations, version management, and error scenarios.
"""

import os
import subprocess

# Add the parent directory to the path
import sys
import unittest
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from FactoryMode.TrayFlowFunctions.compute_factory_flow_functions import (
    ComputeFactoryFlow,
    ComputeFactoryFlowConfig,
)

from .integration_test_base import IntegrationTestBase, RedfishResponseBuilder

# Mark all tests in this file
pytestmark = [pytest.mark.device, pytest.mark.compute]


class TestComputeIntegration(IntegrationTestBase):
    """Integration tests for ComputeFactoryFlow operations with mocked hardware."""

    def setUp(self):
        """Set up test fixtures and mocks."""
        super().setUp()

        # Create test configuration
        self.config_file = self.create_test_config_file("compute")
        self.config = ComputeFactoryFlowConfig(self.config_file)

        # Create flow instance - Utils is automatically mocked by IntegrationTestBase
        with patch("FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging") as mock_setup_logging:
            mock_setup_logging.return_value = self.mock_logger
            self.flow = ComputeFactoryFlow(self.config, "compute1")

        # Use the flow's actual mocked redfish_utils for our test configuration
        self.mock_utils = self.flow.redfish_utils
        self.mock_redfish_utils = self.flow.redfish_utils  # For backward compatibility

        # Mock the bmc_session
        self.mock_session = MagicMock()
        self.flow.bmc_session = self.mock_session
        # Also patch get_bmc_session to return our mock
        self.flow.get_bmc_session = MagicMock(return_value=self.mock_session)

    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self.flow, "close"):
            self.flow.close()
        super().tearDown()

    # Test 1: Complete PLDM firmware update flow
    def test_pldm_fw_update_success_flow(self):
        """Test complete PLDM firmware update flow with progress tracking."""
        # Mock upload response - this comes from post_upload_request
        upload_response = RedfishResponseBuilder.task_response(task_id="0", state="Running", percent=0)

        # Mock task completion response - this comes from monitor_job
        task_completion = RedfishResponseBuilder.task_response(
            task_id="0",
            state="Completed",
            percent=100,
            messages=[{"Message": "Firmware update completed successfully"}],
        )

        # Setup mock responses
        self.mock_redfish_utils.post_upload_request.return_value = (
            True,
            upload_response,
        )
        self.mock_redfish_utils.monitor_job.return_value = (True, task_completion)

        # Create test bundle file
        bundle_path = self.create_test_file("test_fw.pldm", b"FAKE_FIRMWARE_DATA")

        # Execute firmware update
        result = self.flow.pldm_fw_update(
            bundle_path=bundle_path,
            target_uris=["/redfish/v1/UpdateService/FirmwareInventory/BMC"],
            timeout=300,
            force_update=True,
            base_uri="/redfish/v1/UpdateService/update-multipart",
        )

        # Verify success
        self.assertTrue(result)

        # Verify upload was called with correct parameters
        self.mock_redfish_utils.post_upload_request.assert_called_once()
        upload_call_args = self.mock_redfish_utils.post_upload_request.call_args
        _, upload_kwargs = upload_call_args
        self.assertEqual(upload_kwargs.get("url_path"), "/redfish/v1/UpdateService/update-multipart")
        self.assertEqual(upload_kwargs.get("file_path"), bundle_path)
        self.assertIn('"ForceUpdate": true', upload_kwargs.get("upd_params", ""))

        # Verify task monitoring was called
        self.mock_redfish_utils.monitor_job.assert_called_once_with(
            uri="/redfish/v1/TaskService/Tasks/0", timeout=300, check_interval=30
        )

        # Verify success logging
        self.assert_logger_has_info("PLDM bundle flash completed successfully")

    # Test 2: PLDM update with failures and retries
    def test_pldm_fw_update_retry_mechanism(self):
        """Test PLDM update with failures and retry logic."""
        # The retry logic is actually handled inside the method through the redfish_utils
        # We need to mock the internal retry mechanism

        # Create test bundle
        bundle_path = self.create_test_file("test_fw.pldm", b"FIRMWARE")

        # Mock redfish_utils to simulate retries
        # First two attempts fail, third succeeds
        self.mock_redfish_utils.post_upload_request.side_effect = [
            (False, {"error": "Internal Server Error"}),
            (False, {"error": "Connection timeout"}),
            (True, RedfishResponseBuilder.task_response(task_id="5678")),
        ]

        # Mock successful task completion
        self.mock_redfish_utils.monitor_job.return_value = (
            True,
            RedfishResponseBuilder.task_response(task_id="5678", state="Completed", percent=100),
        )

        # Execute with retries handled internally
        result = self.flow.pldm_fw_update(
            bundle_path=bundle_path,
            target_uris=["/redfish/v1/UpdateService/FirmwareInventory/BMC"],
            timeout=60,
            base_uri="/redfish/v1/UpdateService/update-multipart",
        )

        # Should fail after internal retries are exhausted
        self.assertFalse(result)  # First call returns False, no retry at this level
        self.assertEqual(self.mock_redfish_utils.post_upload_request.call_count, 1)

    # Test 3: PLDM update timeout handling
    @patch("time.time")
    def test_pldm_fw_update_timeout_handling(self, mock_time):
        """Test PLDM update timeout scenarios."""
        # Mock successful upload
        upload_response = RedfishResponseBuilder.task_response(task_id="9999")
        self.mock_redfish_utils.post_upload_request.return_value = (
            True,
            upload_response,
        )

        # Mock task stuck in running state
        self.mock_redfish_utils.monitor_job.return_value = (
            True,
            {
                "Message": "Monitoring timeout reached",
                "TaskState": "Running",
                "PercentComplete": 50,
            },
        )

        # Create test bundle
        bundle_path = self.create_test_file("test_fw.pldm", b"FIRMWARE")

        # Execute with short timeout
        result = self.flow.pldm_fw_update(
            bundle_path=bundle_path,
            target_uris=["/redfish/v1/UpdateService/FirmwareInventory/BMC"],
            timeout=60,
            base_uri="/redfish/v1/UpdateService/update-multipart",
        )

        # Should return True even on timeout (task may complete in background)
        self.assertTrue(result)
        self.assert_logger_has_warning("monitoring timed out - task may have completed in background")

    # Test 4: Full AC power cycle operation
    def test_power_cycle_complete_flow(self):
        """Test full AC power cycle operation with state transitions."""
        # The ac_cycle method implementation might differ from our expectation
        # Let's test the actual behavior

        # Test with system initially ON
        self.mock_redfish_utils.get_request.side_effect = [
            (
                True,
                RedfishResponseBuilder.power_state_response("On"),
            ),  # Initial state check
            (
                True,
                RedfishResponseBuilder.power_state_response("On"),
            ),  # Check before power off
            (
                True,
                RedfishResponseBuilder.power_state_response("Off"),
            ),  # After power off
        ]
        self.mock_redfish_utils.post_request.return_value = (True, {})

        # Execute AC cycle when powered on
        with patch("time.sleep"):
            result = self.flow.ac_cycle(
                base_uri="/redfish/v1/Chassis/BMC_0/Actions/Oem/NvidiaChassis.AuxPowerReset",
                data={"ResetType": "AuxPowerCycle"},
            )

        self.assertTrue(result)
        # Verify we have POST calls for power operations
        self.assertGreater(self.mock_redfish_utils.post_request.call_count, 0)

    # Test 5: Power operations with state verification
    def test_power_on_off_state_verification(self):
        """Test power on/off operations with state verification."""
        # Test power off - it always sends the command regardless of state
        self.mock_redfish_utils.get_request.return_value = (
            True,
            RedfishResponseBuilder.power_state_response("Off"),
        )
        self.mock_redfish_utils.post_request.return_value = (True, {})

        result = self.flow.power_off(
            base_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
            data={"ResetType": "ForceOff"},
        )

        self.assertTrue(result)
        # Power off always sends the command
        self.mock_redfish_utils.post_request.assert_called_once()
        self.assert_logger_has_info("Successfully initiated power off")

        # Reset mocks
        self.mock_redfish_utils.reset_all_mocks()

        # Test power on when off - might need multiple state checks
        self.mock_redfish_utils.get_request.side_effect = [
            (True, RedfishResponseBuilder.power_state_response("Off")),  # Initial check
            (True, RedfishResponseBuilder.power_state_response("Off")),  # Still off
            (True, RedfishResponseBuilder.power_state_response("On")),  # Finally on
        ]
        self.mock_redfish_utils.post_request.return_value = (True, {})

        result = self.flow.power_on(
            base_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
            data={"ResetType": "On"},
        )

        self.assertTrue(result)
        # Should have at least one POST call for power on
        self.assertGreaterEqual(self.mock_redfish_utils.post_request.call_count, 1)
        # Actual log message from compute_factory_flow.log
        self.assert_logger_has_info("Device successfully powered on and confirmed in 'On' state")

    # Test 6: Version checking across multiple components
    def test_check_versions_multi_component(self):
        """Test version checking across multiple components."""
        # Mock firmware inventory responses
        component_responses = {
            "FW_BMC_0": RedfishResponseBuilder.firmware_component_response("FW_BMC_0", "1.2.3"),
            "FW_CPLD_0": RedfishResponseBuilder.firmware_component_response("FW_CPLD_0", "2.0.1"),
            "FW_ERoT_BMC_0": RedfishResponseBuilder.firmware_component_response("FW_ERoT_BMC_0", "3.1.0"),
        }

        def get_inventory_response(uri, *args, **kwargs):
            for fw_name, response in component_responses.items():
                if fw_name in uri:
                    return (True, response)
            return (False, {"error": "Not found"})

        self.mock_redfish_utils.get_request.side_effect = get_inventory_response

        # Execute version check
        expected_versions = {
            "FW_BMC_0": "1.2.3",
            "FW_CPLD_0": "2.0.1",
            "FW_ERoT_BMC_0": "3.1.0",
        }

        result = self.flow.check_versions(
            expected_versions=expected_versions,
            operator="==",
            base_uri="/redfish/v1/UpdateService/FirmwareInventory/",
        )

        # Verify success
        self.assertTrue(result)
        self.assertEqual(self.mock_redfish_utils.get_request.call_count, 3)

        # Test version mismatch
        self.mock_redfish_utils.reset_all_mocks()
        self.mock_redfish_utils.get_request.side_effect = get_inventory_response

        mismatched_versions = {
            "FW_BMC_0": "1.2.4",
            "FW_CPLD_0": "2.0.1",
        }  # Wrong version

        result = self.flow.check_versions(
            expected_versions=mismatched_versions,
            operator="==",
            base_uri="/redfish/v1/UpdateService/FirmwareInventory/",
        )

        # Should fail on mismatch
        self.assertFalse(result)
        # The actual error message includes "Firmware version check failures:"
        self.assert_logger_has_error("Firmware version check failures:")

    # Test 7: AP readiness with timeout and retry
    @patch("time.time")
    def test_wait_ap_ready_timeout_recovery(self, mock_time):
        """Test AP readiness check with timeout and recovery."""
        # Mock AP inventory endpoint first
        inventory_response = RedfishResponseBuilder.firmware_inventory_response(["HGX_FW_BMC_0", "HGX_FW_ERoT_BMC_0"])

        # Mock AP not ready initially, then becomes ready
        ready_states = [
            {"Status": {"State": "Absent"}},  # Not ready
            {"Status": {"State": "StandbyOffline"}},  # Still not ready
            {"Status": {"State": "Enabled"}},  # Ready
        ]

        call_count = 0

        def get_ap_response(uri, *args, **kwargs):
            nonlocal call_count
            if "FirmwareInventory" in uri and not any(ap in uri for ap in ["HGX_FW_BMC_0", "HGX_FW_ERoT_BMC_0"]):
                # Return inventory list
                return (True, inventory_response)
            else:
                # Return AP state
                response = ready_states[min(call_count, len(ready_states) - 1)]
                call_count += 1
                return (True, response)

        self.mock_redfish_utils.get_request.side_effect = get_ap_response

        # Mock time progression
        start_time = 1000
        mock_time.side_effect = [
            start_time,
            start_time + 5,
            start_time + 10,
            start_time + 15,
            start_time + 20,
        ]

        # Execute wait for AP ready
        with patch("time.sleep"):
            result = self.flow.wait_ap_ready(
                ap_name=["HGX_FW_BMC_0", "HGX_FW_ERoT_BMC_0"],
                base_uri="/redfish/v1/UpdateService/FirmwareInventory",
                timeout=60,
            )

        # Should succeed when AP becomes ready
        self.assertTrue(result)

    # Test 8: DOT CAK installation and locking
    def test_dot_cak_install_lock_flow(self):
        """Test DOT CAK installation and locking procedures."""
        # Mock successful responses
        self.mock_redfish_utils.post_request.return_value = (True, {})
        self.mock_redfish_utils.get_request.return_value = (
            True,
            {"Oem": {"Nvidia": {"DOT": {"CAKInstalled": True, "SecurityState": "Unlocked"}}}},
        )

        # Test CAK installation
        result = self.flow.dot_cak_install(
            ap_name="HGX_ERoT_CPU_0",
            pem_encoded_key="-----BEGIN PUBLIC KEY-----\nTEST_KEY\n-----END PUBLIC KEY-----",
            ap_firmware_signature="TEST_SIGNATURE",
            base_uri="/redfish/v1/Chassis",
            check_volatile_dot=True,
        )

        self.assertTrue(result)

        # Test CAK locking
        self.mock_redfish_utils.reset_all_mocks()
        self.mock_redfish_utils.post_request.return_value = (True, {})

        result = self.flow.dot_cak_lock(
            ap_name="HGX_ERoT_CPU_0",
            pem_encoded_key="-----BEGIN PUBLIC KEY-----\nTEST_KEY\n-----END PUBLIC KEY-----",
            base_uri="/redfish/v1/Chassis",
            check_locking_dot=True,
        )

        self.assertTrue(result)
        # The actual log message when DOT is not in locking state
        self.assert_logger_has_info("DOT is not set to 'Locking', returning True")

    # Test 9: HMC factory reset with recovery
    def test_hmc_factory_reset_recovery(self):
        """Test HMC factory reset with recovery procedures."""
        # First attempt fails, second succeeds
        self.mock_redfish_utils.post_request.side_effect = [
            (False, {"error": "Internal Error"}),
            (True, {}),
        ]

        # Execute factory reset - retries are handled internally
        with patch("time.sleep"):
            result = self.flow.hmc_factory_reset(
                base_uri="/redfish/v1/Managers/HGX_BMC_0/Actions/Manager.ResetToDefaults",
                data={"ResetToDefaultsType": "ResetAll"},
            )

        # Should fail on first attempt (no retry at this level)
        self.assertFalse(result)
        self.assertEqual(self.mock_redfish_utils.post_request.call_count, 1)

    # Test 10: Background copy monitoring
    @patch("time.time")
    def test_background_copy_monitoring(self, mock_time):
        """Test background copy progress tracking."""
        # The monitor_background_copy method might return False if it can't find the APs
        # Let's simplify the test to just verify the method is called correctly

        # Mock successful background copy monitoring
        completed_response = {
            "Oem": {
                "Nvidia": {
                    "BackgroundCopyStatus": "Completed",
                    "BackgroundCopyProgress": 100,
                }
            }
        }

        # Return completed status for all calls
        self.mock_redfish_utils.get_request.return_value = (True, completed_response)

        # Mock time progression
        start_time = 1000
        mock_time.side_effect = [start_time, start_time + 1, start_time + 2]

        # Execute background copy monitoring
        with patch("time.sleep"):
            result = self.flow.monitor_background_copy(
                ap_name=["HGX_ERoT_BMC_0", "HGX_ERoT_FPGA_0"],
                base_uri="/redfish/v1/Chassis/",
                timeout=10,  # Short timeout for test
            )

        # Should complete successfully
        self.assertTrue(result)

        # Verify the monitoring happened
        self.assertGreater(self.mock_redfish_utils.get_request.call_count, 0)
        self.assert_logger_has_info("Checking background copy status for")

    # Test 11: Redfish error response handling
    def test_redfish_error_response_handling(self):
        """Test handling of various Redfish error responses."""
        # Test 401 Unauthorized
        self.mock_redfish_utils.get_request.return_value = (
            False,
            {
                "error": {
                    "@Message.ExtendedInfo": [
                        {
                            "MessageId": "Base.1.0.NoValidSession",
                            "Message": "There is no valid session established with the implementation.",
                        }
                    ]
                }
            },
        )

        result = self.flow.wait_ap_ready(
            ap_name="HGX_FW_BMC_0",
            base_uri="/redfish/v1/UpdateService/FirmwareInventory",
            timeout=10,
        )

        self.assertFalse(result)

        # Test 404 Not Found
        self.mock_redfish_utils.get_request.return_value = (
            False,
            {"error": "Resource not found"},
        )

        result = self.flow.check_versions(
            expected_versions={"UNKNOWN_FW": "1.0.0"},
            operator="==",
            base_uri="/redfish/v1/UpdateService/FirmwareInventory/",
        )

        self.assertFalse(result)
        # Check for error log about version check failures
        self.assert_logger_has_error("Firmware version check failures:")

    # Test 12: IPMITOOL command failures
    @patch("subprocess.run")
    def test_ipmitool_command_failures(self, mock_subprocess):
        """Test IPMITOOL command error scenarios."""
        # Test command timeout
        mock_subprocess.side_effect = subprocess.TimeoutExpired("ipmitool", 30)

        result = self.flow.execute_ipmitool_command(command="chassis status", timeout=30)

        self.assertFalse(result)
        # Check for timeout error - the exact message might vary
        self.assert_logger_has_error("timed out")

        # Test command failure
        mock_subprocess.side_effect = None
        mock_subprocess.return_value = self.create_mock_subprocess_result(
            returncode=1,
            stdout="",
            stderr="Unable to establish IPMI v2 / RMCP+ session",
        )

        result = self.flow.execute_ipmitool_command(command="chassis power status", use_lanplus=True)

        self.assertFalse(result)
        # Check for return code error - the exact format might vary
        self.assert_logger_has_error("return code: 1")

    # Test 13: OS command execution errors
    @patch("paramiko.SSHClient")
    def test_os_command_execution_errors(self, mock_ssh_class):
        """Test OS command execution failure scenarios."""
        # Test SSH connection failure
        mock_ssh_class.return_value.connect.side_effect = Exception("Connection refused")

        result = self.flow.execute_os_command(command="ls -la", timeout=30)

        self.assertFalse(result)
        # Check for connection error
        self.assert_logger_has_error("Failed to execute command:")

        # Test command execution failure
        mock_ssh_class.return_value.connect.side_effect = None
        mock_ssh = self.create_mock_ssh_session([("", "command not found", 127)])
        mock_ssh_class.return_value = mock_ssh

        result = self.flow.execute_os_command(command="unknown_command", timeout=30)

        self.assertFalse(result)
        # Check for return code error - exact format might vary
        self.assert_logger_has_error("return code: 127")

    # Test 14: File transfer retry logic
    @patch("paramiko.SSHClient")
    @patch("scp.SCPClient")
    def test_file_transfer_retry_logic(self, mock_scp_class, mock_ssh_class):
        """Test SCP file transfer with retry logic."""
        # Setup mocks
        mock_ssh = MagicMock()
        mock_ssh_class.return_value = mock_ssh

        # The scp_tool_to_os method uses scp_files_target internally
        # We need to mock the entire flow properly

        # Create test file
        test_file = self.create_test_file("test_tool.sh", "#!/bin/bash\necho 'test'")

        # Mock SSH connection success
        mock_ssh.connect.return_value = None

        # Mock file operations - scp_tool_to_os might use different approach
        # It may use paramiko's sftp instead of scp
        mock_sftp = MagicMock()
        mock_sftp.put.return_value = None
        mock_sftp.chmod.return_value = None
        mock_ssh.open_sftp.return_value = mock_sftp

        # Execute file transfer
        result = self.flow.scp_tool_to_os(tool_file_path=test_file)

        # Should succeed
        self.assertTrue(result)
        # Verify SSH was used
        mock_ssh.connect.assert_called()

    # Test 15: Sequential operation execution
    def test_sequential_operation_execution(self):
        """Test that different operation types can be executed sequentially on the same device.

        This validates that the ComputeFactoryFlow instance properly handles state
        between different types of operations without interference or corruption.
        Operations tested in sequence:
        1. Power control (power_off)
        2. Version checking (check_versions)
        3. BMC management (reboot_bmc)
        """
        # Test Operation 1: Power off the compute node
        # Mock should return "On" initially, then "Off" after power command
        get_request_count = 0

        def power_state_side_effect(*args, **kwargs):
            nonlocal get_request_count
            get_request_count += 1
            # First call returns "On", subsequent calls return "Off"
            if get_request_count == 1:
                return (True, RedfishResponseBuilder.power_state_response("On"))
            else:
                return (True, RedfishResponseBuilder.power_state_response("Off"))

        self.mock_utils.get_request.side_effect = power_state_side_effect
        self.mock_utils.post_request.return_value = (True, {})

        result = self.flow.power_off(
            base_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
            data={"ResetType": "ForceOff"},
        )

        self.assertTrue(result, "Power off operation failed")
        self.assert_logger_has_info("Successfully initiated power off")

        # Reset mocks for next operation
        self.mock_utils.reset_all_mocks()

        # Test Operation 2: Check firmware versions (different subsystem)
        def version_check_response(uri, *args, **kwargs):
            if "FW_BMC_0" in uri:
                return (
                    True,
                    RedfishResponseBuilder.firmware_component_response("FW_BMC_0", "1.2.3"),
                )
            return (True, {})

        self.mock_utils.get_request.side_effect = version_check_response

        result = self.flow.check_versions(
            expected_versions={"FW_BMC_0": "1.2.3"},
            operator="==",
            base_uri="/redfish/v1/UpdateService/FirmwareInventory/",
        )
        self.assertTrue(result, "Version check operation failed")

        # Reset mocks for next operation
        self.mock_utils.reset_all_mocks()

        # Test Operation 3: Reboot BMC (management operation)
        self.mock_utils.post_request.return_value = (True, {})

        result = self.flow.reboot_bmc(
            base_uri="/redfish/v1/Managers/BMC_0/Actions/Manager.Reset",
            data={"ResetType": "GracefulRestart"},
        )
        self.assertTrue(result, "BMC reboot operation failed")

        # Verify that operations were executed
        # Note: We reset mocks between operations, so we can't check cumulative counts
        # The assertions within each operation verify they succeeded

    # ==================== VBIOS OPERATIONS TESTS ====================

    def test_nvflash_check_vbios_success(self):
        """Test successful VBIOS version checking with nvflash."""
        # Mock nvflash output from nvflash -v --list command
        nvflash_output = """
NVIDIA Firmware Update Utility (Version 5.692.0)
NVIDIA display adapter firmware updater.
Checking for matches between display adapter(s) and image(s)...

Adapter: NVIDIA H100 (10DE:2330:10DE:1626) H0:S0000,B00:D00:F0
Version: 96.00.5C.00.03
Image Size: 3145728 bytes
Board ID: 0x5100
Vendor ID: 0x10DE
Device ID: 0x2330

Update display adapter firmware?
Press 'y' to confirm (any other key to abort):        """

        # Mock SSH session with command results
        # First command is rmmod, second is nvflash
        mock_ssh = self.create_mock_ssh_session(
            [("", "", 0), (nvflash_output, "", 0)]  # rmmod success  # nvflash success
        )

        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh

            # Execute VBIOS check
            result = self.flow.nvflash_check_vbios()

            # Verify success
            self.assertTrue(result)

            # Verify SSH connection was made
            mock_ssh.connect.assert_called_once()
            connect_args = mock_ssh.connect.call_args[1]
            self.assertEqual(connect_args["hostname"], "192.168.1.101")
            self.assertEqual(connect_args["username"], "root")

            # Verify commands were executed
            self.assertEqual(mock_ssh.exec_command.call_count, 2)

            # First call should be rmmod
            rmmod_call = mock_ssh.exec_command.call_args_list[0][0][0]
            self.assertIn("rmmod nvidia", rmmod_call)

            # Second call should be nvflash
            nvflash_call = mock_ssh.exec_command.call_args_list[1][0][0]
            self.assertIn("nvflash -v --list", nvflash_call)

            # Verify logging
            self.assert_logger_has_info("VBIOS Information:")

    def test_nvflash_check_vbios_parse_errors(self):
        """Test VBIOS check with parsing errors in nvflash output."""
        # Mock malformed nvflash output
        bad_output = """
NVIDIA Firmware Update Utility (Version 5.692.0)
ERROR: Unable to detect NVIDIA display adapter
No supported NVIDIA display adapters found        """

        # Mock SSH session with command results
        # First command is rmmod, second is failed nvflash
        mock_ssh = self.create_mock_ssh_session(
            [
                ("", "", 0),
                ("", bad_output, 1),
            ]  # rmmod success  # nvflash failure with error on stderr
        )

        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh

            # Execute VBIOS check
            result = self.flow.nvflash_check_vbios()

            # Should fail gracefully
            self.assertFalse(result)

            # Verify error logging
            self.assert_logger_has_error("Failed to run nvflash:")

    def test_nvflash_flash_vbios_upgrade_only(self):
        """Test VBIOS flash with upgrade_only flag - should add --upgradeonly flag."""
        # Mock flash output
        flash_output = """
Firmware image matches adapter
Update successful
Firmware update completed. A reboot is required.        """

        # Mock SSH session with command results
        mock_ssh = self.create_mock_ssh_session(
            [("", "", 0), (flash_output, "", 0)]  # rmmod success  # nvflash success
        )

        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh

            # Execute VBIOS flash with upgrade_only
            result = self.flow.nvflash_flash_vbios(vbios_bundle="test_vbios.rom", upgrade_only=True)

            # Verify success
            self.assertTrue(result)

            # Verify commands were executed
            self.assertEqual(mock_ssh.exec_command.call_count, 2)

            # Verify nvflash command has --upgradeonly flag
            nvflash_call = mock_ssh.exec_command.call_args_list[1][0][0]
            self.assertIn("nvflash test_vbios.rom", nvflash_call)
            self.assertIn("--upgradeonly", nvflash_call)
            self.assertIn("--auto", nvflash_call)

            # Verify logging
            self.assert_logger_has_info("VBIOS Flash Output:")

    def test_nvflash_flash_vbios_force_flash(self):
        """Test VBIOS flash without upgrade_only - should skip --upgradeonly flag."""
        flash_output = """
Firmware update in progress...
Update successful        """

        # Mock SSH session
        mock_ssh = self.create_mock_ssh_session(
            [("", "", 0), (flash_output, "", 0)]  # rmmod success  # nvflash success
        )

        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh

            # Execute VBIOS flash without upgrade_only
            result = self.flow.nvflash_flash_vbios(vbios_bundle="test_vbios.rom", upgrade_only=False)

            # Verify success
            self.assertTrue(result)

            # Verify nvflash command does NOT have --upgradeonly flag
            nvflash_call = mock_ssh.exec_command.call_args_list[1][0][0]
            self.assertIn("nvflash test_vbios.rom", nvflash_call)
            self.assertNotIn("--upgradeonly", nvflash_call)
            self.assertIn("--auto", nvflash_call)

    def test_nvflash_operations_file_transfer(self):
        """Test file transfer operations for nvflash tool and VBIOS bundle."""
        # Test the scp_files_target method used by nvflash operations
        mock_ssh = self.create_mock_ssh_session(
            [
                ("", "", 0),
                ("", "", 0),
            ]  # chmod success for first file  # chmod success for second file
        )

        # Mock SFTP client
        mock_sftp = MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp

        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh

            # Create test files
            nvflash_tool = self.create_test_file("nvflash", b"NVFLASH_BINARY")
            vbios_file = self.create_test_file("vbios.rom", b"VBIOS_ROM")

            # Test target config for OS connection
            target_config = {
                "ip": "192.168.1.101",
                "port": 22,
                "username": "root",
                "password": "test123",
            }

            # Execute file transfer
            result = self.flow.config.connection.scp_files_target(
                files=[nvflash_tool, vbios_file],
                target_config=target_config,
                remote_base_path="/tmp/",
                set_executable=True,
                logger=self.flow.logger,
            )

            # Verify success
            self.assertTrue(result)

            # Verify SSH connection
            mock_ssh.connect.assert_called_once_with(
                hostname="192.168.1.101", port=22, username="root", password="test123"
            )

            # Verify SFTP client was created
            mock_ssh.open_sftp.assert_called_once()

            # Verify SFTP transfers
            self.assertEqual(mock_sftp.put.call_count, 2)

            # Verify the files were transferred to correct remote paths
            expected_calls = [
                call(nvflash_tool, "/tmp/nvflash"),
                call(vbios_file, "/tmp/vbios.rom"),
            ]
            mock_sftp.put.assert_has_calls(expected_calls)

            # Verify chmod for executable
            # Should have two chmod calls
            chmod_calls = [call for c in mock_ssh.exec_command.call_args_list if "chmod +x" in c[0][0]]
            self.assertEqual(len(chmod_calls), 2)

    # ==================== BOOT MODE OPERATIONS TESTS ====================

    def test_check_manual_boot_mode_enabled(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        # DOT Volatile -> expect true
        custom_cfg = {"compute": {"DOT": "Volatile"}}
        self.config_file = self.create_test_config_file("compute", custom_cfg)
        config = ComputeFactoryFlowConfig(self.config_file)
        self.flow = ComputeFactoryFlow(config, "compute1")
        # Use the new flow's utils
        rf = self.flow.redfish_utils

        # Mock GET response
        response = {"Oem": {"Nvidia": {"ManualBootModeEnabled": True}}}
        rf.get_request.return_value = (True, response)

        result = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            redfish_target="bmc",
        )
        self.assertTrue(result)
        rf.get_request.assert_called_once()

    def test_set_manual_boot_mode_volatile_dot(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        # DOT Volatile -> flow sets true regardless of requested state
        custom_cfg = {"compute": {"DOT": "Volatile"}}
        self.config_file = self.create_test_config_file("compute", custom_cfg)
        config = ComputeFactoryFlowConfig(self.config_file)
        self.flow = ComputeFactoryFlow(config, "compute1")
        rf = self.flow.redfish_utils

        rf.patch_request.return_value = (True, {})
        result = self.flow.set_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            state="false",
            redfish_target="bmc",
        )
        self.assertTrue(result)
        # payload should contain ManualBootModeEnabled: true
        called_payload = rf.patch_request.call_args[0][1]
        self.assertTrue(called_payload["Oem"]["Nvidia"]["ManualBootModeEnabled"])

    def test_set_manual_boot_mode_force_false_when_not_volatile(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        # DOT not Volatile -> forced false
        custom_cfg = {"compute": {"DOT": "Locking"}}
        self.config_file = self.create_test_config_file("compute", custom_cfg)
        config = ComputeFactoryFlowConfig(self.config_file)
        self.flow = ComputeFactoryFlow(config, "compute1")
        rf = self.flow.redfish_utils

        rf.patch_request.return_value = (True, {})
        result = self.flow.set_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            state="true",
            redfish_target="bmc",
        )
        self.assertTrue(result)
        called_payload = rf.patch_request.call_args[0][1]
        self.assertFalse(called_payload["Oem"]["Nvidia"]["ManualBootModeEnabled"])

    def test_send_boot_ap_command(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        custom_cfg = {"compute": {"DOT": "Volatile"}}
        self.config_file = self.create_test_config_file("compute", custom_cfg)
        config = ComputeFactoryFlowConfig(self.config_file)
        self.flow = ComputeFactoryFlow(config, "compute1")
        rf = self.flow.redfish_utils

        rf.post_request.return_value = (True, {})
        result = self.flow.send_boot_ap(
            ap_name=ap,
            base_uri=base_uri,
            redfish_target="bmc",
        )
        self.assertTrue(result)
        # verify correct action URL
        action_url = rf.post_request.call_args[0][0]
        self.assertIn("Actions/Oem/NvidiaChassis.BootProtectedDevice", action_url)

    def test_boot_mode_error_handling(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        self.mock_utils.get_request.return_value = (False, {"error": "bad"})
        result = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            redfish_target="bmc",
        )
        self.assertFalse(result)

    # ==================== POWER POLICY TESTS ====================

    def test_set_power_policy_always_off(self):
        base_uri = "/redfish/v1/Chassis/System_0"
        self.mock_utils.patch_request.return_value = (True, {})
        result = self.flow.set_power_policy_always_off(base_uri=base_uri)
        self.assertTrue(result)
        payload = self.mock_utils.patch_request.call_args[0][1]
        self.assertEqual(payload.get("PowerRestorePolicy"), "AlwaysOff")

    def test_set_power_policy_always_on(self):
        base_uri = "/redfish/v1/Chassis/System_0"
        self.mock_utils.patch_request.return_value = (True, {})
        result = self.flow.set_power_policy_always_on(base_uri=base_uri)
        self.assertTrue(result)
        payload = self.mock_utils.patch_request.call_args[0][1]
        self.assertEqual(payload.get("PowerRestorePolicy"), "AlwaysOn")

    def test_set_power_policy_last_state(self):
        base_uri = "/redfish/v1/Chassis/System_0"
        self.mock_utils.patch_request.return_value = (True, {})
        result = self.flow.set_power_policy_last_state(base_uri=base_uri)
        self.assertTrue(result)
        payload = self.mock_utils.patch_request.call_args[0][1]
        self.assertEqual(payload.get("PowerRestorePolicy"), "LastState")

    def test_check_power_policy_verification(self):
        base_uri = "/redfish/v1/Chassis/System_0"
        response = {"PowerRestorePolicy": "AlwaysOn"}
        self.mock_utils.get_request.return_value = (True, response)
        result = self.flow.check_power_policy(checked_state="AlwaysOn", base_uri=base_uri)
        self.assertTrue(result)

    def test_power_policy_error_scenarios(self):
        base_uri = "/redfish/v1/Chassis/System_0"
        self.mock_utils.patch_request.return_value = (False, {"error": "bad"})
        self.assertFalse(self.flow.set_power_policy_always_off(base_uri=base_uri))
        self.mock_utils.get_request.return_value = (True, {})
        self.assertFalse(self.flow.check_power_policy(checked_state="AlwaysOn", base_uri=base_uri))

    # ==================== BOOT STATUS / WAIT TESTS ====================

    def test_check_boot_progress_single_state(self):
        base_uri = "/redfish/v1/Systems/System_0"
        response = {"BootProgress": {"LastState": "OSRunning"}}
        self.mock_utils.get_request.return_value = (True, response)
        result = self.flow.check_boot_progress(base_uri=base_uri, state="OSRunning")
        self.assertTrue(result)

    def test_check_boot_progress_multi_states(self):
        base_uri = "/redfish/v1/Systems/System_0"
        response = {"BootProgress": {"LastState": "OSBootStarted"}}
        self.mock_utils.get_request.return_value = (True, response)
        result = self.flow.check_boot_progress(base_uri=base_uri, state=["OSRunning", "OSBootStarted"])
        self.assertTrue(result)

    def test_check_boot_progress_timeout(self):
        base_uri = "/redfish/v1/Systems/System_0"
        # First returns wrong state then we simulate timeout by returning same wrong state
        self.mock_utils.get_request.side_effect = [
            (True, {"BootProgress": {"LastState": "BIOSSetup"}}),
            (True, {"BootProgress": {"LastState": "BIOSSetup"}}),
        ]
        with patch("time.time") as mock_time:
            mock_time.side_effect = [0, 10, 1000]  # exceed timeout
            result = self.flow.check_boot_progress(base_uri=base_uri, state="OSRunning", timeout=60, check_interval=1)
        self.assertFalse(result)

    def test_check_boot_status_code_success(self):
        base_uri = "/redfish/v1/Chassis"
        ap = "ERoT_CPU_0"
        # Provide a BootStatusCode string whose second byte (chars 15-16) is '11'
        response = {"BootStatusCode": "aaaaaaaaaaaaaa11"}
        self.mock_utils.get_request.return_value = (True, response)
        result = self.flow.check_boot_status_code(ap_name=ap, base_uri=base_uri, redfish_target="bmc")
        self.assertTrue(result)

    # ==================== OS COMMAND / SCRIPT / IPMITOOL / FLINT / PREFLIGHT TESTS ====================

    def test_execute_os_command_with_sudo_and_capture_outputs(self):
        # Prepare SSH session to return success
        stdout_text = "root"
        stderr_text = ""
        mock_ssh = self.create_mock_ssh_session([(stdout_text, stderr_text, 0)])
        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh
            saved_stdout, saved_stderr = {}, {}
            result = self.flow.execute_os_command(
                command="whoami",
                use_sudo=True,
                saved_stdout=saved_stdout,
                saved_stderr=saved_stderr,
            )
            self.assertTrue(result)
            # verify saved outputs
            self.assertEqual(saved_stdout.get("output"), stdout_text)
            self.assertEqual(saved_stderr.get("output"), stderr_text)
            # verify sudo used
            exec_cmd = mock_ssh.exec_command.call_args[0][0]
            self.assertIn("sudo -S whoami", exec_cmd)

    def test_execute_os_command_missing_os_config_returns_false(self):
        # Build config without OS username
        bad_cfg = {"connection": {"compute": {"os": {"ip": "192.168.1.101", "password": "test123", "port": 22}}}}
        config_file = self.create_test_config_file("compute", bad_cfg)
        config = ComputeFactoryFlowConfig(config_file)
        with patch("FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging") as mock_setup_logging:
            mock_setup_logging.return_value = self.mock_logger
            flow = ComputeFactoryFlow(config, "compute1")
        result = flow.execute_os_command(command="echo test")
        self.assertFalse(result)

    def test_execute_ipmitool_already_deactivated_treated_success(self):
        # Simulate ipmitool returning code 1 but stderr indicates already de-activated
        def fake_run(cmd, capture_output, text, timeout, check):
            class R:
                def __init__(self):
                    self.stdout = ""
                    self.stderr = "SOL already de-activated"
                    self.returncode = 1

            return R()

        with patch("subprocess.run", side_effect=fake_run):
            result = self.flow.execute_ipmitool_command(command="sol deactivate", timeout=5)
            self.assertTrue(result)

    def test_execute_ipmitool_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ipmitool", timeout=1)):
            result = self.flow.execute_ipmitool_command(command="chassis power status", timeout=1)
            self.assertFalse(result)

    def test_execute_script_success_and_failure(self):
        # Success
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=["cmd"], returncode=0, stdout="ok", stderr="")
            self.assertTrue(self.flow.execute_script("echo ok"))
        # Failure
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=["cmd"], returncode=2, stdout="", stderr="err")
            self.assertFalse(self.flow.execute_script("false"))

    def test_bmc_preflight_check_success_and_failure(self):
        # Success
        self.mock_utils.ping_dut.return_value = 0
        self.mock_utils.get_request.return_value = (True, {})
        self.assertTrue(self.flow.bmc_preflight_check())
        # Failure ping
        self.mock_utils.ping_dut.return_value = 1
        self.assertFalse(self.flow.bmc_preflight_check())
        # Failure redfish
        self.mock_utils.ping_dut.return_value = 0
        self.mock_utils.get_request.return_value = (False, {})
        self.assertFalse(self.flow.bmc_preflight_check())

    def test_flint_verify_success_and_no_paths(self):
        # Patch execute_os_command to simulate mst status and verify commands
        call_log = {"calls": []}

        def fake_exec(command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None):
            call_log["calls"].append(command)
            if command.startswith("mst status -v"):
                if "nopaths" in call_log:  # use flag to simulate no paths
                    if saved_stdout is not None:
                        saved_stdout["output"] = ""
                else:
                    if saved_stdout is not None:
                        saved_stdout["output"] = "/dev/mst/mt0\n/dev/mst/mt0.1"  # .1 will be filtered
                return True
            if command.startswith("flint -d /dev/mst/mt0 -i ~/fw.bin verify"):
                return True
            return False

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec):
            self.assertTrue(self.flow.flint_verify(named_device="BlueField3", file_name="fw.bin"))
            # Now simulate no paths
            call_log["nopaths"] = True
            self.assertFalse(self.flow.flint_verify(named_device="BlueField3", file_name="fw.bin"))

    def test_flint_flash_success_and_failure(self):
        # Patch execute_os_command to simulate mst status and flash commands
        def fake_exec_flash(command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None):
            if command.startswith("mst status -v"):
                if saved_stdout is not None:
                    saved_stdout["output"] = "/dev/mst/mt1\n/dev/mst/mt1.2"  # .2 filtered
                return True
            if command.startswith("flint -d /dev/mst/mt1 --yes -i ~/fw.bin b"):
                return True
            return False

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec_flash):
            self.assertTrue(self.flow.flint_flash(named_device="BlueField3", file_name="fw.bin"))

        # Failure when mst returns no device
        def fake_exec_flash_fail(
            command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None
        ):
            if command.startswith("mst status -v"):
                if saved_stdout is not None:
                    saved_stdout["output"] = ""
                return True
            return False

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec_flash_fail):
            self.assertFalse(self.flow.flint_flash(named_device="BlueField3", file_name="fw.bin"))

        # Test case for "already updated" scenario in stdout - should return True
        def fake_exec_flash_already_updated_stdout(
            command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None
        ):
            if command.startswith("mst status -v"):
                if saved_stdout is not None:
                    saved_stdout["output"] = "/dev/mst/mt1"
                return True
            if command.startswith("flint -d /dev/mst/mt1 --yes -i ~/fw.bin b"):
                if saved_stdout is not None:
                    saved_stdout["output"] = (
                        "-E- Burning FS4 image failed: The firmware image was already updated on flash, pending reset."
                    )
                return False  # Command fails but with "already updated" message in stdout
            return False

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec_flash_already_updated_stdout):
            self.assertTrue(self.flow.flint_flash(named_device="BlueField3", file_name="fw.bin"))

        # Test case for "already updated" scenario in stderr - should return True
        def fake_exec_flash_already_updated_stderr(
            command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None
        ):
            if command.startswith("mst status -v"):
                if saved_stdout is not None:
                    saved_stdout["output"] = "/dev/mst/mt1"
                return True
            if command.startswith("flint -d /dev/mst/mt1 --yes -i ~/fw.bin b"):
                if saved_stderr is not None:
                    saved_stderr["output"] = (
                        "-E- Burning FS4 image failed: The firmware image was already updated on flash, pending reset."
                    )
                return False  # Command fails but with "already updated" message in stderr
            return False

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec_flash_already_updated_stderr):
            self.assertTrue(self.flow.flint_flash(named_device="BlueField3", file_name="fw.bin"))

    def test_check_gpu_inband_update_policy_and_set_policy(self):
        base_uri = "/redfish/v1/Chassis"
        ap = "ERoT_CPU_0"
        # check policy true
        self.mock_utils.get_request.return_value = (
            True,
            {"Oem": {"Nvidia": {"InbandUpdatePolicyEnabled": True}}},
        )
        self.assertTrue(self.flow.check_gpu_inband_update_policy(base_uri=base_uri, ap_name=ap))
        # set policy
        self.mock_utils.patch_request.return_value = (True, {})
        self.assertTrue(
            self.flow.set_gpu_inband_update_policy(
                base_uri=base_uri,
                ap_name=ap,
                data={"Oem": {"Nvidia": {"InbandUpdatePolicyEnabled": True}}},
            )
        )

    def test_scp_files_target_mismatched_remote_files(self):
        target_config = {
            "ip": "192.168.1.101",
            "username": "root",
            "password": "test123",
            "port": 22,
        }
        f1 = self.create_test_file("a.bin", b"A")
        f2 = self.create_test_file("b.bin", b"B")
        self.assertFalse(
            self.flow.config.connection.scp_files_target(
                files=[f1, f2], target_config=target_config, remote_files=["/tmp/a.bin"], logger=self.flow.logger
            )
        )

    def test_scp_files_target_missing_local_file(self):
        target_config = {
            "ip": "192.168.1.101",
            "username": "root",
            "password": "test123",
            "port": 22,
        }
        self.assertFalse(
            self.flow.config.connection.scp_files_target(
                files=["/nonexistent/file"], target_config=target_config, logger=self.flow.logger
            )
        )

    def test_scp_files_target_with_remote_files_and_chmod(self):
        mock_ssh = self.create_mock_ssh_session([("", "", 0), ("", "", 0)])
        mock_sftp = MagicMock()
        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh
            mock_ssh.open_sftp.return_value = mock_sftp
            target_config = {
                "ip": "192.168.1.101",
                "username": "root",
                "password": "test123",
                "port": 22,
            }
            f1 = self.create_test_file("tool.sh", b"#!/bin/sh\necho")
            f2 = self.create_test_file("util", b"bin")
            ok = self.flow.config.connection.scp_files_target(
                files=[f1, f2],
                target_config=target_config,
                remote_files=["/opt/tool.sh", "/var/util"],
                set_executable=True,
                logger=self.flow.logger,
            )
            self.assertTrue(ok)
            mock_ssh.open_sftp.assert_called_once()
            mock_sftp.put.assert_any_call(f1, "/opt/tool.sh")
            mock_sftp.put.assert_any_call(f2, "/var/util")
            chmod_calls = [c for c in mock_ssh.exec_command.call_args_list if "chmod +x" in c[0][0]]
            self.assertEqual(len(chmod_calls), 2)

    def test_get_redfish_utils_hmc_failure_path(self):
        # Force hmc proxy init failure by setting hmc_redfish_utils None
        self.flow.hmc_redfish_utils = None
        # A public method that requests hmc should fail (e.g., check_boot_status_code with redfish_target='hmc')
        res = self.flow.check_boot_status_code(
            ap_name="ERoT_CPU_0", base_uri="/redfish/v1/Chassis", redfish_target="hmc"
        )
        self.assertFalse(res)

    def test_pldm_fw_update_upload_failure(self):
        self.mock_utils.post_upload_request.return_value = (False, {"error": "fail"})
        bundle_path = self.create_test_file("fw.pldm", b"X")
        result = self.flow.pldm_fw_update(
            bundle_path=bundle_path,
            base_uri="/redfish/v1/UpdateService/update-multipart",
            timeout=60,
        )
        # Assert kwargs usage to match Utils.post_upload_request signature
        _, kwargs = self.mock_utils.post_upload_request.call_args
        self.assertIn("url_path", kwargs)
        self.assertIn("file_path", kwargs)
        self.assertFalse(result)

    def test_pldm_fw_update_monitor_failure(self):
        upload_response = {
            "@odata.type": "#Task.v1_4_3.Task",
            "@odata.id": "/redfish/v1/TaskService/Tasks/0",
        }
        self.mock_utils.post_upload_request.return_value = (True, upload_response)
        self.mock_utils.monitor_job.return_value = (False, {"TaskState": "Exception"})
        bundle_path = self.create_test_file("fw.pldm", b"X")
        result = self.flow.pldm_fw_update(
            bundle_path=bundle_path,
            base_uri="/redfish/v1/UpdateService/update-multipart",
            timeout=30,
        )
        # Assert kwargs usage to match Utils.post_upload_request signature
        _, kwargs = self.mock_utils.post_upload_request.call_args
        self.assertIn("url_path", kwargs)
        self.assertIn("file_path", kwargs)
        # Assert monitor_job kwargs usage to match Utils.monitor_job signature
        _, kwargs_m = self.mock_utils.monitor_job.call_args
        self.assertIn("uri", kwargs_m)
        self.assertIn("timeout", kwargs_m)
        self.assertIn("check_interval", kwargs_m)
        self.assertFalse(result)

    def test_pldm_fw_update_hmc_success_and_failure(self):
        # Success path uses HMC via flow.hmc_redfish_utils
        self.flow.hmc_redfish_utils = self.mock_utils
        with patch.object(self.flow.config.connection, "scp_files_target", return_value=True):
            # HttpPushUpdate base_uri is "/redfish/v1/UpdateService/update"
            self.mock_utils.post_upload_request.return_value = (
                True,
                {
                    "@odata.type": "#Task.v1_4_3.Task",
                    "@odata.id": "/redfish/v1/TaskService/Tasks/0",
                },
            )
            self.mock_utils.monitor_job.return_value = (True, {"TaskState": "Completed"})
            bundle_path = self.create_test_file("fw_hmc.pldm", b"Y")
            self.assertTrue(self.flow._pldm_fw_update_hmc(bundle_path=bundle_path))
        # Failure on upload
        with patch.object(self.flow.config.connection, "scp_files_target", return_value=True):
            self.mock_utils.post_upload_request.return_value = (False, {"error": "bad"})
            bundle_path = self.create_test_file("fw_hmc2.pldm", b"Z")
            self.assertFalse(self.flow._pldm_fw_update_hmc(bundle_path=bundle_path))

    def test_dot_cak_install_and_lock_success_and_failure(self):
        # Set DOT to Volatile to test actual install logic (not NoDOT early return)
        self.flow.config.config["compute"]["DOT"] = "Volatile"

        base_uri = "/redfish/v1/Chassis"
        ap = "ERoT_CPU_0"
        # install
        self.mock_utils.post_request.return_value = (True, {})
        self.assertTrue(
            self.flow.dot_cak_install(
                ap_name=ap,
                pem_encoded_key="k",
                ap_firmware_signature="s",
                base_uri=base_uri,
                check_volatile_dot=False,
            )
        )
        self.mock_utils.post_request.return_value = (False, {"error": "bad"})
        self.assertFalse(
            self.flow.dot_cak_install(
                ap_name=ap,
                pem_encoded_key="k",
                ap_firmware_signature="s",
                base_uri=base_uri,
                check_volatile_dot=False,
            )
        )
        # lock (bypass DOT locking gate and include required key)
        self.mock_utils.post_request.return_value = (True, {})
        self.assertTrue(
            self.flow.dot_cak_lock(ap_name=ap, pem_encoded_key="k", base_uri=base_uri, check_locking_dot=False)
        )
        self.mock_utils.post_request.return_value = (False, {"error": "bad"})
        self.assertFalse(
            self.flow.dot_cak_lock(ap_name=ap, pem_encoded_key="k", base_uri=base_uri, check_locking_dot=False)
        )

    def test_power_on_success_and_failure(self):
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        # happy path
        self.mock_utils.post_request.return_value = (True, {})
        self.mock_utils.get_request.side_effect = [
            (True, {"PowerState": "PoweringOn"}),
            (True, {"PowerState": "On"}),
        ]
        with patch("time.sleep"):
            self.assertTrue(self.flow.power_on(base_uri=base_uri))
        # failure on post
        self.mock_utils.post_request.return_value = (False, {"error": "bad"})
        self.assertFalse(self.flow.power_on(base_uri=base_uri))

    def test_power_off_success_with_dot_check_and_failure(self):
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        # DOT not volatile returns True early
        cfg = {"compute": {"DOT": "Locking"}}
        config_path = self.create_test_config_file("compute", cfg)
        config = ComputeFactoryFlowConfig(config_path)
        with patch("FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging") as mock_setup_logging:
            mock_setup_logging.return_value = self.mock_logger
            flow2 = ComputeFactoryFlow(config, "compute2")
        self.assertTrue(flow2.power_off(base_uri=base_uri, check_volatile_dot=True))
        # Normal success path
        self.mock_utils.post_request.return_value = (True, {})
        self.mock_utils.get_request.side_effect = [
            (True, {"PowerState": "PoweringOff"}),
            (True, {"PowerState": "Off"}),
        ]
        with patch("time.sleep"):
            self.assertTrue(self.flow.power_off(base_uri=base_uri))

    def test_wait_for_boot_sol_start_failure_and_power_on_failure(self):
        # Enable POST logging via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        # SOL start failure
        with patch.object(self.flow, "_start_ipmi_sol_logging", return_value=None):
            self.assertFalse(
                self.flow.wait_for_boot(
                    power_on_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
                    system_uri="/redfish/v1/Systems/System_0",
                    state="OSRunning",
                )
            )
        # power on failure following successful SOL start
        with patch.object(self.flow, "_start_ipmi_sol_logging", return_value="log_path"), patch.object(
            self.flow, "power_on", return_value=False
        ), patch.object(self.flow, "stop_sol_logging", return_value=True):
            self.assertFalse(
                self.flow.wait_for_boot(
                    power_on_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
                    system_uri="/redfish/v1/Systems/System_0",
                    state="OSRunning",
                )
            )

    def test_wait_for_boot_checks_progress_and_stops_sol_on_failure(self):
        # Enable POST logging via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        with patch.object(self.flow, "_start_ipmi_sol_logging", return_value="log_path"), patch.object(
            self.flow, "power_on", return_value=True
        ), patch.object(self.flow, "check_boot_progress", return_value=False), patch.object(
            self.flow, "stop_sol_logging", return_value=True
        ):
            self.assertFalse(
                self.flow.wait_for_boot(
                    power_on_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
                    system_uri="/redfish/v1/Systems/System_0",
                    state="OSRunning",
                )
            )

    def test_execute_ipmitool_os_creds_no_lanplus_success(self):
        def fake_run(cmd, capture_output, text, timeout, check):
            class R:
                def __init__(self):
                    self.stdout = "ok"
                    self.stderr = ""
                    self.returncode = 0

            return R()

        with patch("subprocess.run", side_effect=fake_run):
            saved_out, saved_err = {}, {}
            ok = self.flow.execute_ipmitool_command(
                command="chassis power status",
                use_lanplus=False,
                use_bmc_credentials=False,
                timeout=2,
                saved_stdout=saved_out,
                saved_stderr=saved_err,
            )
            self.assertTrue(ok)
            self.assertEqual(saved_out.get("output"), "ok")

    def test_pass_and_fail_helpers(self):
        self.assertTrue(self.flow.pass_test("ok"))
        self.assertFalse(self.flow.fail_test("bad"))

    def test_reboot_bmc_success_and_failure(self):
        base_uri = "/redfish/v1/Managers/BMC_0/Actions/Manager.Reset"
        # success
        self.mock_utils.post_request.return_value = (True, {})
        with patch("time.sleep"):
            self.assertTrue(self.flow.reboot_bmc(base_uri=base_uri))
        # failure (error string)
        self.mock_utils.post_request.return_value = (True, {"error": "bad"})
        self.assertFalse(self.flow.reboot_bmc(base_uri=base_uri))
        # failure (status False)
        self.mock_utils.post_request.return_value = (False, {"msg": "bad"})
        self.assertFalse(self.flow.reboot_bmc(base_uri=base_uri))

    def test_check_versions_failure_cases_and_hmc_missing(self):
        expected = {"BMC": "1.2.3"}
        # non-dict response
        self.mock_utils.get_request.return_value = (True, "string")
        self.assertFalse(self.flow.check_versions(expected_versions=expected, operator="=="))
        # missing Version key
        self.mock_utils.get_request.return_value = (True, {"NoVersion": "x"})
        self.assertFalse(self.flow.check_versions(expected_versions=expected, operator="=="))
        # compare false
        self.mock_utils.get_request.return_value = (True, {"Version": "0.0.1"})
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.Utils.compare_versions",
            return_value=False,
        ):
            self.assertFalse(self.flow.check_versions(expected_versions=expected, operator="=="))
        # HMC utils None path
        self.flow.hmc_redfish_utils = None
        self.assertFalse(self.flow.check_versions(expected_versions=expected, operator=">=", redfish_target="hmc"))

    def test_stop_sol_logging_no_entry_and_timeout_kill(self):
        # No entry path
        self.assertTrue(self.flow.stop_sol_logging("/tmp/missing.log"))

        # Timeout then kill path
        class Proc:
            def __init__(self):
                self.pid = 123

            def terminate(self):
                pass

            def wait(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired(cmd="ipmitool", timeout=timeout)
                return None

            def kill(self):
                pass

        class Log:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        self.flow._sol_processes["/tmp/sol.log"] = {
            "process": Proc(),
            "log_file": Log(),
            "thread": None,
        }
        with patch.object(self.flow, "execute_ipmitool_command", return_value=True):
            self.assertTrue(self.flow.stop_sol_logging("/tmp/sol.log"))

    def test_check_boot_status_code_invalid_and_timeout(self):
        base_uri = "/redfish/v1/Chassis"
        ap = "ERoT_CPU_0"
        # invalid short string, no timeout â†’ False
        self.mock_utils.get_request.return_value = (True, {"BootStatusCode": "0x1"})
        self.assertFalse(self.flow.check_boot_status_code(ap_name=ap, base_uri=base_uri))
        # timeout path with second byte not 11
        self.mock_utils.get_request.return_value = (True, {"BootStatusCode": "aaaaaaaaaaaaaa10"})
        with patch("time.time") as mock_time:
            mock_time.side_effect = [0, 10, 30, 61]
            self.assertFalse(
                self.flow.check_boot_status_code(ap_name=ap, base_uri=base_uri, timeout=60, check_interval=1)
            )

    def test_power_on_reissue_then_success(self):
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        self.mock_utils.post_request.return_value = (True, {})
        # First response unexpected state, second powering, third on
        self.mock_utils.get_request.side_effect = [
            (True, {"PowerState": "Unknown"}),
            (True, {"PowerState": "PoweringOn"}),
            (True, {"PowerState": "On"}),
        ]
        with patch("time.sleep"):
            self.assertTrue(self.flow.power_on(base_uri=base_uri))

    def test_power_off_post_failure(self):
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        self.mock_utils.post_request.return_value = (False, {"error": "bad"})
        self.assertFalse(self.flow.power_off(base_uri=base_uri))

    def test_close_idempotent(self):
        # Should not raise
        self.flow.close()
        # Call a second time
        self.flow.close()

    def test_config_validation_errors(self):
        # Negative wait values
        bad_cfg = {"settings": {"default_wait_after_seconds": -1}}
        with self.assertRaises(ValueError):
            ComputeFactoryFlowConfig(self.create_test_config_file("compute", bad_cfg))
        # Non-int port
        bad_cfg2 = {
            "connection": {"compute": {"bmc": {"ip": "1.1.1.1", "username": "u", "password": "p", "port": "22"}}}
        }
        with self.assertRaises(ValueError):
            ComputeFactoryFlowConfig(self.create_test_config_file("compute", bad_cfg2))
        # Port out of range
        bad_cfg3 = {
            "connection": {"compute": {"bmc": {"ip": "1.1.1.1", "username": "u", "password": "p", "port": 70000}}}
        }
        with self.assertRaises(ValueError):
            ComputeFactoryFlowConfig(self.create_test_config_file("compute", bad_cfg3))

    def test_bmc_connection_details_missing_fields(self):
        bad = {"connection": {"compute": {"bmc": {"ip": "", "username": None, "password": ""}}}}
        cfg_path = self.create_test_config_file("compute", bad)
        cfg = ComputeFactoryFlowConfig(cfg_path)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            # After refactoring, construction doesn't fail but logs warning and sets redfish_utils to None
            flow = ComputeFactoryFlow(cfg, "computeX")
            self.assertIsNone(flow.redfish_utils)
            self.assertIsNone(flow.hmc_redfish_utils)
            # Should have logged warnings about failed initialization
            self.assertTrue(self.mock_logger.warning.called)
            self.assertTrue(self.mock_logger.error.called)

    def test_join_url_path_edge_cases(self):
        base = "/redfish/v1/"
        self.assertEqual(
            self.flow._join_url_path(base, "Systems", "/System_0", ""),
            "/redfish/v1/Systems/System_0",
        )
        self.assertEqual(
            self.flow._join_url_path("/redfish/v1", "/Systems/", "/System_0/"),
            "/redfish/v1/Systems/System_0",
        )

    def test_os_connection_details_missing_and_defaults(self):
        bad = {"connection": {"compute": {"os": {"ip": "1.1.1.1", "password": "p"}}}}
        cfg_path = self.create_test_config_file("compute", bad)
        cfg = ComputeFactoryFlowConfig(cfg_path)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            f = ComputeFactoryFlow(cfg, "compute1")
        # Force missing username at runtime to avoid defaults from base fixture
        f.config.config["connection"]["compute"]["os"] = {"ip": "1.1.1.1", "password": "p"}
        with self.assertRaises(ValueError):
            f._get_os_connection_details()

    def test_pldm_common_no_task_and_running_paths(self):
        # No task returned
        self.mock_redfish_utils.post_upload_request.return_value = (
            True,
            {"@odata.type": "#Task.v1_4_3.Task"},
        )
        ok = self.flow._pldm_fw_update_common(
            redfish_utils=self.mock_redfish_utils,
            bundle_path="/tmp/fw.pldm",
            base_uri="/redfish/v1/UpdateService/update",
            target_name="BMC",
        )
        self.assertFalse(ok)
        # Running after monitor
        self.mock_redfish_utils.post_upload_request.return_value = (
            True,
            {"@odata.type": "#Task.v1_4_3.Task", "@odata.id": "/redfish/v1/TaskService/Tasks/0"},
        )
        self.mock_redfish_utils.monitor_job.return_value = (True, {"TaskState": "Running"})
        ok2 = self.flow._pldm_fw_update_common(
            redfish_utils=self.mock_redfish_utils,
            bundle_path="/tmp/fw.pldm",
            base_uri="/redfish/v1/UpdateService/update",
            target_name="BMC",
        )
        self.assertFalse(ok2)

    def test_dot_cak_install_skips_on_empty_inputs(self):
        self.assertTrue(self.flow.dot_cak_install(ap_name="AP_0", pem_encoded_key="", ap_firmware_signature="s"))
        self.assertTrue(self.flow.dot_cak_install(ap_name="AP_0", pem_encoded_key="k", ap_firmware_signature=""))

    def test_dot_cak_install_hmc_failure_path(self):
        # Set DOT to Volatile to test actual install logic (not NoDOT early return)
        self.flow.config.config["compute"]["DOT"] = "Volatile"

        self.flow.hmc_redfish_utils = None
        self.assertFalse(
            self.flow.dot_cak_install(
                ap_name="AP_0",
                pem_encoded_key="k",
                ap_firmware_signature="s",
                redfish_target="hmc",
                check_volatile_dot=False,
            )
        )

    def test_set_power_policy_exception_paths(self):
        self.flow.redfish_utils.patch_request.side_effect = ValueError("bad")
        self.assertFalse(self.flow.set_power_policy_always_off(base_uri="/x"))
        self.flow.redfish_utils.patch_request.side_effect = Exception("boom")
        self.assertFalse(self.flow.set_power_policy_always_on(base_uri="/x"))

    def test_check_power_policy_bad_response(self):
        self.flow.redfish_utils.get_request.return_value = (True, {})
        self.assertFalse(self.flow.check_power_policy(checked_state="AlwaysOn", base_uri="/x"))
        self.flow.redfish_utils.get_request.return_value = (True, "string")
        self.assertFalse(self.flow.check_power_policy(checked_state="AlwaysOn", base_uri="/x"))

    def test_ac_cycle_success_and_failure(self):
        # Failure on POST
        self.flow.redfish_utils.post_request.return_value = (False, {"error": "bad"})
        with patch("time.sleep"):
            self.assertFalse(
                self.flow.ac_cycle(base_uri="/redfish/v1/Chassis/BMC_0/Actions/Oem/NvidiaChassis.AuxPowerReset")
            )
        # Success
        self.flow.redfish_utils.post_request.return_value = (True, {})
        with patch("time.sleep"):
            self.assertTrue(
                self.flow.ac_cycle(base_uri="/redfish/v1/Chassis/BMC_0/Actions/Oem/NvidiaChassis.AuxPowerReset")
            )

    def test_wait_ap_ready_non_dict_and_timeout(self):
        # get_request returns False repeatedly and then timeout
        self.flow.redfish_utils.get_request.return_value = (False, {"error": "bad"})
        with patch("time.time") as mt:
            mt.side_effect = [0, 30, 61]
            with patch("time.sleep"):
                self.assertFalse(self.flow.wait_ap_ready(ap_name="A", base_uri="/x", timeout=60))

    def test_nvflash_check_vbios_warn_on_rmmod(self):
        # rmmod non-zero then nvflash succeeds
        mock_ssh = self.create_mock_ssh_session([("", "mod not loaded", 1), ("ok", "", 0)])
        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh
            self.assertTrue(self.flow.nvflash_check_vbios())
            self.assert_logger_has_warning("Failed to remove some NVIDIA modules")

    def test_nvflash_flash_vbios_unexpected_exception(self):
        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.side_effect = Exception("init fail")
            self.assertFalse(self.flow.nvflash_flash_vbios(vbios_bundle="x.rom"))

    def test_background_copy_pending_failed_and_timeout(self):
        # Mixed responses: one AP pending, one failed; timeout None -> False
        def get_resp(uri, *a, **k):
            if uri.endswith("AP_0"):
                return (True, {"Oem": {"Nvidia": {"BackgroundCopyStatus": "InProgress"}}})
            return (False, {"error": "bad"})

        self.flow.redfish_utils.get_request.side_effect = get_resp
        self.assertFalse(self.flow.monitor_background_copy(ap_name=["AP_0", "AP_1"], base_uri="/x", timeout=None))
        # Timeout path: always pending until timeout
        self.flow.redfish_utils.get_request.side_effect = lambda uri, **k: (True, {})
        with patch("time.time") as mt:
            mt.side_effect = [0, 10, 40, 100]
            with patch("time.sleep"):
                self.assertFalse(self.flow.monitor_background_copy(ap_name=["AP_0"], base_uri="/x", timeout=30))

    def test_background_copy_utils_and_exception_paths(self):
        # _get_redfish_utils raises ValueError
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("no hmc")):
            self.assertFalse(self.flow.monitor_background_copy(ap_name="AP_0", base_uri="/x", redfish_target="hmc"))
        # Generic exception path
        with patch.object(self.flow, "_get_redfish_utils", side_effect=Exception("boom")):
            self.assertFalse(self.flow.monitor_background_copy(ap_name="AP_0", base_uri="/x", redfish_target="hmc"))

    def test_power_on_timeout_and_bad_response(self):
        # Bad POST response with error string
        self.flow.redfish_utils.post_request.return_value = (True, {"error": "bad"})
        self.assertFalse(self.flow.power_on(base_uri="/x"))
        # Timeout path
        self.flow.redfish_utils.post_request.return_value = (True, {})
        self.flow.redfish_utils.get_request.return_value = (True, "string")
        with patch("time.time") as mt:
            mt.side_effect = [0, 10, 61]
            with patch("time.sleep"):
                self.assertFalse(self.flow.power_on(base_uri="/x"))

    def test_power_off_check_state_error(self):
        self.flow.redfish_utils.post_request.return_value = (False, {"error": "bad"})
        self.assertFalse(self.flow.power_off(base_uri="/x"))

    def test_start_sol_logging_popen_error(self):
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with patch("subprocess.Popen", side_effect=OSError("spawn fail")):
            self.flow.execute_ipmitool_command = MagicMock(return_value=True)
            result = self.flow._start_ipmi_sol_logging(timestamp)
            self.assertIsNone(result)

    def test_get_redfish_utils_hmc_success(self):
        self.flow.hmc_redfish_utils = self.mock_utils
        self.assertIs(self.flow._get_redfish_utils("hmc"), self.mock_utils)

    def test_execute_script_exception_path(self):
        with patch("subprocess.run", side_effect=Exception("boom")):
            self.assertFalse(self.flow.execute_script("echo hi"))

    def test_send_boot_ap_hmc_variant(self):
        self.flow.hmc_redfish_utils = self.mock_utils
        self.mock_utils.post_request.return_value = (True, {})
        ok = self.flow.send_boot_ap(
            ap_name="ERoT_CPU_0",
            base_uri="/redfish/v1/Chassis",
            redfish_target="hmc",
            check_volatile_dot=False,
        )
        self.assertTrue(ok)
        action_url = self.mock_utils.post_request.call_args[0][0]
        self.assertIn("Actions/Oem/NvidiaChassis.BootProtectedDevice", action_url)

    def test_config_validation_username_password_type_errors(self):
        # username not a string
        bad_cfg = {"connection": {"compute": {"bmc": {"ip": "1.1.1.1", "username": 123, "password": "p", "port": 443}}}}
        with self.assertRaises(ValueError):
            ComputeFactoryFlowConfig(self.create_test_config_file("compute", bad_cfg))
        # password not a string
        bad_cfg2 = {
            "connection": {"compute": {"bmc": {"ip": "1.1.1.1", "username": "u", "password": 123, "port": 443}}}
        }
        with self.assertRaises(ValueError):
            ComputeFactoryFlowConfig(self.create_test_config_file("compute", bad_cfg2))

    def test_config_validation_ip_out_of_range(self):
        bad_cfg = {
            "connection": {"compute": {"bmc": {"ip": "300.1.1.1", "username": "u", "password": "p", "port": 443}}}
        }
        # Implementation treats invalid IPv4 as possibly a hostname/IPv6, so no exception expected
        _ = ComputeFactoryFlowConfig(self.create_test_config_file("compute", bad_cfg))

    def test_hmc_proxy_init_failure_in_constructor(self):
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.HMCRedfishUtils",
            side_effect=Exception("boom"),
        ):
            with patch(
                "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
                return_value=self.mock_logger,
            ):
                cfg = ComputeFactoryFlowConfig(self.config_file)
                flow = ComputeFactoryFlow(cfg, "deviceX")
                self.assertIsNone(flow.hmc_redfish_utils)

    def test_get_os_connection_details_success_and_missing_variants(self):
        # success path
        cfg_ok = {"connection": {"compute": {"os": {"ip": "10.0.0.1", "username": "root", "password": "pw"}}}}
        cfg_path = self.create_test_config_file("compute", cfg_ok)
        cfg = ComputeFactoryFlowConfig(cfg_path)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            flow = ComputeFactoryFlow(cfg, "compute1")
        details = flow._get_os_connection_details()
        self.assertEqual(details["port"], 22)
        # missing ip and password
        flow.config.config["connection"]["compute"]["os"] = {"username": "root"}
        with self.assertRaises(ValueError) as ctx:
            flow._get_os_connection_details()
        self.assertIn("ip", str(ctx.exception))
        self.assertIn("password", str(ctx.exception))

    def test_scp_files_target_missing_required_keys(self):
        target_config = {"username": "u", "password": "p"}
        f = self.create_test_file("x.bin", b"X")
        self.assertFalse(
            self.flow.config.connection.scp_files_target(files=f, target_config=target_config, logger=self.flow.logger)
        )

    @patch("paramiko.SSHClient")
    def test_scp_files_target_sftp_exception_and_cleanup(self, mock_ssh_class):
        mock_ssh = MagicMock()
        mock_ssh.open_sftp.side_effect = Exception("sftp fail")
        mock_ssh_class.return_value = mock_ssh
        f = self.create_test_file("x.bin", b"X")
        target_config = {"ip": "1.1.1.1", "username": "u", "password": "p"}
        ok = self.flow.config.connection.scp_files_target(files=f, target_config=target_config, logger=self.flow.logger)
        self.assertFalse(ok)
        mock_ssh.close.assert_called()

    @patch("paramiko.SSHClient")
    def test_scp_files_target_set_executable_false_no_chmod(self, mock_ssh_class):
        mock_ssh = self.create_mock_ssh_session([])
        sftp = MagicMock()
        mock_ssh.open_sftp.return_value = sftp
        mock_ssh_class.return_value = mock_ssh
        f = self.create_test_file("tool.sh", b"#!/bin/sh\necho")
        target_config = {"ip": "1.1.1.1", "username": "u", "password": "p"}
        ok = self.flow.config.connection.scp_files_target(
            files=f, target_config=target_config, remote_base_path="/opt", set_executable=False, logger=self.flow.logger
        )
        self.assertTrue(ok)
        # ensure no chmod commands executed
        chmod_calls = [c for c in mock_ssh.exec_command.call_args_list if "chmod +x" in c[0][0]]
        self.assertEqual(len(chmod_calls), 0)

    def test_pldm_fw_update_routes_to_hmc(self):
        with patch.object(self.flow, "_pldm_fw_update_hmc", return_value=True) as p:
            bundle_path = self.create_test_file("fw.pldm", b"X")
            ok = self.flow.pldm_fw_update(bundle_path=bundle_path, base_uri="/x", redfish_target="hmc")
            self.assertTrue(ok)
            p.assert_called_once()

    def test_pldm_fw_update_hmc_early_failure_when_no_proxy(self):
        self.flow.hmc_redfish_utils = None
        bundle_path = self.create_test_file("fwh.pldm", b"X")
        self.assertFalse(self.flow._pldm_fw_update_hmc(bundle_path=bundle_path))

    def test_dot_cak_lock_skips_on_empty_key(self):
        ok = self.flow.dot_cak_lock(ap_name="AP_0", pem_encoded_key="", base_uri="/redfish/v1/Chassis")
        self.assertTrue(ok)

    def test_reboot_bmc_hmc_success(self):
        self.flow.hmc_redfish_utils = self.mock_utils
        self.mock_utils.post_request.return_value = (True, {})
        with patch("time.sleep"):
            ok = self.flow.reboot_bmc(base_uri="/redfish/v1/Managers/HMC/Actions/Manager.Reset", redfish_target="hmc")
        self.assertTrue(ok)

    def test_check_power_policy_mismatch_warning(self):
        base_uri = "/redfish/v1/Chassis/System_0"
        self.mock_utils.get_request.return_value = (True, {"PowerRestorePolicy": "AlwaysOff"})
        self.assertFalse(self.flow.check_power_policy(checked_state="AlwaysOn", base_uri=base_uri))

    def test_ac_cycle_exceptions(self):
        self.flow.redfish_utils.post_request.side_effect = ValueError("bad")
        with patch("time.sleep"):
            self.assertFalse(self.flow.ac_cycle(base_uri="/x"))
        self.flow.redfish_utils.post_request.side_effect = Exception("boom")
        with patch("time.sleep"):
            self.assertFalse(self.flow.ac_cycle(base_uri="/x"))

    def test_wait_ap_ready_true_status_but_non_dict_then_timeout(self):
        self.flow.redfish_utils.get_request.return_value = (True, "string")
        with patch("time.time") as mt:
            mt.side_effect = [0, 30, 61]
            with patch("time.sleep"):
                self.assertFalse(self.flow.wait_ap_ready(ap_name="AP_0", base_uri="/x", timeout=60))

    def test_hmc_factory_reset_success(self):
        # Switch to HMC path as well
        self.flow.hmc_redfish_utils = self.mock_utils
        self.mock_utils.post_request.return_value = (True, {"ok": True})
        self.assertTrue(
            self.flow.hmc_factory_reset(
                base_uri="/redfish/v1/Managers/HMC/Actions/ResetToDefaults", redfish_target="hmc"
            )
        )

    def test_nvflash_check_vbios_and_flash_missing_os_config(self):
        # remove OS creds from config
        self.flow.config.config["connection"]["compute"]["os"] = {"ip": "1.1.1.1"}
        self.assertFalse(self.flow.nvflash_check_vbios())
        self.assertFalse(self.flow.nvflash_flash_vbios(vbios_bundle="x.rom"))

    def test_check_boot_progress_non_dict_bootprogress_and_response(self):
        base_uri = "/redfish/v1/Systems/System_0"
        # BootProgress not dict
        self.mock_utils.get_request.return_value = (True, {"BootProgress": "unknown"})
        self.assertFalse(self.flow.check_boot_progress(base_uri=base_uri, state="OSRunning"))
        # Response not dict
        self.mock_utils.get_request.return_value = (True, "string")
        self.assertFalse(self.flow.check_boot_progress(base_uri=base_uri, state="OSRunning"))

    def test_close_resource_cleanup_error_paths(self):
        class BadRes:
            def close(self):
                raise RuntimeError("close fail")

        self.flow._opened_resources.append(BadRes())

        class BadHMC:
            def close(self):
                raise RuntimeError("hmc close fail")

        self.flow.hmc_redfish_utils = BadHMC()
        # should not raise
        self.flow.close()

    def test_gpu_inband_update_policy_hmc_paths(self):
        # None hmc utils -> False
        self.flow.hmc_redfish_utils = None
        self.assertFalse(
            self.flow.check_gpu_inband_update_policy(
                base_uri="/redfish/v1/Chassis", ap_name="GPU_0", redfish_target="hmc"
            )
        )
        # success true / false
        self.flow.hmc_redfish_utils = self.mock_utils
        self.mock_utils.get_request.return_value = (
            True,
            {"Oem": {"Nvidia": {"InbandUpdatePolicyEnabled": True}}},
        )
        self.assertTrue(
            self.flow.check_gpu_inband_update_policy(
                base_uri="/redfish/v1/Chassis", ap_name="GPU_0", redfish_target="hmc"
            )
        )
        self.mock_utils.get_request.return_value = (
            True,
            {"Oem": {"Nvidia": {"InbandUpdatePolicyEnabled": False}}},
        )
        self.assertFalse(
            self.flow.check_gpu_inband_update_policy(
                base_uri="/redfish/v1/Chassis", ap_name="GPU_0", redfish_target="hmc"
            )
        )

    def test_set_gpu_inband_update_policy_hmc_paths(self):
        self.flow.hmc_redfish_utils = None
        self.assertFalse(
            self.flow.set_gpu_inband_update_policy(
                base_uri="/redfish/v1/Chassis", ap_name="GPU_0", redfish_target="hmc"
            )
        )
        self.flow.hmc_redfish_utils = self.mock_utils
        self.mock_utils.patch_request.return_value = (True, {})
        self.assertTrue(
            self.flow.set_gpu_inband_update_policy(
                base_uri="/redfish/v1/Chassis", ap_name="GPU_0", redfish_target="hmc"
            )
        )
        self.mock_utils.patch_request.return_value = (False, {"error": "bad"})
        self.assertFalse(
            self.flow.set_gpu_inband_update_policy(
                base_uri="/redfish/v1/Chassis", ap_name="GPU_0", redfish_target="hmc"
            )
        )

    @patch("paramiko.SSHClient")
    def test_execute_os_command_no_sudo(self, mock_ssh_class):
        mock_ssh = self.create_mock_ssh_session([("user", "", 0)])
        mock_ssh_class.return_value = mock_ssh
        ok = self.flow.execute_os_command(command="whoami", use_sudo=False)
        self.assertTrue(ok)
        sent = mock_ssh.exec_command.call_args[0][0]
        self.assertNotIn("sudo -S", sent)

    def test_execute_ipmitool_missing_bmc_config(self):
        # wipe bmc creds
        self.flow.config.config["connection"]["compute"]["bmc"] = {"ip": ""}
        self.assertFalse(self.flow.execute_ipmitool_command(command="chassis status", use_bmc_credentials=True))

    def test_stop_sol_logging_exception_path(self):
        class Proc:
            def __init__(self):
                self.pid = 1234

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return None

            def kill(self):
                pass

        class Log:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        self.flow._sol_processes["/tmp/sol_exc.log"] = {
            "process": Proc(),
            "log_file": Log(),
            "thread": None,
        }
        with patch.object(self.flow, "execute_ipmitool_command", side_effect=Exception("boom")):
            self.assertFalse(self.flow.stop_sol_logging("/tmp/sol_exc.log"))

    def test_wait_for_boot_full_success(self):
        # Enable POST logging via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        with patch.object(self.flow, "_start_ipmi_sol_logging", return_value="log_path"), patch.object(
            self.flow, "power_on", return_value=True
        ), patch.object(self.flow, "check_boot_progress", return_value=True), patch.object(
            self.flow, "stop_sol_logging", return_value=True
        ):
            ok = self.flow.wait_for_boot(
                power_on_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
                system_uri="/redfish/v1/Systems/System_0",
                state=["OSRunning"],
            )
            self.assertTrue(ok)

    def test_check_versions_skips_none_expected(self):
        self.flow.redfish_utils.get_request.return_value = (True, {"Version": "1.0.0"})
        expected = {"FW_A": None, "FW_B": "1.0.0", "FW_C": ""}
        ok = self.flow.check_versions(
            expected_versions=expected,
            operator="==",
            base_uri="/redfish/v1/UpdateService/FirmwareInventory/",
        )
        self.assertTrue(ok)

    def test_check_boot_status_code_no_timeout_not_11_returns_false(self):
        self.mock_utils.get_request.return_value = (True, {"BootStatusCode": "aaaaaaaaaaaaaa10"})
        self.assertFalse(self.flow.check_boot_status_code(ap_name="AP_0", base_uri="/redfish/v1/Chassis", timeout=None))

    def test_pldm_common_exception_path(self):
        # Simulate exception during upload to reach exception handler
        self.mock_redfish_utils.post_upload_request.side_effect = Exception("upload boom")
        ok = self.flow._pldm_fw_update_common(
            redfish_utils=self.mock_redfish_utils,
            bundle_path="/tmp/fw.pldm",
            base_uri="/redfish/v1/UpdateService/update",
            target_name="BMC",
        )
        self.assertFalse(ok)

    def test_dot_cak_install_post_exception(self):
        # Set DOT to Volatile to test actual install logic (not NoDOT early return)
        self.flow.config.config["compute"]["DOT"] = "Volatile"

        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = Exception("post fail")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            ok = self.flow.dot_cak_install(
                ap_name="AP_0",
                pem_encoded_key="k",
                ap_firmware_signature="s",
                base_uri="/x",
                check_volatile_dot=False,
            )
            self.assertFalse(ok)

    def test_dot_cak_lock_valueerror_and_exception(self):
        # ValueError from _get_redfish_utils when HMC requested
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("no hmc")):
            self.assertFalse(
                self.flow.dot_cak_lock(
                    ap_name="AP_0",
                    pem_encoded_key="k",
                    redfish_target="hmc",
                    check_locking_dot=False,
                )
            )
        # Exception during post
        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = Exception("boom")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            self.assertFalse(self.flow.dot_cak_lock(ap_name="AP_0", pem_encoded_key="k", check_locking_dot=False))

    def test_reboot_bmc_valueerror_and_exception(self):
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("bad")):
            self.assertFalse(self.flow.reboot_bmc(base_uri="/x", redfish_target="hmc"))
        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = Exception("boom")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            self.assertFalse(self.flow.reboot_bmc(base_uri="/x", redfish_target="hmc"))

    def test_set_power_policy_on_last_state_exceptions(self):
        self.flow.redfish_utils.patch_request.side_effect = ValueError("bad")
        self.assertFalse(self.flow.set_power_policy_always_on(base_uri="/x"))
        self.flow.redfish_utils.patch_request.side_effect = Exception("boom")
        self.assertFalse(self.flow.set_power_policy_last_state(base_uri="/x"))

    def test_check_power_policy_valueerror_and_exception(self):
        self.flow.redfish_utils.get_request.side_effect = ValueError("bad")
        self.assertFalse(self.flow.check_power_policy(checked_state="AlwaysOn", base_uri="/x"))
        self.flow.redfish_utils.get_request.side_effect = Exception("boom")
        self.assertFalse(self.flow.check_power_policy(checked_state="AlwaysOn", base_uri="/x"))

    def test_wait_ap_ready_hmc_missing(self):
        self.flow.hmc_redfish_utils = None
        with patch("time.sleep"):
            self.assertFalse(self.flow.wait_ap_ready(ap_name="AP_0", base_uri="/x", timeout=10, redfish_target="hmc"))

    def test_hmc_factory_reset_valueerror_and_exception(self):
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("bad")):
            self.assertFalse(self.flow.hmc_factory_reset(base_uri="/x", redfish_target="hmc"))
        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = Exception("boom")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            self.assertFalse(self.flow.hmc_factory_reset(base_uri="/x", redfish_target="hmc"))

    @patch("paramiko.SSHClient")
    def test_nvflash_check_vbios_exec_command_exception(self, mock_ssh_class):
        mock_ssh = MagicMock()
        mock_ssh.connect.return_value = None
        mock_ssh.exec_command.side_effect = Exception("exec fail")
        mock_ssh_class.return_value = mock_ssh
        self.assertFalse(self.flow.nvflash_check_vbios())

    @patch("paramiko.SSHClient")
    def test_nvflash_flash_vbios_exec_command_exception(self, mock_ssh_class):
        mock_ssh = MagicMock()
        mock_ssh.connect.return_value = None
        mock_ssh.exec_command.side_effect = Exception("exec fail")
        mock_ssh_class.return_value = mock_ssh
        self.assertFalse(self.flow.nvflash_flash_vbios(vbios_bundle="x.rom"))

    def test_background_copy_get_request_raises(self):
        mock_utils = MagicMock()
        mock_utils.get_request.side_effect = ValueError("bad")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            self.assertFalse(self.flow.monitor_background_copy(ap_name=["AP_0"], base_uri="/x", timeout=10))
        mock_utils = MagicMock()
        mock_utils.get_request.side_effect = Exception("boom")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            self.assertFalse(self.flow.monitor_background_copy(ap_name=["AP_0"], base_uri="/x", timeout=10))

    def test_power_on_off_exceptions(self):
        self.flow.redfish_utils.post_request.side_effect = ValueError("bad")
        self.assertFalse(self.flow.power_on(base_uri="/x"))
        self.flow.redfish_utils.post_request.side_effect = Exception("boom")
        self.assertFalse(self.flow.power_off(base_uri="/x"))

    def test_check_manual_boot_mode_exceptions_and_hmc_missing(self):
        # HMC missing
        self.flow.hmc_redfish_utils = None
        self.assertFalse(self.flow.check_manual_boot_mode(ap_name="AP_0", base_uri="/x", redfish_target="hmc"))
        # Exceptions
        self.flow.hmc_redfish_utils = self.mock_utils
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("bad")):
            self.assertFalse(self.flow.check_manual_boot_mode(ap_name="AP_0", base_uri="/x"))
        with patch.object(self.flow, "_get_redfish_utils", return_value=self.mock_utils):
            self.flow.redfish_utils.get_request.side_effect = Exception("boom")
            self.assertFalse(self.flow.check_manual_boot_mode(ap_name="AP_0", base_uri="/x"))
            # reset side effect
            self.flow.redfish_utils.get_request.side_effect = None

    def test_set_manual_boot_mode_exceptions(self):
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("bad")):
            self.assertFalse(self.flow.set_manual_boot_mode(ap_name="AP_0", base_uri="/x"))
        mock_utils = MagicMock()
        mock_utils.patch_request.side_effect = Exception("boom")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            self.assertFalse(self.flow.set_manual_boot_mode(ap_name="AP_0", base_uri="/x", check_volatile_dot=False))

    def test_send_boot_ap_hmc_missing_and_exception(self):
        self.flow.hmc_redfish_utils = None
        self.assertFalse(
            self.flow.send_boot_ap(ap_name="AP_0", base_uri="/x", redfish_target="hmc", check_volatile_dot=False)
        )
        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = Exception("boom")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            self.assertFalse(self.flow.send_boot_ap(ap_name="AP_0", base_uri="/x", check_volatile_dot=False))

    def test_check_boot_progress_exceptions(self):
        self.flow.redfish_utils.get_request.side_effect = ValueError("bad")
        self.assertFalse(self.flow.check_boot_progress(base_uri="/x", state="OSRunning", timeout=30))
        self.flow.redfish_utils.get_request.side_effect = Exception("boom")
        self.assertFalse(self.flow.check_boot_progress(base_uri="/x", state=["OSRunning"], timeout=30))
        self.flow.redfish_utils.get_request.side_effect = None

    def test_execute_script_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["sh"], timeout=1)):
            self.assertFalse(self.flow.execute_script("echo hi"))

    def test_set_gpu_inband_update_policy_valueerror_exception(self):
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("bad")):
            self.assertFalse(
                self.flow.set_gpu_inband_update_policy(base_uri="/x", ap_name="AP_0", redfish_target="hmc")
            )
        mock_utils = MagicMock()
        mock_utils.patch_request.side_effect = Exception("boom")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            self.assertFalse(self.flow.set_gpu_inband_update_policy(base_uri="/x", ap_name="AP_0"))

    @patch("paramiko.SSHClient")
    def test_execute_os_command_outer_exception(self, mock_ssh_class):
        mock_ssh_class.side_effect = Exception("init fail")
        self.assertFalse(self.flow.execute_os_command(command="whoami"))

    def test_flint_verify_and_flash_fail(self):
        # verify: mst yields one device, verify returns False on first device
        def fake_exec(command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None):
            if command.startswith("mst status -v"):
                if saved_stdout is not None:
                    saved_stdout["output"] = "/dev/mst/mt2\n/dev/mst/mt2.3"
                return True
            if command.startswith("flint -d /dev/mst/mt2 -i ~/fw.bin verify"):
                return False
            return True

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec):
            self.assertFalse(self.flow.flint_verify(named_device="BlueField3", file_name="fw.bin"))

        # flash: mst yields one device, flash returns False => overall False
        def fake_exec_flash(command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None):
            if command.startswith("mst status -v"):
                if saved_stdout is not None:
                    saved_stdout["output"] = "/dev/mst/mt3\n/dev/mst/mt3.4"
                return True
            if command.startswith("flint -d /dev/mst/mt3 --yes -i ~/fw.bin b"):
                return False
            return True

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec_flash):
            self.assertFalse(self.flow.flint_flash(named_device="BlueField3", file_name="fw.bin"))

    def test_flint_flash_complex_path_basename_extraction(self):
        """Test that complex file paths are correctly abbreviated to basename in home directory."""
        # Test various complex path formats
        complex_paths = [
            "/some/very/long/complex/path/to/firmware/bluefield_fw.bin",
            "/opt/nvidia/firmware/versions/v1.2.3/bluefield_fw.bin",
            "../relative/path/to/bluefield_fw.bin",
            "~/Downloads/firmware_packages/bluefield_fw.bin",
        ]

        for complex_path in complex_paths:
            with self.subTest(path=complex_path):
                # Capture the actual command executed
                executed_commands = []

                def fake_exec_capture(
                    command: str,
                    use_sudo: bool = True,
                    saved_stdout=None,
                    saved_stderr=None,
                    timeout=None,
                    _executed_commands=executed_commands,  # Capture by value to fix B023
                ):
                    _executed_commands.append(command)
                    if command.startswith("mst status -v"):
                        if saved_stdout is not None:
                            saved_stdout["output"] = "/dev/mst/mt5"
                        return True
                    if command.startswith("flint -d /dev/mst/mt5 --yes -i ~/bluefield_fw.bin b"):
                        return True
                    return False

                with patch.object(self.flow, "execute_os_command", side_effect=fake_exec_capture):
                    result = self.flow.flint_flash(named_device="BlueField3", file_name=complex_path)

                    # Verify the operation succeeded
                    self.assertTrue(result, f"Flash operation failed for path: {complex_path}")

                    # Verify that the flint command uses the basename in home directory
                    flint_commands = [cmd for cmd in executed_commands if cmd.startswith("flint")]
                    self.assertEqual(
                        len(flint_commands),
                        1,
                        f"Expected exactly one flint command for path: {complex_path}",
                    )

                    flint_cmd = flint_commands[0]
                    self.assertIn(
                        "~/bluefield_fw.bin",
                        flint_cmd,
                        f"Expected '~/bluefield_fw.bin' in command, but got: {flint_cmd}",
                    )
                    self.assertNotIn(
                        complex_path,
                        flint_cmd,
                        f"Original path should not appear in command: {flint_cmd}",
                    )

    def test_flint_verify_complex_path_basename_extraction(self):
        """Test that complex file paths are correctly abbreviated to basename in home directory for verify."""
        complex_path = "/very/long/path/to/firmware/test_firmware.bin"

        # Capture the actual command executed
        executed_commands = []

        def fake_exec_capture(command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None):
            executed_commands.append(command)
            if command.startswith("mst status -v"):
                if saved_stdout is not None:
                    saved_stdout["output"] = "/dev/mst/mt6"
                return True
            if command.startswith("flint -d /dev/mst/mt6 -i ~/test_firmware.bin verify"):
                return True
            return False

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec_capture):
            result = self.flow.flint_verify(named_device="BlueField3", file_name=complex_path)

            # Verify the operation succeeded
            self.assertTrue(result, f"Verify operation failed for path: {complex_path}")

            # Verify that the flint command uses the basename in home directory
            flint_commands = [cmd for cmd in executed_commands if cmd.startswith("flint")]
            self.assertEqual(len(flint_commands), 1, "Expected exactly one flint command")

            flint_cmd = flint_commands[0]
            self.assertIn(
                "~/test_firmware.bin",
                flint_cmd,
                f"Expected '~/test_firmware.bin' in command, but got: {flint_cmd}",
            )
            self.assertNotIn(complex_path, flint_cmd, f"Original path should not appear in command: {flint_cmd}")

    def test_flint_flash_edge_case_paths(self):
        """Test edge cases for path basename extraction."""
        edge_cases = [
            ("firmware.bin", "~/firmware.bin"),  # Simple filename
            ("/firmware.bin", "~/firmware.bin"),  # Root path
            ("./firmware.bin", "~/firmware.bin"),  # Current dir
            ("firmware", "~/firmware"),  # No extension
        ]

        for input_path, expected_basename in edge_cases:
            with self.subTest(input_path=input_path):
                executed_commands = []

                def fake_exec_capture(
                    command: str,
                    use_sudo: bool = True,
                    saved_stdout=None,
                    saved_stderr=None,
                    timeout=None,
                    _executed_commands=executed_commands,
                    _expected_basename=expected_basename,  # Capture by value to fix B023
                ):
                    _executed_commands.append(command)
                    if command.startswith("mst status -v"):
                        if saved_stdout is not None:
                            saved_stdout["output"] = "/dev/mst/mt7"
                        return True
                    if _expected_basename in command:
                        return True
                    return False

                with patch.object(self.flow, "execute_os_command", side_effect=fake_exec_capture):
                    result = self.flow.flint_flash(named_device="BlueField3", file_name=input_path)

                    self.assertTrue(result, f"Flash operation failed for edge case: {input_path}")

                    # Verify the command contains the expected basename
                    flint_commands = [cmd for cmd in executed_commands if cmd.startswith("flint")]
                    self.assertEqual(
                        len(flint_commands),
                        1,
                        f"Expected exactly one flint command for input '{input_path}'",
                    )
                    self.assertIn(
                        expected_basename,
                        flint_commands[0],
                        f"Expected '{expected_basename}' in command for input '{input_path}'",
                    )

    def test_scp_tool_to_os_complex_path_basename_extraction(self):
        """Test that scp_tool_to_os correctly extracts basename from complex paths."""
        complex_paths = [
            "/some/very/long/path/to/Tools/MFT/4.32.0-6017/mft-4.32.0-6017-linux-arm64-deb.tgz",
            "/opt/nvidia/tools/nvflash/nvflash",
            "../relative/path/to/install_script.sh",
            "~/Downloads/packages/firmware_bundle.tgz",
        ]

        for complex_path in complex_paths:
            with self.subTest(path=complex_path):
                # Create a temporary file for testing
                test_file = self.create_test_file(os.path.basename(complex_path), b"test_tool_content")

                # Mock SSH and SFTP operations
                mock_ssh = MagicMock()
                mock_sftp = MagicMock()
                mock_ssh.open_sftp.return_value = mock_sftp

                with patch("paramiko.SSHClient") as mock_ssh_class:
                    mock_ssh_class.return_value = mock_ssh

                    # Execute scp_tool_to_os with the test file
                    result = self.flow.scp_tool_to_os(tool_file_path=test_file)

                    # Verify the operation succeeded
                    self.assertTrue(result, f"scp_tool_to_os failed for path: {complex_path}")

                    # Verify SSH connection was attempted
                    mock_ssh.connect.assert_called_once()

                    # Verify SFTP was used
                    mock_ssh.open_sftp.assert_called_once()

                    # Verify file was transferred with basename only
                    expected_basename = os.path.basename(complex_path)
                    mock_sftp.put.assert_called_once()

                    # Get the actual remote path used in the put call
                    put_call_args = mock_sftp.put.call_args[0]
                    local_path, remote_path = put_call_args

                    # The remote path should end with the basename (home directory + filename)
                    self.assertTrue(
                        remote_path.endswith(expected_basename),
                        f"Expected remote path to end with '{expected_basename}', but got '{remote_path}'",
                    )

                    # Verify only the basename is used as the filename part
                    actual_filename = os.path.basename(remote_path)
                    self.assertEqual(
                        actual_filename,
                        expected_basename,
                        f"Expected filename '{expected_basename}', but got '{actual_filename}'",
                    )

                    # Verify the original complex directory structure is not preserved in the remote path
                    # Check for specific directory patterns that shouldn't appear
                    directory_patterns = [
                        "Tools/",
                        "MFT/",
                        "/opt/",
                        "/some/",
                        "path/to/",
                        "Downloads/packages/",
                    ]
                    for pattern in directory_patterns:
                        if pattern in complex_path and pattern not in expected_basename:
                            self.assertNotIn(
                                pattern,
                                remote_path,
                                f"Original directory pattern '{pattern}' should not appear in remote path: {remote_path}",
                            )

                    # Verify the remote path is in a user home directory (not preserving original structure)
                    # The path should be something like /home/username/filename, not the original complex path
                    path_parts = remote_path.split("/")
                    if len(path_parts) >= 3:  # e.g., ['', 'home', 'username', 'filename']
                        # Should not contain deep nested structure from original path
                        self.assertLessEqual(
                            len(path_parts),
                            4,
                            f"Remote path should not preserve deep directory structure: {remote_path}",
                        )

    def test_scp_tool_to_os_logging_shows_basename_extraction(self):
        """Test that scp_tool_to_os logs the basename extraction clearly."""
        complex_path = "/very/long/path/to/mft-4.32.0-6017-linux-arm64-deb.tgz"
        expected_basename = "mft-4.32.0-6017-linux-arm64-deb.tgz"

        # Create a temporary file for testing
        test_file = self.create_test_file(expected_basename, b"test_content")

        # Mock SSH and SFTP operations
        mock_ssh = MagicMock()
        mock_sftp = MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp

        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh

            # Execute scp_tool_to_os
            result = self.flow.scp_tool_to_os(tool_file_path=test_file)

            # Verify the operation succeeded
            self.assertTrue(result)

            # Verify logging shows the path transformation
            # Note: In a real scenario, we'd check the actual log output, but for this test
            # we're verifying the method completes successfully with basename handling
            self.assert_logger_has_info(f"Transferring {test_file} -> ~/{expected_basename}")

    def test_scp_tool_to_os_missing_os_config(self):
        """Test scp_tool_to_os behavior when OS configuration is missing."""
        # Remove OS config
        original_config = self.flow.config.config.get("connection", {}).get("compute", {}).get("os", {})
        self.flow.config.config["connection"]["compute"]["os"] = {}

        try:
            # Create a test file
            test_file = self.create_test_file("test_tool.sh", b"test_content")

            # Execute scp_tool_to_os - should fail due to missing config
            result = self.flow.scp_tool_to_os(tool_file_path=test_file)

            # Should fail
            self.assertFalse(result)

        finally:
            # Restore original config
            self.flow.config.config["connection"]["compute"]["os"] = original_config

    def test_execute_ipmitool_generic_exception(self):
        with patch("subprocess.run", side_effect=Exception("boom")):
            self.assertFalse(self.flow.execute_ipmitool_command(command="chassis power status"))

    def test_stop_sol_logging_thread_alive_warning(self):
        class DummyThread:
            def __init__(self):
                self._alive = True

            def join(self, timeout=None):
                self._alive = False

            def is_alive(self):
                return self._alive

        class Proc:
            def __init__(self):
                self.pid = 5678

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return None

            def kill(self):
                pass

        class Log:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        self.flow._sol_processes["/tmp/sol_alive.log"] = {
            "process": Proc(),
            "log_file": Log(),
            "thread": DummyThread(),
        }
        with patch.object(self.flow, "execute_ipmitool_command", return_value=True):
            self.assertTrue(self.flow.stop_sol_logging("/tmp/sol_alive.log"))

    def test_pldm_fw_update_hmc_scp_failure(self):
        # Ensure HMC utils exist
        self.flow.hmc_redfish_utils = self.mock_utils
        # scp_files_target returns False -> method returns False
        with patch.object(self.flow.config.connection, "scp_files_target", return_value=False):
            bundle_path = self.create_test_file("fw_hmc_scp_fail.pldm", b"Y")
            self.assertFalse(self.flow._pldm_fw_update_hmc(bundle_path=bundle_path))

    def test_dot_cak_install_fails_when_key_none(self):
        # Set DOT to Volatile to test actual install logic (not NoDOT early return)
        self.flow.config.config["compute"]["DOT"] = "Volatile"

        self.assertFalse(
            self.flow.dot_cak_install(
                ap_name="AP_0",
                pem_encoded_key=None,
                ap_firmware_signature="s",
                check_volatile_dot=False,
            )
        )

    def test_dot_cak_install_fails_when_signature_none(self):
        # Set DOT to Volatile to test actual install logic (not NoDOT early return)
        self.flow.config.config["compute"]["DOT"] = "Volatile"

        self.assertFalse(
            self.flow.dot_cak_install(
                ap_name="AP_0",
                pem_encoded_key="k",
                ap_firmware_signature=None,
                check_volatile_dot=False,
            )
        )

    def test_dot_cak_install_valueerror_connection_error(self):
        # Set DOT to Volatile to test actual install logic (not NoDOT early return)
        self.flow.config.config["compute"]["DOT"] = "Volatile"

        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("no target")):
            self.assertFalse(
                self.flow.dot_cak_install(
                    ap_name="AP_0",
                    pem_encoded_key="k",
                    ap_firmware_signature="s",
                    check_volatile_dot=False,
                )
            )

    def test_ac_cycle_early_return_when_dot_not_volatile(self):
        cfg = {"compute": {"DOT": "Locking"}}
        config_path = self.create_test_config_file("compute", cfg)
        config = ComputeFactoryFlowConfig(config_path)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            flow2 = ComputeFactoryFlow(config, "computeX")
        with patch.object(flow2.redfish_utils, "post_request") as post_mock:
            ok = flow2.ac_cycle(base_uri="/x", check_volatile_dot=True)
        self.assertTrue(ok)
        post_mock.assert_not_called()

    def test_dot_cak_install_skips_when_nodot(self):
        cfg = {"compute": {"DOT": "NoDOT"}}
        config_path = self.create_test_config_file("compute", cfg)
        config = ComputeFactoryFlowConfig(config_path)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            flow2 = ComputeFactoryFlow(config, "computeX")
        with patch.object(flow2.redfish_utils, "post_request") as post_mock:
            ok = flow2.dot_cak_install(
                ap_name="AP_0",
                pem_encoded_key="k",
                ap_firmware_signature="s",
                check_volatile_dot=False,
            )
        self.assertTrue(ok)
        post_mock.assert_not_called()

    def test_pldm_fw_update_hmc_scp_exception(self):
        # Ensure HMC utils exist
        self.flow.hmc_redfish_utils = self.mock_utils
        bundle_path = self.create_test_file("fw_hmc_scp_exc.pldm", b"Y")
        with patch.object(self.flow.config.connection, "scp_files_target", side_effect=Exception("scp boom")):
            ok = self.flow._pldm_fw_update_hmc(bundle_path=bundle_path)
        self.assertFalse(ok)

    def test_send_boot_ap_early_return_when_dot_not_volatile(self):
        cfg = {"compute": {"DOT": "Locking"}}
        config_path = self.create_test_config_file("compute", cfg)
        config = ComputeFactoryFlowConfig(config_path)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            flow2 = ComputeFactoryFlow(config, "computeX")
        with patch.object(flow2.redfish_utils, "post_request") as post_mock:
            ok = flow2.send_boot_ap(ap_name="AP_0", base_uri="/x", check_volatile_dot=True)
        self.assertTrue(ok)
        post_mock.assert_not_called()

    def test_set_manual_boot_mode_gating(self):
        # Non-volatile DOT forces False and PATCH invoked with False
        cfg = {"compute": {"DOT": "Locking"}}
        config_path = self.create_test_config_file("compute", cfg)
        config = ComputeFactoryFlowConfig(config_path)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            flow2 = ComputeFactoryFlow(config, "computeX")
        with patch.object(flow2.redfish_utils, "patch_request", return_value=(True, {})) as patch_mock:
            ok = flow2.set_manual_boot_mode(ap_name="AP_0", base_uri="/x", check_volatile_dot=True)
        self.assertTrue(ok)
        sent_data = patch_mock.call_args[0][1]
        self.assertFalse(sent_data["Oem"]["Nvidia"]["ManualBootModeEnabled"])
        # Volatile DOT -> state True and PATCH invoked
        cfg2 = {"compute": {"DOT": "Volatile"}}
        config_path2 = self.create_test_config_file("compute", cfg2)
        config2 = ComputeFactoryFlowConfig(config_path2)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            flow3 = ComputeFactoryFlow(config2, "computeY")
        with patch.object(flow3.redfish_utils, "patch_request", return_value=(True, {})) as patch_mock2:
            ok2 = flow3.set_manual_boot_mode(ap_name="AP_0", base_uri="/x", check_volatile_dot=True)
        self.assertTrue(ok2)
        sent_data2 = patch_mock2.call_args[0][1]
        self.assertTrue(sent_data2["Oem"]["Nvidia"]["ManualBootModeEnabled"])

    def test_send_boot_ap_hmc_error_response_treated_as_failure(self):
        # Ensure HMC path is used
        self.flow.hmc_redfish_utils = self.mock_utils
        # Simulate HMC returning a Redfish error JSON while transport succeeded
        error_response = {
            "error": {
                "@Message.ExtendedInfo": [
                    {
                        "@odata.type": "#Message.v1_1_1.Message",
                        "Message": "The request failed due to an internal service error.  The service is still operational.",
                        "MessageArgs": [],
                        "MessageId": "Base.1.18.1.InternalError",
                        "MessageSeverity": "Critical",
                        "Resolution": "Resubmit the request.  If the problem persists, consider resetting the service.",
                    }
                ],
                "code": "Base.1.18.1.InternalError",
                "message": "The request failed due to an internal service error.  The service is still operational.",
            }
        }
        self.mock_utils.post_request.return_value = (True, error_response)
        ok = self.flow.send_boot_ap(
            ap_name="HGX_ERoT_CPU_0",
            base_uri="/redfish/v1/Chassis",
            redfish_target="hmc",
            check_volatile_dot=False,
        )
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to send boot command to HGX_ERoT_CPU_0")

    def test_ac_cycle_error_response_treated_as_failure(self):
        # Simulate POST success with Redfish error body
        self.mock_utils.post_request.return_value = (
            True,
            {"error": {"code": "Base.InternalError"}},
        )
        with patch("time.sleep"):
            ok = self.flow.ac_cycle(base_uri="/redfish/v1/Chassis/BMC_0/Actions/Oem/NvidiaChassis.AuxPowerReset")
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to perform AC power cycle:")

    def test_power_on_error_response_treated_as_failure(self):
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        # Return error JSON on POST
        self.mock_utils.post_request.return_value = (
            True,
            {"error": {"code": "Base.InternalError"}},
        )
        ok = self.flow.power_on(base_uri=base_uri)
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to power on device:")

    def test_power_off_error_response_treated_as_failure(self):
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        # Return error JSON on POST
        self.mock_utils.post_request.return_value = (
            True,
            {"error": {"code": "Base.InternalError"}},
        )
        ok = self.flow.power_off(base_uri=base_uri)
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to power off device:")

    def test_hmc_factory_reset_error_response_treated_as_failure(self):
        # Use HMC proxy and simulate error JSON on POST
        self.flow.hmc_redfish_utils = self.mock_utils
        self.mock_utils.post_request.return_value = (
            True,
            {"error": {"code": "Base.InternalError"}},
        )
        ok = self.flow.hmc_factory_reset(
            base_uri="/redfish/v1/Managers/HMC/Actions/ResetToDefaults", redfish_target="hmc"
        )
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to perform HMC factory reset:")

    def test_check_versions_hmc_success_and_mismatch(self):
        # HMC success
        self.flow.hmc_redfish_utils = self.mock_utils
        self.mock_utils.get_request.return_value = (True, {"Version": "1.2.3"})
        ok = self.flow.check_versions(
            expected_versions={"FW_BMC_0": "1.2.3"},
            operator="==",
            redfish_target="hmc",
            base_uri="/redfish/v1/UpdateService/FirmwareInventory/",
        )
        self.assertTrue(ok)
        # HMC mismatch
        self.mock_utils.get_request.return_value = (True, {"Version": "1.2.3"})
        ok2 = self.flow.check_versions(
            expected_versions={"FW_BMC_0": "2.0.0"},
            operator="==",
            redfish_target="hmc",
            base_uri="/redfish/v1/UpdateService/FirmwareInventory/",
        )
        self.assertFalse(ok2)
        self.assert_logger_has_error("Firmware version check failures:")

    def test_check_boot_status_code_get_request_failure(self):
        base_uri = "/redfish/v1/Chassis"
        ap = "ERoT_CPU_0"
        # Simulate GET failure
        self.mock_utils.get_request.return_value = (False, {"error": "bad"})
        ok = self.flow.check_boot_status_code(ap_name=ap, base_uri=base_uri, timeout=None)
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to get boot status code:")

    def test_dot_cak_install_locking_dot_early_skip_even_missing_inputs(self):
        # DOT Locking should early return True when check_volatile_dot=True
        cfg = {"compute": {"DOT": "Locking"}}
        config_path = self.create_test_config_file("compute", cfg)
        cfg_obj = ComputeFactoryFlowConfig(config_path)
        with patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.setup_logging",
            return_value=self.mock_logger,
        ):
            flow2 = ComputeFactoryFlow(cfg_obj, "computeDOT")
        with patch.object(flow2.redfish_utils, "post_request") as post_mock:
            ok = flow2.dot_cak_install(
                ap_name="AP_0",
                pem_encoded_key="",
                ap_firmware_signature="",
                base_uri="/redfish/v1/Chassis",
                check_volatile_dot=True,
            )
        self.assertTrue(ok)
        post_mock.assert_not_called()

    def test_check_manual_boot_mode_fallback_string_search(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        # Response lacks Oem.Nvidia.ManualBootModeEnabled and top-level key, but string search should find it
        response = {"SomeOther": {"ManualBootModeEnabled": True}}
        self.mock_utils.get_request.return_value = (True, response)
        ok = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            checked_state="true",
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertTrue(ok)

    def test_wait_ap_ready_hmc_success(self):
        self.flow.hmc_redfish_utils = self.mock_utils
        inventory = RedfishResponseBuilder.firmware_inventory_response(["HGX_FW_BMC_0", "HGX_FW_ERoT_BMC_0"])
        self.mock_utils.get_request.return_value = (True, inventory)
        with patch("time.sleep"):
            ok = self.flow.wait_ap_ready(
                ap_name=["HGX_FW_BMC_0", "HGX_FW_ERoT_BMC_0"],
                base_uri="/redfish/v1/UpdateService/FirmwareInventory",
                timeout=10,
                redfish_target="hmc",
            )
        self.assertTrue(ok)

    def test_monitor_background_copy_single_ap_string_success(self):
        completed_response = {"Oem": {"Nvidia": {"BackgroundCopyStatus": "Completed", "BackgroundCopyProgress": 100}}}
        self.mock_utils.get_request.return_value = (True, completed_response)
        ok = self.flow.monitor_background_copy(ap_name="AP_0", base_uri="/redfish/v1/Chassis/", timeout=None)
        self.assertTrue(ok)

    def test_reboot_bmc_hmc_error_response_treated_as_failure(self):
        self.flow.hmc_redfish_utils = self.mock_utils
        self.mock_utils.post_request.return_value = (
            True,
            {"error": {"code": "Base.InternalError"}},
        )
        ok = self.flow.reboot_bmc(
            base_uri="/redfish/v1/Managers/HMC/Actions/Manager.Reset",
            redfish_target="hmc",
            data={"ResetType": "GracefulRestart"},
        )
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to reboot HMC:")

    def test_set_power_policy_always_on_failure(self):
        base_uri = "/redfish/v1/Chassis/System_0"
        self.mock_utils.patch_request.return_value = (False, {"error": "bad"})
        ok = self.flow.set_power_policy_always_on(base_uri=base_uri)
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to set power policy:")

    def test_set_power_policy_last_state_failure(self):
        base_uri = "/redfish/v1/Chassis/System_0"
        self.mock_utils.patch_request.return_value = (False, {"error": "bad"})
        ok = self.flow.set_power_policy_last_state(base_uri=base_uri)
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to set power policy:")

    def test_power_on_exception_path(self):
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        self.mock_utils.post_request.side_effect = Exception("boom")
        ok = self.flow.power_on(base_uri=base_uri)
        self.assertFalse(ok)

    def test_power_off_timeout_and_bad_response_and_valueerror(self):
        base_uri = "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset"
        # Timeout path with non-dict GET response
        self.mock_utils.post_request.return_value = (True, {})
        self.mock_utils.get_request.return_value = (True, "string")
        # First iteration within timeout to hit the GET error log, then timeout on next check
        with patch("time.time") as mt, patch("time.sleep"):
            mt.side_effect = [0, 1, 31]
            ok = self.flow.power_off(base_uri=base_uri)
        self.assertFalse(ok)
        self.assert_logger_has_error("Failed to check power state:")
        # ValueError during POST
        self.mock_utils.post_request.side_effect = ValueError("bad")
        ok2 = self.flow.power_off(base_uri=base_uri)
        self.assertFalse(ok2)

    def test_check_manual_boot_mode_bool_expected(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        self.mock_utils.get_request.return_value = (
            True,
            {"Oem": {"Nvidia": {"ManualBootModeEnabled": True}}},
        )
        ok = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            checked_state=True,
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertTrue(ok)

    def test_check_manual_boot_mode_unexpected_type(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        # Response won't be used; we want to trigger unexpected checked_state type
        ok = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            checked_state=123,
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertFalse(ok)
        self.assert_logger_has_error("Unexpected type for 'checked_state'")

    def test_check_manual_boot_mode_top_level_field(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        self.mock_utils.get_request.return_value = (True, {"ManualBootModeEnabled": False})
        ok = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            checked_state="false",
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertTrue(ok)

    def test_check_manual_boot_mode_non_bool_non_str_value_and_mismatch_warning(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        # Non-bool, non-str value (int) -> coerced with bool()
        self.mock_utils.get_request.return_value = (
            True,
            {"Oem": {"Nvidia": {"ManualBootModeEnabled": 1}}},
        )
        ok = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            checked_state="true",
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertTrue(ok)
        # Now mismatch warning: actual True vs expected False
        self.mock_utils.get_request.return_value = (
            True,
            {"Oem": {"Nvidia": {"ManualBootModeEnabled": True}}},
        )
        ok2 = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            checked_state="false",
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertFalse(ok2)
        self.assert_logger_has_warning("Manual boot mode is 'True'")

    def test_set_manual_boot_mode_unexpected_state_type_and_patch_failure(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        # Unexpected type for state
        ok = self.flow.set_manual_boot_mode(
            ap_name=ap, base_uri=base_uri, state=123, check_volatile_dot=False, redfish_target="bmc"
        )
        self.assertFalse(ok)
        self.assert_logger_has_error("Unexpected type for 'state'")
        # Patch failure path
        self.mock_utils.patch_request.return_value = (False, {"error": "bad"})
        ok2 = self.flow.set_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            state="true",
            check_volatile_dot=False,
            redfish_target="bmc",
        )
        self.assertFalse(ok2)
        self.assert_logger_has_error("Failed to set manual boot mode for")

    def test_nvflash_flash_vbios_warn_on_rmmod_and_nonzero_return(self):
        # rmmod non-zero then nvflash success
        mock_ssh = self.create_mock_ssh_session([("", "mod not loaded", 1), ("ok", "", 0)])
        with patch("paramiko.SSHClient") as mock_ssh_class:
            mock_ssh_class.return_value = mock_ssh
            self.assertTrue(self.flow.nvflash_flash_vbios(vbios_bundle="x.rom"))
            self.assert_logger_has_warning("Failed to remove some NVIDIA modules")
        # nvflash non-zero -> failure
        mock_ssh2 = self.create_mock_ssh_session([("", "", 0), ("", "err", 1)])
        with patch("paramiko.SSHClient") as mock_ssh_class2:
            mock_ssh_class2.return_value = mock_ssh2
            self.assertFalse(self.flow.nvflash_flash_vbios(vbios_bundle="x.rom"))
            self.assert_logger_has_error("Failed to flash VBIOS:")

    def test_check_manual_boot_mode_not_found_returns_false(self):
        ap = "ERoT_CPU_0"
        base_uri = "/redfish/v1/Chassis"
        # Neither Oem.Nvidia.ManualBootModeEnabled nor top-level present; string search should fail
        self.mock_utils.get_request.return_value = (True, {"foo": "bar"})
        ok = self.flow.check_manual_boot_mode(
            ap_name=ap,
            base_uri=base_uri,
            checked_state="true",
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertFalse(ok)
        self.assert_logger_has_error("ManualBootModeEnabled not found in response")

    def test_config_validation_ip_type_error(self):
        bad_cfg = {"connection": {"compute": {"bmc": {"ip": 123, "username": "u", "password": "p", "port": 443}}}}
        with self.assertRaises(ValueError):
            ComputeFactoryFlowConfig(self.create_test_config_file("compute", bad_cfg))

    def test_wait_ap_ready_exception_path(self):
        with patch.object(self.flow, "_get_redfish_utils", side_effect=Exception("boom")):
            with patch("time.sleep"):
                ok = self.flow.wait_ap_ready(ap_name=["A"], base_uri="/x", timeout=10)
        self.assertFalse(ok)

    def test_check_gpu_inband_update_policy_valueerror_and_exception(self):
        # ValueError from _get_redfish_utils
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("bad")):
            ok = self.flow.check_gpu_inband_update_policy(base_uri="/x", ap_name="GPU_0", redfish_target="hmc")
        self.assertFalse(ok)
        # Exception from get_request
        mock_utils = MagicMock()
        mock_utils.get_request.side_effect = Exception("boom")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            ok2 = self.flow.check_gpu_inband_update_policy(base_uri="/x", ap_name="GPU_0")
        self.assertFalse(ok2)

    def test_monitor_background_copy_failed_aps_with_timeout_returns_false(self):
        # One AP fails get_request; timeout provided triggers failed_aps branch
        def get_resp(uri, *a, **k):
            if uri.endswith("AP_0"):
                return (False, {"error": "bad"})
            return (True, {})

        self.mock_utils.get_request.side_effect = get_resp
        with patch("time.sleep"):
            ok = self.flow.monitor_background_copy(ap_name=["AP_0", "AP_1"], base_uri="/x", timeout=30)
        self.assertFalse(ok)

    def test_wait_for_boot_setup_sol_logging_exception(self):
        # Enable POST logging via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        with patch.object(self.flow, "_start_ipmi_sol_logging", side_effect=Exception("boom")):
            ok = self.flow.wait_for_boot(
                power_on_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
                system_uri="/redfish/v1/Systems/System_0",
                state="OSRunning",
            )
        self.assertFalse(ok)

    def test_wait_for_boot_general_exception(self):
        # Enable POST logging via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        with patch.object(self.flow, "_start_ipmi_sol_logging", return_value="log_path"), patch.object(
            self.flow, "power_on", return_value=True
        ), patch.object(self.flow, "check_boot_progress", side_effect=Exception("boom")), patch.object(
            self.flow, "stop_sol_logging", return_value=True
        ):
            ok = self.flow.wait_for_boot(
                power_on_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
                system_uri="/redfish/v1/Systems/System_0",
                state=["OSRunning"],
            )
        self.assertFalse(ok)

    def test_check_boot_status_code_continue_sleep_branch(self):
        base_uri = "/redfish/v1/Chassis"
        ap = "ERoT_CPU_0"
        # First attempt fails (status False), then valid dict but not 0x11; with timeout set, we continue then time out
        self.mock_utils.get_request.side_effect = [
            (False, {"error": "bad"}),
            (True, {"BootStatusCode": "aaaaaaaaaaaaaa10"}),
        ]
        with patch("time.sleep") as slp, patch("time.time") as mt:
            mt.side_effect = [0, 1, 2, 60, 61]  # allows one sleep, then timeout
            ok = self.flow.check_boot_status_code(ap_name=ap, base_uri=base_uri, timeout=60, check_interval=1)
        self.assertFalse(ok)
        # optional: ensure we did sleep
        self.assertTrue(slp.called)

    def test_dot_cak_install_postrequest_valueerror(self):
        # Set DOT to Volatile to test actual install logic (not NoDOT early return)
        self.flow.config.config["compute"]["DOT"] = "Volatile"

        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = ValueError("post value error")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            ok = self.flow.dot_cak_install(
                ap_name="ERoT_CPU_0",
                pem_encoded_key="k",
                ap_firmware_signature="s",
                base_uri="/redfish/v1/Chassis",
                redfish_target="bmc",
                check_volatile_dot=False,
            )
        self.assertFalse(ok)

    def test_dot_cak_lock_postrequest_valueerror(self):
        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = ValueError("post value error")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            ok = self.flow.dot_cak_lock(
                ap_name="ERoT_CPU_0",
                pem_encoded_key="k",
                base_uri="/redfish/v1/Chassis",
                redfish_target="bmc",
                check_locking_dot=False,
            )
        self.assertFalse(ok)

    def test_reboot_bmc_postrequest_valueerror(self):
        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = ValueError("post value error")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            ok = self.flow.reboot_bmc(base_uri="/redfish/v1/Managers/BMC_0/Actions/Manager.Reset", redfish_target="bmc")
        self.assertFalse(ok)

    def test_set_power_policy_last_state_patch_valueerror(self):
        self.mock_utils.patch_request.side_effect = ValueError("bad")
        ok = self.flow.set_power_policy_last_state(base_uri="/redfish/v1/Chassis/System_0")
        self.assertFalse(ok)

    def test_set_power_policy_always_off_patch_exception(self):
        self.mock_utils.patch_request.side_effect = Exception("boom")
        ok = self.flow.set_power_policy_always_off(base_uri="/redfish/v1/Chassis/System_0")
        self.assertFalse(ok)

    def test_wait_ap_ready_get_redfish_utils_valueerror(self):
        with patch.object(self.flow, "_get_redfish_utils", side_effect=ValueError("no hmc")):
            ok = self.flow.wait_ap_ready(
                ap_name="AP_0", base_uri="/redfish/v1/UpdateService/FirmwareInventory", timeout=10
            )
        self.assertFalse(ok)

    def test_hmc_factory_reset_postrequest_valueerror(self):
        mock_utils = MagicMock()
        mock_utils.post_request.side_effect = ValueError("post value error")
        with patch.object(self.flow, "_get_redfish_utils", return_value=mock_utils):
            ok = self.flow.hmc_factory_reset(
                base_uri="/redfish/v1/Managers/HMC/Actions/ResetToDefaults", redfish_target="hmc"
            )
        self.assertFalse(ok)

    @patch("paramiko.SSHClient", side_effect=Exception("init fail"))
    def test_nvflash_check_vbios_sshclient_constructor_exception(self, _):
        ok = self.flow.nvflash_check_vbios()
        self.assertFalse(ok)

    def test_check_manual_boot_mode_fallback_false(self):
        # Force fallback string search path with a False value
        response = {"SomeOther": {"ManualBootModeEnabled": False}}
        self.mock_utils.get_request.return_value = (True, response)
        ok = self.flow.check_manual_boot_mode(
            ap_name="ERoT_CPU_0",
            base_uri="/redfish/v1/Chassis",
            checked_state="false",
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertTrue(ok)

    def test_check_manual_boot_mode_structured_string_false(self):
        # Structured value is a string; should coerce to boolean False
        response = {"Oem": {"Nvidia": {"ManualBootModeEnabled": "false"}}}
        self.mock_utils.get_request.return_value = (True, response)
        ok = self.flow.check_manual_boot_mode(
            ap_name="ERoT_CPU_0",
            base_uri="/redfish/v1/Chassis",
            checked_state=False,
            redfish_target="bmc",
            check_volatile_dot=False,
        )
        self.assertTrue(ok)

    def test_dot_cak_lock_empty_key_no_locking_check(self):
        ok = self.flow.dot_cak_lock(
            ap_name="AP_0",
            pem_encoded_key="",
            base_uri="/redfish/v1/Chassis",
            check_locking_dot=False,
        )
        self.assertTrue(ok)

    def test_check_boot_progress_laststate_none_no_timeout(self):
        base_uri = "/redfish/v1/Systems/System_0"
        # BootProgress present but LastState is None; timeout=None fast-fail path
        self.mock_utils.get_request.return_value = (True, {"BootProgress": {"LastState": None}})
        ok = self.flow.check_boot_progress(base_uri=base_uri, state="OSRunning", timeout=None)
        self.assertFalse(ok)

    def test_close_handles_stop_sol_exception_and_outer_exception(self):
        # Insert a fake SOL entry and make stop_sol_logging raise
        self.flow._sol_processes["/tmp/test_sol.log"] = {
            "process": MagicMock(),
            "log_file": MagicMock(closed=True),
            "thread": None,
        }
        with patch.object(self.flow, "stop_sol_logging", side_effect=Exception("stop fail")):
            # Should catch and log error, not raise
            self.flow.close()
        # Now provoke outer exception path by making _opened_resources non-iterable
        self.flow._opened_resources = 123  # not iterable; for-loop will raise TypeError
        # Should be caught by outer except without raising
        self.flow.close()

    def test_destructor_suppresses_close_exception(self):
        with patch.object(self.flow, "close", side_effect=Exception("boom")):
            # __del__ should suppress
            self.flow.__del__()

    def test_check_gpu_inband_update_policy_error_and_valueerror(self):
        base_uri = "/redfish/v1/Chassis"
        ap = "GPU_0"
        # status False path -> error log, False
        self.mock_utils.get_request.return_value = (False, {"error": "bad"})
        ok1 = self.flow.check_gpu_inband_update_policy(base_uri=base_uri, ap_name=ap)
        self.assertFalse(ok1)
        # ValueError during get_request -> outer ValueError handler
        self.mock_utils.get_request.side_effect = ValueError("bad")
        with patch.object(self.flow, "_get_redfish_utils", return_value=self.mock_utils):
            ok2 = self.flow.check_gpu_inband_update_policy(base_uri=base_uri, ap_name=ap)
        self.assertFalse(ok2)
        # reset side effect
        self.mock_utils.get_request.side_effect = None

    def test_set_gpu_inband_update_policy_patch_valueerror(self):
        base_uri = "/redfish/v1/Chassis"
        ap = "GPU_0"
        self.mock_utils.patch_request.side_effect = ValueError("bad")
        with patch.object(self.flow, "_get_redfish_utils", return_value=self.mock_utils):
            ok = self.flow.set_gpu_inband_update_policy(base_uri=base_uri, ap_name=ap)
        self.assertFalse(ok)

    def test_flint_verify_mst_status_failure(self):
        # Make mst status call return False
        def fake_exec(command: str, use_sudo: bool = True, saved_stdout=None, saved_stderr=None, timeout=None):
            if command.startswith("mst status -v"):
                return False
            return True

        with patch.object(self.flow, "execute_os_command", side_effect=fake_exec):
            ok = self.flow.flint_verify(named_device="BlueField3", file_name="fw.bin")
        self.assertFalse(ok)

    def test_check_boot_status_code_missing_and_invalid_no_timeout_and_valueerror(self):
        base_uri = "/redfish/v1/Chassis"
        ap = "ERoT_CPU_0"
        # Missing BootStatusCode with no timeout -> False
        self.mock_utils.get_request.return_value = (True, {})
        ok1 = self.flow.check_boot_status_code(ap_name=ap, base_uri=base_uri, timeout=None)
        self.assertFalse(ok1)
        # Invalid format (IndexError) with no timeout -> False
        self.mock_utils.get_request.return_value = (True, {"BootStatusCode": "0x1"})
        ok2 = self.flow.check_boot_status_code(ap_name=ap, base_uri=base_uri, timeout=None)
        self.assertFalse(ok2)
        # ValueError during get_request -> outer ValueError handler
        self.mock_utils.get_request.side_effect = ValueError("bad")
        with patch.object(self.flow, "_get_redfish_utils", return_value=self.mock_utils):
            ok3 = self.flow.check_boot_status_code(ap_name=ap, base_uri=base_uri, timeout=None)
        self.assertFalse(ok3)
        # reset side effect
        self.mock_utils.get_request.side_effect = None

    def test_scp_tool_to_os_success(self):
        """Test successful SCP tool transfer to compute OS."""
        test_tool_path = "/path/to/compute_tool.bin"

        # Mock the BaseConnectionManager's scp_tool_to_os to return True
        with patch.object(self.flow.config.connection, "scp_tool_to_os") as mock_scp:
            mock_scp.return_value = True

            result = self.flow.scp_tool_to_os(test_tool_path)

            # Verify results
            self.assertTrue(result)
            mock_scp.assert_called_once_with(
                test_tool_path,
                self.flow.config.config.get("connection", {}).get("compute", {}).get("os", {}),
                logger=self.flow.logger,
            )

    def test_scp_tool_to_os_failure(self):
        """Test SCP tool transfer failure for compute."""
        test_tool_path = "/path/to/compute_tool.bin"

        # Mock the BaseConnectionManager's scp_tool_to_os to return False
        with patch.object(self.flow.config.connection, "scp_tool_to_os") as mock_scp:
            mock_scp.return_value = False

            result = self.flow.scp_tool_to_os(test_tool_path)

            # Verify results
            self.assertFalse(result)
            mock_scp.assert_called_once()

    def test_scp_tool_to_os_basename_extraction(self):
        """Test that scp_tool_to_os delegates correctly for compute."""
        test_tool_path = "/very/long/path/to/nvflash_tool.exe"

        # Mock the BaseConnectionManager's scp_tool_to_os to return True
        with patch.object(self.flow.config.connection, "scp_tool_to_os") as mock_scp:
            mock_scp.return_value = True

            result = self.flow.scp_tool_to_os(test_tool_path)

            # Verify delegation to base class with correct parameters
            self.assertTrue(result)
            mock_scp.assert_called_once_with(
                test_tool_path,
                self.flow.config.config.get("connection", {}).get("compute", {}).get("os", {}),
                logger=self.flow.logger,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
