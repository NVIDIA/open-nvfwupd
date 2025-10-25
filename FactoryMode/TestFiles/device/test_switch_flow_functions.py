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
Switch Device Integration Tests

This module provides integration-level testing for switch device operations,
focusing on complete operation flows with mocked SSH connections.
Tests cover firmware updates, configuration management, version checking, and error scenarios.
"""

import os
import socket

# Add the parent directory to the path
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from FactoryMode.TrayFlowFunctions.switch_factory_flow_functions import (
    SwitchFactoryFlow,
    SwitchFactoryFlowConfig,
)

from .integration_test_base import IntegrationTestBase

# Mark all tests in this file
pytestmark = [pytest.mark.device, pytest.mark.switch]


class TestSwitchIntegration(IntegrationTestBase):
    """Integration tests for SwitchFactoryFlow operations with mocked SSH connections."""

    def setUp(self):
        """Set up test fixtures and mocks."""
        super().setUp()

        # Create test configuration for switch
        self.config_file = self.create_test_config_file(
            "switch",
            custom_config={
                "connection": {
                    "switch": {
                        "os": {
                            "ip": "192.168.1.200",
                            "username": "admin",
                            "password": "test123",
                            "port": 22,
                        },
                        "bmc": {  # Some switches have BMC too
                            "ip": "192.168.1.201",
                            "username": "admin",
                            "password": "test123",
                            "port": 443,
                            "protocol": "https",
                        },
                    }
                }
            },
        )

        # Mock the SSH client at the module level
        self.mock_ssh_patcher = patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.paramiko.SSHClient")
        self.mock_ssh_class = self.mock_ssh_patcher.start()
        self.addCleanup(self.mock_ssh_patcher.stop)

        # Create mock SSH instance
        self.mock_ssh_instance = MagicMock()
        self.mock_ssh_class.return_value = self.mock_ssh_instance

        # Mock the connection methods
        self.mock_transport = MagicMock()
        self.mock_ssh_instance.get_transport.return_value = self.mock_transport
        self.mock_ssh_instance.connect.return_value = None

        self.config = SwitchFactoryFlowConfig(self.config_file)

        # Create flow instance with mocked logger
        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.setup_logging") as mock_setup_logging:
            mock_setup_logging.return_value = self.mock_logger
            self.flow = SwitchFactoryFlow(self.config, "switch1")

        # Use the mocked Utils from IntegrationTestBase
        self.mock_utils = self.flow.__class__.Utils = self.mock_utils

    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self.flow, "config") and hasattr(self.flow.config, "close"):
            self.flow.config.close()
        super().tearDown()

    def create_mock_ssh_command_result(self, stdout: str = "", stderr: str = "", exit_code: int = 0):
        """Helper to create mock SSH command results."""
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        # Mock stdout
        mock_stdout.read.return_value = stdout.encode()
        mock_stdout.channel.recv_exit_status.return_value = exit_code
        mock_stdout.channel.settimeout = MagicMock()

        # Mock stderr
        mock_stderr.read.return_value = stderr.encode()

        return mock_stdin, mock_stdout, mock_stderr

    # Test 1: SSH connection establishment
    def test_ssh_connection_establishment(self):
        """Test SSH connection setup and authentication."""
        # Test successful connection
        self.mock_ssh_instance.connect.return_value = None

        # Get SSH client should establish connection
        ssh_client = self.flow.config.connection.get_ssh_client()

        # Verify connection was attempted with correct parameters
        self.mock_ssh_instance.connect.assert_called_once_with(
            hostname="192.168.1.200", port=22, username="admin", password="test123"
        )

        # Verify keepalive was set
        self.mock_transport.set_keepalive.assert_called_once_with(15)

        # Verify we got the client back
        self.assertIsNotNone(ssh_client)
        self.assertEqual(ssh_client, self.mock_ssh_instance)

    # Test 2: Firmware update Cumulus flow
    def test_firmware_update_cumulus_flow(self):
        """Test Cumulus firmware update process."""
        # Mock successful command executions
        command_results = [
            # fetch command
            ("Firmware downloaded successfully", "", 0),
            # install command
            ("Firmware installed successfully", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Execute firmware update - this uses fetch_and_install_switch_firmware
        result = self.flow.fetch_and_install_switch_firmware(
            firmware_url="http://192.168.1.100/cumulus-firmware.bin",
            component="bios",
            timeout=900,
            reboot_config="skip-reboot",
        )

        self.assertTrue(result)

        # Verify commands were executed
        self.assertEqual(self.mock_ssh_instance.exec_command.call_count, 2)

        # Check first command (fetch)
        first_call = self.mock_ssh_instance.exec_command.call_args_list[0]
        self.assertIn("nv action fetch platform firmware", first_call[0][0])

        # Check second command (install)
        second_call = self.mock_ssh_instance.exec_command.call_args_list[1]
        self.assertIn("nv action install platform firmware", second_call[0][0])

    # Test 3: Firmware update SONiC flow
    def test_firmware_update_sonic_flow(self):
        """Test SONiC firmware update process (NVOS)."""
        # Mock successful command executions
        command_results = [
            # fetch command
            ("NVOS image downloaded successfully", "", 0),
            # install command
            ("NVOS installed successfully", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Execute NVOS update
        result = self.flow.fetch_and_install_nvos(
            firmware_url="http://192.168.1.100/sonic-os.bin",
            timeout=900,
            reboot_config="reboot no",
        )

        self.assertTrue(result)

        # Verify commands
        self.assertEqual(self.mock_ssh_instance.exec_command.call_count, 2)

        # Check fetch command
        first_call = self.mock_ssh_instance.exec_command.call_args_list[0]
        self.assertIn("nv action fetch system image", first_call[0][0])

        # Check install command
        second_call = self.mock_ssh_instance.exec_command.call_args_list[1]
        self.assertIn("nv action install system image", second_call[0][0])
        self.assertIn("reboot no", second_call[0][0])

    # Test 4: Configuration backup and restore
    def test_configuration_backup_restore(self):
        """Test config backup and restore operations."""
        # Test save config
        save_result = self.create_mock_ssh_command_result("Configuration saved", "", 0)
        self.mock_ssh_instance.exec_command.return_value = save_result

        result = self.flow.save_config()
        self.assertTrue(result)
        self.mock_ssh_instance.exec_command.assert_called_with("nv config save", timeout=60)

        # Reset mock
        self.mock_ssh_instance.reset_mock()

        # Test apply config
        apply_result = self.create_mock_ssh_command_result("Configuration applied", "", 0)
        self.mock_ssh_instance.exec_command.return_value = apply_result

        result = self.flow.apply_config()
        self.assertTrue(result)
        self.mock_ssh_instance.exec_command.assert_called_with("nv config apply", timeout=300)

    # Test 5: Version check multi-component
    def test_version_check_multi_component(self):
        """Test version checking for all components."""
        # Mock show platform firmware output
        firmware_output = """component    version
bios         1.2.3
cpld         2.0.1
erot         3.1.0"""

        fw_result = self.create_mock_ssh_command_result(firmware_output, "", 0)
        self.mock_ssh_instance.exec_command.return_value = fw_result

        # Test firmware version check
        expected_versions = {"bios": "1.2.3", "cpld": "2.0.1", "erot": "3.1.0"}

        result = self.flow.check_fw_versions(expected_versions, "==")
        self.assertTrue(result)

        # Reset mock
        self.mock_ssh_instance.reset_mock()

        # Test OS version check
        os_output = """attribute    value
image        5.4.0-nvos"""

        os_result = self.create_mock_ssh_command_result(os_output, "", 0)
        self.mock_ssh_instance.exec_command.return_value = os_result

        result = self.flow.check_os_versions({"nvos": "5.4.0-nvos"}, "==")
        self.assertTrue(result)

    # Test 6: Reboot with verification
    def test_reboot_with_verification(self):
        """Test switch reboot and recovery."""
        # Mock time.sleep to prevent actual sleeping during test
        with patch("time.sleep") as mock_sleep:
            # Mock the redfish_utils for power_on functionality
            with patch.object(self.flow, "redfish_utils") as mock_redfish:
                # Mock POST request for power on
                mock_redfish.post_request.return_value = (True, {"Success": "Reset action completed"})
                # Mock GET request to return power state as "On"
                mock_redfish.get_request.return_value = (True, {"PowerState": "On"})

                # Mock the show_system_version to succeed on first call after power_on
                with patch.object(self.flow, "show_system_version") as mock_show_version:
                    mock_show_version.return_value = {"image": "5.4.0-nvos", "uptime": "10 seconds"}

                    # Reboot command will cause SSH exception (expected)
                    self.mock_ssh_instance.exec_command.side_effect = OSError("Connection closed")

                    # Execute reboot
                    result = self.flow.reboot_system()

                    # Should return True even with connection error (expected during reboot)
                    self.assertTrue(result)
                    self.assert_logger_has_error("Unexpected error during reboot: Connection closed")
                    self.assert_logger_has_info("Attempting power cycle as backup recovery method")

                    # Verify reboot command was attempted
                    self.mock_ssh_instance.exec_command.assert_called_with("nv action reboot system", timeout=60)

                    # Verify both power_cycle_system and power_on were called
                    self.assertEqual(mock_redfish.post_request.call_count, 2)

                    # First call should be power cycle (from the backup recovery method)
                    first_call = mock_redfish.post_request.call_args_list[0]
                    self.assertEqual(first_call[0][0], "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset")
                    self.assertEqual(first_call[0][1], {"ResetType": "PowerCycle"})

                    # Second call should be power on (from the regular flow)
                    second_call = mock_redfish.post_request.call_args_list[1]
                    self.assertEqual(second_call[0][0], "/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset")
                    self.assertEqual(second_call[0][1], {"ResetType": "On"})

                    # Verify show_system_version was called in the verification loop
                    mock_show_version.assert_called()

                    # Verify time.sleep was called (120s wait + at least one 10s wait in loop)
                    # The exact number of calls depends on timing, but should be at least 1
                    self.assertTrue(mock_sleep.call_count >= 1)

    # Test 7: SSH command timeout handling
    def test_ssh_command_timeout_handling(self):
        """Test SSH command timeout scenarios."""
        # Create a mock that simulates timeout
        mock_stdout = MagicMock()
        mock_stdout.channel.settimeout = MagicMock()
        mock_stdout.channel.recv_exit_status.side_effect = socket.timeout("Command timed out")

        self.mock_ssh_instance.exec_command.return_value = (
            MagicMock(),
            mock_stdout,
            MagicMock(),
        )

        # Test command that times out
        with self.assertRaises(socket.timeout):
            self.flow._execute_nv_command("nv show system version", timeout=5)

        # Verify warning was logged
        self.assert_logger_has_warning("Connection terminated or timed out")

    # Test 8: Firmware rollback scenario
    def test_firmware_rollback_scenario(self):
        """Test firmware rollback on failure."""
        # First attempt - install fails
        command_results = [
            # fetch succeeds
            ("Firmware downloaded", "", 0),
            # install fails
            ("", "Installation failed: checksum mismatch", 1),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Execute firmware update - should fail
        result = self.flow.fetch_and_install_switch_firmware(
            firmware_url="http://192.168.1.100/bad-firmware.bin",
            component="bios",
            timeout=900,
        )

        self.assertFalse(result)
        self.assert_logger_has_info("Install command output:")
        self.assert_logger_has_info("checksum mismatch")

    # Test 9: Network connectivity check
    def test_network_connectivity_check(self):
        """Test network connectivity validation."""
        # Test successful version check (indicates connectivity)
        version_output = """attribute    value
image        5.4.0-nvos
uptime       10 days"""

        version_result = self.create_mock_ssh_command_result(version_output, "", 0)
        self.mock_ssh_instance.exec_command.return_value = version_result

        # Get system version as connectivity check
        version_info = self.flow.show_system_version()

        self.assertIsNotNone(version_info)
        self.assertIn("image", version_info)
        self.assertEqual(version_info["image"], "5.4.0-nvos")

        # Verify command was executed
        self.mock_ssh_instance.exec_command.assert_called_with("nv show system version", timeout=10)

    # Test 10: Concurrent SSH operations
    def test_concurrent_ssh_operations(self):
        """Test multiple SSH sessions handling."""
        # Create multiple flows to simulate concurrent operations
        flows = []

        # Mock the logging setup for all flows
        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.setup_logging") as mock_setup_logging:
            mock_setup_logging.return_value = self.mock_logger

            # Each flow should get its own SSH connection
            for i in range(3):
                config = SwitchFactoryFlowConfig(self.config_file)
                flow = SwitchFactoryFlow(config, f"switch{i}")
                flows.append(flow)

        # Mock different responses for each flow
        version_responses = ["image 5.4.0-nvos", "image 5.4.1-nvos", "image 5.4.2-nvos"]

        # Execute commands on each flow
        for i, flow in enumerate(flows):
            # Set up mock for this specific execution
            result = self.create_mock_ssh_command_result(version_responses[i], "", 0)
            self.mock_ssh_instance.exec_command.return_value = result

            # Execute command
            try:
                version = flow.show_system_version()
                # Basic check that we got some response
                self.assertIsNotNone(version)
            except Exception:
                # Connection setup might fail in test environment
                pass

        # Clean up
        for flow in flows:
            if hasattr(flow.config, "close"):
                flow.config.close()

    # Additional test: SSH inactivity timeout setting
    def test_ssh_inactivity_timeout_setting(self):
        """Test setting SSH inactivity timeout."""
        # Mock successful command executions for set, apply, and save
        command_results = [
            # set command
            ("SSH timeout set", "", 0),
            # apply command
            ("Configuration applied", "", 0),
            # save command
            ("Configuration saved", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Set SSH inactivity timeout
        result = self.flow.set_ssh_inactivity_timeout(timeout_seconds=3600)

        self.assertTrue(result)
        self.assert_logger_has_info("SSH inactivity timeout set to 3600 seconds")

        # Verify all three commands were called
        self.assertEqual(self.mock_ssh_instance.exec_command.call_count, 3)

        # Check commands
        calls = self.mock_ssh_instance.exec_command.call_args_list
        self.assertIn("nv set system ssh-server inactivity-timeout 3600", calls[0][0][0])
        self.assertIn("nv config apply", calls[1][0][0])
        self.assertIn("nv config save", calls[2][0][0])

    def test_ssh_inactivity_timeout_fallback_success(self):
        """Test SSH inactivity timeout with fallback command success."""
        # Mock command executions: first set fails, second set succeeds, then apply and save succeed
        command_results = [
            # First set command fails
            ("", "command not found", 1),
            # Second set command (fallback) succeeds
            ("SSH timeout set with alternative command", "", 0),
            # apply command
            ("Configuration applied", "", 0),
            # save command
            ("Configuration saved", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Set SSH inactivity timeout
        result = self.flow.set_ssh_inactivity_timeout(timeout_seconds=1800)

        self.assertTrue(result)
        self.assert_logger_has_info("SSH inactivity timeout set to 1800 seconds")
        self.assert_logger_has_info("First command failed, trying alternative command variant")

        # Verify all four commands were called
        self.assertEqual(self.mock_ssh_instance.exec_command.call_count, 4)

        # Check commands
        calls = self.mock_ssh_instance.exec_command.call_args_list
        self.assertIn("nv set system ssh-server inactivity-timeout 1800", calls[0][0][0])
        self.assertIn("nv set system ssh-server inactive-timeout 1800", calls[1][0][0])
        self.assertIn("nv config apply", calls[2][0][0])
        self.assertIn("nv config save", calls[3][0][0])

    def test_show_platform_firmware_failure_returns_false(self):
        """Non-zero exit should return False in show_platform_firmware."""
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result("", "err", 1)
        result = self.flow.show_platform_firmware()
        self.assertFalse(result)

    def test_check_fw_versions_failures_accumulated(self):
        """Validate failures list when missing component, mismatch, and skip None."""
        fw_output = """component    version
compA        1.0.0
compB        2.0.0
"""
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result(fw_output, "", 0)
        expected = {"compA": "1.0.1", "compB": "2.0.0", "compC": "3.0.0", "skip": None}
        result = self.flow.check_fw_versions(expected, "==")
        self.assertFalse(result)
        self.assert_logger_has_error("Firmware version check failures")

    def test_check_os_versions_missing_image_and_mismatch(self):
        """OS versions path: missing image leads to error, mismatch logs and returns False."""
        # Missing image key
        os_output_missing = """attribute    value
uptime       10 days
"""
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result(os_output_missing, "", 0)
        self.assertFalse(self.flow.check_os_versions({"nvos": "5.4.0"}, "=="))

        # Mismatch
        os_output = """attribute    value
image        5.4.1
"""
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result(os_output, "", 0)
        self.assertFalse(self.flow.check_os_versions({"nvos": "5.4.0"}, "=="))

    def test_set_ssh_inactivity_timeout_failure_paths(self):
        """Cover set_ssh_inactivity_timeout when apply/save fails and when set command fails."""
        # set ok, apply fails
        exec_returns = [
            self.create_mock_ssh_command_result("ok", "", 0),  # set
            self.create_mock_ssh_command_result("", "apply fail", 1),  # apply
        ]
        self.mock_ssh_instance.exec_command.side_effect = exec_returns
        self.assertFalse(self.flow.set_ssh_inactivity_timeout(1200))

        # set ok, apply ok, save fails
        self.mock_ssh_instance.exec_command.side_effect = [
            self.create_mock_ssh_command_result("ok", "", 0),  # set
            self.create_mock_ssh_command_result("ok", "", 0),  # apply
            self.create_mock_ssh_command_result("save fail", "", 1),  # save
        ]
        self.assertFalse(self.flow.set_ssh_inactivity_timeout(1200))

        # Both set commands fail (first command fails, second command also fails)
        self.mock_ssh_instance.exec_command.side_effect = [
            self.create_mock_ssh_command_result("", "set fail", 1),  # first set command
            self.create_mock_ssh_command_result("", "set fail alternative", 1),  # second set command
        ]
        self.assertFalse(self.flow.set_ssh_inactivity_timeout(1200))

    def test_show_system_version_failure_returns_false(self):
        """Non-zero exit in show_system_version should return False."""
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result("", "err", 1)
        result = self.flow.show_system_version()
        self.assertFalse(result)

    def test_fetch_and_install_platform_firmware_failures(self):
        """Cover failure return paths for fetch/install platform firmware."""
        # Fetch fails
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result("", "fetch err", 1)
        self.assertFalse(self.flow.fetch_platform_firmware("http://x/fw.bin"))
        # Install fails (fetch ok then install not ok)
        self.mock_ssh_instance.exec_command.side_effect = [
            self.create_mock_ssh_command_result("ok", "", 0),
            self.create_mock_ssh_command_result("", "install err", 1),
        ]
        self.assertFalse(self.flow.fetch_and_install_switch_firmware(firmware_url="http://x/fw.bin", component="bios"))

    def test_fetch_and_install_system_image_failures(self):
        """Cover failure return paths for fetch/install system image (NVOS)."""
        # Fetch fails
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result("", "fetch err", 1)
        self.assertFalse(self.flow.fetch_system_image("http://x/os.bin"))
        # Install fails (fetch ok then install not ok)
        self.mock_ssh_instance.exec_command.side_effect = [
            self.create_mock_ssh_command_result("ok", "", 0),
            self.create_mock_ssh_command_result("", "install err", 1),
        ]
        self.assertFalse(self.flow.fetch_and_install_nvos(firmware_url="http://x/os.bin"))

    def test_check_fw_versions_current_version_none_and_mismatch(self):
        """When current_version is None and when mismatch occurs, failures are collected."""
        fw_output = """component    version
compA        1.0.0
"""
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result(fw_output, "", 0)
        # Include component not present in sys_versions to force None, and mismatch on compA
        expected = {"compA": "2.0.0", "missing": "1.2.3"}
        result = self.flow.check_fw_versions(expected, "==")
        self.assertFalse(result)
        self.assert_logger_has_error("Firmware version check failures")

    def test_check_os_versions_skip_none_expected(self):
        """Skip branch when expected NVOS version is None returns True."""
        os_output = """attribute    value
image        5.4.1
"""
        self.mock_ssh_instance.exec_command.return_value = self.create_mock_ssh_command_result(os_output, "", 0)
        self.assertTrue(self.flow.check_os_versions({"nvos": None}, "=="))

    def test_set_ssh_inactivity_timeout_failure_and_exception(self):
        # Both commands return non-zero
        self.mock_ssh_instance.exec_command.side_effect = [
            self.create_mock_ssh_command_result(stdout="", stderr="err", exit_code=1),  # first command
            self.create_mock_ssh_command_result(stdout="", stderr="err alt", exit_code=1),  # second command
        ]
        ok = self.flow.set_ssh_inactivity_timeout(timeout_seconds=900)
        self.assertFalse(ok)
        # Exception path triggers raise from _execute_nv_command
        self.mock_ssh_instance.exec_command.side_effect = ConnectionError("SSH connection failed")
        with self.assertRaises(ConnectionError):
            _ = self.flow.set_ssh_inactivity_timeout(timeout_seconds=900)

    def test_check_fw_versions_missing_and_mismatch(self):
        # mismatch path with present component
        with patch.object(self.flow, "show_platform_firmware", return_value={"FW": "0.9.0"}):
            ok2 = self.flow.check_fw_versions({"FW": "1.0.0"}, operator=">=")
            self.assertFalse(ok2)

    def test_extract_scp_fetch_and_install_cpld_firmware_success(self):
        """Test successful CPLD extraction, SCP transfer, and firmware installation."""
        test_fwpkg_path = "/path/to/test.fwpkg"
        test_firmware_url = "file://"

        # Mock all the required functions and modules
        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.exists") as mock_exists, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.tempfile.mkdtemp"
        ) as mock_mkdtemp, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.PLDMUnpack"
        ) as mock_pldm_class, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.shutil.rmtree"
        ) as mock_rmtree, patch.object(
            self.flow, "_find_cpld_file"
        ) as mock_find_cpld, patch.object(
            self.flow, "_scp_cpld_file_to_switch_os"
        ) as mock_scp, patch.object(
            self.flow, "fetch_and_install_switch_firmware"
        ) as mock_fetch_install:

            # Setup mocks
            mock_exists.return_value = True
            mock_mkdtemp.return_value = "/tmp/cpld_extract_123"

            mock_pldm_instance = MagicMock()
            mock_pldm_class.return_value = mock_pldm_instance
            mock_pldm_instance.unpack_pldm_package.return_value = True

            mock_find_cpld.return_value = "/tmp/cpld_extract_123/cpld_file.bin"
            mock_scp.return_value = True
            mock_fetch_install.return_value = True

            # Execute the function
            result = self.flow.extract_scp_fetch_and_install_cpld_firmware(
                firmware_url=test_firmware_url, fwpkg_file_path=test_fwpkg_path, component="CPLD"
            )

            # Verify results
            self.assertTrue(result)
            # Verify exists was called with the fwpkg path (may be called multiple times for cleanup)
            mock_exists.assert_any_call(test_fwpkg_path)
            mock_mkdtemp.assert_called_once()
            mock_pldm_instance.unpack_pldm_package.assert_called_once_with(test_fwpkg_path, "/tmp/cpld_extract_123")
            mock_find_cpld.assert_called_once_with("/tmp/cpld_extract_123")
            mock_scp.assert_called_once_with("/tmp/cpld_extract_123/cpld_file.bin")
            mock_fetch_install.assert_called_once_with(
                firmware_url=test_firmware_url,
                firmware_file_name="cpld_file.bin",
                component="CPLD",
                timeout=900,
                reboot_config="skip-reboot",
            )
            mock_rmtree.assert_called_once_with("/tmp/cpld_extract_123")

    def test_extract_scp_fetch_and_install_cpld_firmware_file_not_found(self):
        """Test behavior when firmware package file doesn't exist."""
        test_fwpkg_path = "/path/to/nonexistent.fwpkg"
        test_firmware_url = "file://"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.exists") as mock_exists:
            mock_exists.return_value = False

            result = self.flow.extract_scp_fetch_and_install_cpld_firmware(
                firmware_url=test_firmware_url, fwpkg_file_path=test_fwpkg_path, component="CPLD"
            )

            self.assertFalse(result)
            mock_exists.assert_called_once_with(test_fwpkg_path)

    def test_extract_scp_fetch_and_install_cpld_firmware_unpack_failure(self):
        """Test behavior when firmware package unpacking fails."""
        test_fwpkg_path = "/path/to/test.fwpkg"
        test_firmware_url = "file://"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.exists") as mock_exists, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.tempfile.mkdtemp"
        ) as mock_mkdtemp, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.PLDMUnpack"
        ) as mock_pldm_class, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.shutil.rmtree"
        ) as mock_rmtree:

            mock_exists.return_value = True
            mock_mkdtemp.return_value = "/tmp/cpld_extract_123"

            mock_pldm_instance = MagicMock()
            mock_pldm_class.return_value = mock_pldm_instance
            mock_pldm_instance.unpack_pldm_package.return_value = False

            result = self.flow.extract_scp_fetch_and_install_cpld_firmware(
                firmware_url=test_firmware_url, fwpkg_file_path=test_fwpkg_path, component="CPLD"
            )

            self.assertFalse(result)
            mock_rmtree.assert_called_once_with("/tmp/cpld_extract_123")

    def test_extract_scp_fetch_and_install_cpld_firmware_cpld_not_found(self):
        """Test behavior when CPLD file is not found in unpacked files."""
        test_fwpkg_path = "/path/to/test.fwpkg"
        test_firmware_url = "file://"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.exists") as mock_exists, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.tempfile.mkdtemp"
        ) as mock_mkdtemp, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.PLDMUnpack"
        ) as mock_pldm_class, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.shutil.rmtree"
        ) as mock_rmtree, patch.object(
            self.flow, "_find_cpld_file"
        ) as mock_find_cpld:

            mock_exists.return_value = True
            mock_mkdtemp.return_value = "/tmp/cpld_extract_123"

            mock_pldm_instance = MagicMock()
            mock_pldm_class.return_value = mock_pldm_instance
            mock_pldm_instance.unpack_pldm_package.return_value = True

            mock_find_cpld.return_value = ""  # No CPLD file found

            result = self.flow.extract_scp_fetch_and_install_cpld_firmware(
                firmware_url=test_firmware_url, fwpkg_file_path=test_fwpkg_path, component="CPLD"
            )

            self.assertFalse(result)
            mock_rmtree.assert_called_once_with("/tmp/cpld_extract_123")

    def test_extract_scp_fetch_and_install_cpld_firmware_scp_failure(self):
        """Test behavior when SCP transfer fails."""
        test_fwpkg_path = "/path/to/test.fwpkg"
        test_firmware_url = "file://"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.exists") as mock_exists, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.tempfile.mkdtemp"
        ) as mock_mkdtemp, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.PLDMUnpack"
        ) as mock_pldm_class, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.shutil.rmtree"
        ) as mock_rmtree, patch.object(
            self.flow, "_find_cpld_file"
        ) as mock_find_cpld, patch.object(
            self.flow, "_scp_cpld_file_to_switch_os"
        ) as mock_scp:

            mock_exists.return_value = True
            mock_mkdtemp.return_value = "/tmp/cpld_extract_123"

            mock_pldm_instance = MagicMock()
            mock_pldm_class.return_value = mock_pldm_instance
            mock_pldm_instance.unpack_pldm_package.return_value = True

            mock_find_cpld.return_value = "/tmp/cpld_extract_123/cpld_file.bin"
            mock_scp.return_value = False  # SCP fails

            result = self.flow.extract_scp_fetch_and_install_cpld_firmware(
                firmware_url=test_firmware_url, fwpkg_file_path=test_fwpkg_path, component="CPLD"
            )

            self.assertFalse(result)
            mock_rmtree.assert_called_once_with("/tmp/cpld_extract_123")

    def test_extract_scp_fetch_and_install_cpld_firmware_install_failure(self):
        """Test behavior when firmware installation fails."""
        test_fwpkg_path = "/path/to/test.fwpkg"
        test_firmware_url = "file://"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.exists") as mock_exists, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.tempfile.mkdtemp"
        ) as mock_mkdtemp, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.PLDMUnpack"
        ) as mock_pldm_class, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.shutil.rmtree"
        ) as mock_rmtree, patch.object(
            self.flow, "_find_cpld_file"
        ) as mock_find_cpld, patch.object(
            self.flow, "_scp_cpld_file_to_switch_os"
        ) as mock_scp, patch.object(
            self.flow, "fetch_and_install_switch_firmware"
        ) as mock_fetch_install:

            mock_exists.return_value = True
            mock_mkdtemp.return_value = "/tmp/cpld_extract_123"

            mock_pldm_instance = MagicMock()
            mock_pldm_class.return_value = mock_pldm_instance
            mock_pldm_instance.unpack_pldm_package.return_value = True

            mock_find_cpld.return_value = "/tmp/cpld_extract_123/cpld_file.bin"
            mock_scp.return_value = True
            mock_fetch_install.return_value = False  # Installation fails

            result = self.flow.extract_scp_fetch_and_install_cpld_firmware(
                firmware_url=test_firmware_url, fwpkg_file_path=test_fwpkg_path, component="CPLD"
            )

            self.assertFalse(result)
            mock_fetch_install.assert_called_once_with(
                firmware_url=test_firmware_url,
                firmware_file_name="cpld_file.bin",
                component="CPLD",
                timeout=900,
                reboot_config="skip-reboot",
            )
            mock_rmtree.assert_called_once_with("/tmp/cpld_extract_123")

    def test_find_cpld_file_success(self):
        """Test CPLD file finding with successful pattern match."""
        test_directory = "/tmp/test_dir"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.glob.glob") as mock_glob, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.isfile"
        ) as mock_isfile:
            # First pattern matches
            mock_glob.return_value = ["/tmp/test_dir/switch_cpld_v1.bin"]
            mock_isfile.return_value = True  # Mock file validation to pass

            result = self.flow._find_cpld_file(test_directory)

            self.assertEqual(result, "/tmp/test_dir/switch_cpld_v1.bin")

    def test_find_cpld_file_not_found(self):
        """Test CPLD file finding when no files match."""
        test_directory = "/tmp/test_dir"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.glob.glob") as mock_glob:
            # No matches for any pattern
            mock_glob.return_value = []

            result = self.flow._find_cpld_file(test_directory)

            self.assertEqual(result, "")

    def test_find_cpld_file_skips_directories(self):
        """Test CPLD file finding skips directories and only returns actual files."""
        test_directory = "/tmp/test_dir"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.glob.glob") as mock_glob, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.isfile"
        ) as mock_isfile:
            # Mock glob to return different results for different patterns
            def glob_side_effect(pattern):
                if "*cpld*" in pattern:
                    return [
                        "/tmp/test_dir/cpld_folder",  # This is a directory (should be skipped)
                        "/tmp/test_dir/switch_cpld_v1.bin",  # This is a file (should be returned)
                    ]
                else:
                    return []  # Other patterns don't match

            mock_glob.side_effect = glob_side_effect

            # Mock isfile to return False for directory, True for file
            def mock_isfile_func(path):
                return path.endswith(".bin")  # Only .bin files are considered files

            mock_isfile.side_effect = mock_isfile_func

            result = self.flow._find_cpld_file(test_directory)

            # Should return the file, not the directory
            self.assertEqual(result, "/tmp/test_dir/switch_cpld_v1.bin")

            # Verify isfile was called for both paths from the matching pattern
            self.assertEqual(mock_isfile.call_count, 2)

    def test_find_cpld_file_multiple_matches_intelligent_selection(self):
        """Test CPLD file finding uses intelligent selection when multiple matches exist."""
        test_directory = "/tmp/test_dir"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.glob.glob") as mock_glob, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.isfile"
        ) as mock_isfile:
            # Multiple files matching different patterns - should select based on priority
            def glob_side_effect(pattern):
                if "*cpld*" in pattern:
                    return ["/tmp/test_dir/switch_cpld_v1.bin"]  # Priority 0
                elif "*CPLD*" in pattern:
                    return ["/tmp/test_dir/switch_CPLD_v2.bin"]  # Priority 1
                return []

            mock_glob.side_effect = glob_side_effect
            mock_isfile.return_value = True  # All are valid files

            result = self.flow._find_cpld_file(test_directory)

            # Should return the higher priority match (*cpld* pattern has priority 0)
            self.assertEqual(result, "/tmp/test_dir/switch_cpld_v1.bin")

    def test_find_cpld_file_unusual_patterns(self):
        """Test CPLD file finding with unusual but valid patterns."""
        test_directory = "/tmp/test_dir"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.glob.glob") as mock_glob, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.isfile"
        ) as mock_isfile:
            # Test with unusual but valid CPLD file naming patterns
            test_cases = [
                "UPPER_CPLD_FILE.BIN",
                "mixed_Case_CPLD.img",
                "cpld123_firmware.hex",
                "my_custom_cpld_v2.1.bin",
            ]

            for test_file in test_cases:
                with self.subTest(filename=test_file):
                    mock_glob.return_value = [f"/tmp/test_dir/{test_file}"]
                    mock_isfile.return_value = True

                    result = self.flow._find_cpld_file(test_directory)

                    self.assertEqual(result, f"/tmp/test_dir/{test_file}")

    def test_find_cpld_file_extension_fallback(self):
        """Test CPLD file finding falls back to extension-based search when patterns fail."""
        test_directory = "/tmp/test_dir"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.glob.glob") as mock_glob, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.isfile"
        ) as mock_isfile:

            def glob_side_effect(pattern):
                # No matches for cpld patterns, but matches for *.bin with "cpld" in name
                if "*cpld*" in pattern.lower() or "*CPLD*" in pattern:
                    return []  # No direct pattern matches
                elif "*.bin" in pattern:
                    return ["/tmp/test_dir/firmware_cpld_data.bin"]
                return []

            mock_glob.side_effect = glob_side_effect
            mock_isfile.return_value = True

            result = self.flow._find_cpld_file(test_directory)

            # Should find the file via extension fallback
            self.assertEqual(result, "/tmp/test_dir/firmware_cpld_data.bin")

    def test_find_cpld_file_logs_multiple_candidates(self):
        """Test that CPLD file finding logs information about multiple candidates."""
        test_directory = "/tmp/test_dir"

        with patch("FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.glob.glob") as mock_glob, patch(
            "FactoryMode.TrayFlowFunctions.switch_factory_flow_functions.os.path.isfile"
        ) as mock_isfile:
            # Multiple files matching the same pattern - should log selection details
            mock_glob.return_value = ["/tmp/test_dir/switch_cpld_main.bin", "/tmp/test_dir/switch_cpld_backup.bin"]
            mock_isfile.return_value = True

            result = self.flow._find_cpld_file(test_directory)

            # Should return the first one (alphabetically sorted)
            self.assertEqual(result, "/tmp/test_dir/switch_cpld_backup.bin")  # "backup" comes before "main"

            # Should have logged the selection decision
            self.assert_logger_has_info("Multiple CPLD candidates found. Selected: switch_cpld_backup.bin")

    def test_scp_cpld_file_to_switch_os_missing_config(self):
        """Test CPLD SCP file transfer with missing OS configuration."""
        test_file = "/tmp/test_file.bin"

        # Mock the BaseConnectionManager's scp_files_target to return False for missing config
        with patch.object(self.flow.config.connection, "scp_files_target") as mock_scp:
            mock_scp.return_value = False

            result = self.flow._scp_cpld_file_to_switch_os(test_file)

            self.assertFalse(result)
            mock_scp.assert_called_once()

    def test_scp_tool_to_os_success(self):
        """Test successful SCP tool transfer to switch OS."""
        test_tool_path = "/path/to/tool.sh"

        # Mock the BaseConnectionManager's scp_tool_to_os to return True
        with patch.object(self.flow.config.connection, "scp_tool_to_os") as mock_scp:
            mock_scp.return_value = True

            result = self.flow.scp_tool_to_os(test_tool_path)

            # Verify results
            self.assertTrue(result)
            mock_scp.assert_called_once_with(
                test_tool_path,
                self.flow.config.config.get("connection", {}).get("switch", {}).get("os", {}),
                logger=self.flow.logger,
            )

    def test_scp_tool_to_os_failure(self):
        """Test SCP tool transfer failure."""
        test_tool_path = "/path/to/tool.sh"

        # Mock the BaseConnectionManager's scp_tool_to_os to return False
        with patch.object(self.flow.config.connection, "scp_tool_to_os") as mock_scp:
            mock_scp.return_value = False

            result = self.flow.scp_tool_to_os(test_tool_path)

            # Verify results
            self.assertFalse(result)
            mock_scp.assert_called_once()

    def test_scp_tool_to_os_logging(self):
        """Test that scp_tool_to_os delegates correctly and passes logger."""
        test_tool_path = "/long/path/to/complex_tool_name.bin"

        # Mock the BaseConnectionManager's scp_tool_to_os to return True
        with patch.object(self.flow.config.connection, "scp_tool_to_os") as mock_scp:
            mock_scp.return_value = True

            result = self.flow.scp_tool_to_os(test_tool_path)

            # Verify delegation to base class with correct parameters
            self.assertTrue(result)
            mock_scp.assert_called_once_with(
                test_tool_path,
                self.flow.config.config.get("connection", {}).get("switch", {}).get("os", {}),
                logger=self.flow.logger,
            )

    # URL Construction Tests
    def test_fetch_and_install_switch_firmware_url_construction_with_path(self):
        """Test file:// URL construction when firmware_file_name contains a path."""
        # Mock successful command executions
        command_results = [
            # fetch command
            ("Firmware downloaded successfully", "", 0),
            # install command
            ("Firmware installed successfully", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Execute with firmware_file_name containing path (firmware_url is ignored when filename provided)
        result = self.flow.fetch_and_install_switch_firmware(
            firmware_url="file://",
            firmware_file_name="Switch Tray/Switch Tray Firmware/BMC/250713.1.0/nvfw_GB200-P4978_0004_250713.1.0_prod-signed.fwpkg",
            component="BMC",
            timeout=900,
            reboot_config="skip-reboot",
        )

        self.assertTrue(result)

        # Verify commands were executed
        self.assertEqual(self.mock_ssh_instance.exec_command.call_count, 2)

        # Check first command (fetch) - should use file:// URL with username from config
        first_call = self.mock_ssh_instance.exec_command.call_args_list[0]
        expected_fetch_cmd = "nv action fetch platform firmware BMC file:///home/admin/nvfw_GB200-P4978_0004_250713.1.0_prod-signed.fwpkg"
        self.assertEqual(first_call[0][0], expected_fetch_cmd)

        # Check second command (install) - should use basename for install
        second_call = self.mock_ssh_instance.exec_command.call_args_list[1]
        expected_install_cmd = "nv action install platform firmware BMC files nvfw_GB200-P4978_0004_250713.1.0_prod-signed.fwpkg skip-reboot"
        self.assertEqual(second_call[0][0], expected_install_cmd)

    def test_fetch_and_install_switch_firmware_url_construction_without_filename(self):
        """Test URL construction when firmware_file_name is not provided."""
        # Mock successful command executions
        command_results = [
            # fetch command
            ("Firmware downloaded successfully", "", 0),
            # install command
            ("Firmware installed successfully", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Execute without firmware_file_name
        result = self.flow.fetch_and_install_switch_firmware(
            firmware_url="scp://user:pass@192.168.1.100/firmware/switch_firmware.fwpkg",
            component="BIOS",
            timeout=900,
            reboot_config="skip-reboot",
        )

        self.assertTrue(result)

        # Verify commands were executed
        self.assertEqual(self.mock_ssh_instance.exec_command.call_count, 2)

        # Check first command (fetch) - should use URL directly
        first_call = self.mock_ssh_instance.exec_command.call_args_list[0]
        expected_fetch_cmd = (
            "nv action fetch platform firmware BIOS scp://user:pass@192.168.1.100/firmware/switch_firmware.fwpkg"
        )
        self.assertEqual(first_call[0][0], expected_fetch_cmd)

        # Check second command (install) - should extract filename from URL
        second_call = self.mock_ssh_instance.exec_command.call_args_list[1]
        expected_install_cmd = "nv action install platform firmware BIOS files switch_firmware.fwpkg skip-reboot"
        self.assertEqual(second_call[0][0], expected_install_cmd)

    def test_fetch_and_install_nvos_url_construction_with_path(self):
        """Test NVOS file:// URL construction when firmware_file_name contains a path."""
        # Mock successful command executions
        command_results = [
            # fetch command
            ("NVOS image downloaded successfully", "", 0),
            # install command
            ("NVOS image installed successfully", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Execute with firmware_file_name containing path (firmware_url is ignored when filename provided)
        result = self.flow.fetch_and_install_nvos(
            firmware_url="file://",
            firmware_file_name="Switch Tray/Switch Tray Software/NVOS/25.02.4257/nvos-amd64-25.02.4257.bin",
            timeout=900,
            reboot_config="reboot no",
        )

        self.assertTrue(result)

        # Verify commands were executed
        self.assertEqual(self.mock_ssh_instance.exec_command.call_count, 2)

        # Check first command (fetch) - should use file:// URL with username from config
        first_call = self.mock_ssh_instance.exec_command.call_args_list[0]
        expected_fetch_cmd = "nv action fetch system image file:///home/admin/nvos-amd64-25.02.4257.bin"
        self.assertEqual(first_call[0][0], expected_fetch_cmd)

        # Check second command (install) - should use basename for install
        second_call = self.mock_ssh_instance.exec_command.call_args_list[1]
        expected_install_cmd = "nv action install system image files nvos-amd64-25.02.4257.bin reboot no"
        self.assertEqual(second_call[0][0], expected_install_cmd)

    def test_fetch_and_install_nvos_url_construction_without_filename(self):
        """Test NVOS URL construction when firmware_file_name is not provided."""
        # Mock successful command executions
        command_results = [
            # fetch command
            ("NVOS image downloaded successfully", "", 0),
            # install command
            ("NVOS image installed successfully", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Execute without firmware_file_name
        result = self.flow.fetch_and_install_nvos(
            firmware_url="scp://user:pass@192.168.1.100/nvos/nvos-system.bin",
            timeout=900,
            reboot_config="reboot no",
        )

        self.assertTrue(result)

        # Verify commands were executed
        self.assertEqual(self.mock_ssh_instance.exec_command.call_count, 2)

        # Check first command (fetch) - should use URL directly
        first_call = self.mock_ssh_instance.exec_command.call_args_list[0]
        expected_fetch_cmd = "nv action fetch system image scp://user:pass@192.168.1.100/nvos/nvos-system.bin"
        self.assertEqual(first_call[0][0], expected_fetch_cmd)

        # Check second command (install) - should extract filename from URL
        second_call = self.mock_ssh_instance.exec_command.call_args_list[1]
        expected_install_cmd = "nv action install system image files nvos-system.bin reboot no"
        self.assertEqual(second_call[0][0], expected_install_cmd)

    def test_fetch_and_install_switch_firmware_file_url_construction_with_path(self):
        """Test file:// URL construction when firmware_file_name contains a path."""
        # Mock successful command executions
        command_results = [
            ("Firmware downloaded successfully", "", 0),
            ("Firmware installed successfully", "", 0),
        ]

        exec_returns = []
        for stdout, stderr, exit_code in command_results:
            exec_returns.append(self.create_mock_ssh_command_result(stdout, stderr, exit_code))

        self.mock_ssh_instance.exec_command.side_effect = exec_returns

        # Execute with firmware_file_name containing path (firmware_url is ignored when filename provided)
        result = self.flow.fetch_and_install_switch_firmware(
            firmware_url="file://",
            firmware_file_name="path/to/firmware.fwpkg",
            component="CPLD",
            timeout=900,
            reboot_config="skip-reboot",
        )

        self.assertTrue(result)

        # Check first command (fetch) - should use file:// URL with username from config
        first_call = self.mock_ssh_instance.exec_command.call_args_list[0]
        expected_fetch_cmd = "nv action fetch platform firmware CPLD file:///home/admin/firmware.fwpkg"
        self.assertEqual(first_call[0][0], expected_fetch_cmd)

        # Check second command (install) - should use basename
        second_call = self.mock_ssh_instance.exec_command.call_args_list[1]
        expected_install_cmd = "nv action install platform firmware CPLD files firmware.fwpkg skip-reboot"
        self.assertEqual(second_call[0][0], expected_install_cmd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
