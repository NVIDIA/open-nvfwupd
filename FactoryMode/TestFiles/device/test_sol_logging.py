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


#!/usr/bin/env python3
"""
SOL Logging and Boot Integration Tests

This module tests the SOL (Serial Over LAN) logging functionality in the
ComputeFactoryFlow class, including process management, output formatting,
and integration with boot sequence operations.

These tests validate:
- SOL logging process creation and management
- Timestamp formatting and carriage return handling
- Process termination and cleanup
- Boot integration with SOL logging
- Multi-state boot handling
- Concurrent session management
- Error handling and timeouts

Use the following command to run the tests:
python3 -m unittest FactoryMode.TestFiles.test_sol_logging -v
"""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from FactoryMode.TrayFlowFunctions.compute_factory_flow_functions import (
    ComputeFactoryFlow,
    ComputeFactoryFlowConfig,
)

# Mark all tests in this file
pytestmark = [pytest.mark.device, pytest.mark.compute]


class TestSOLLogging(unittest.TestCase):
    """Test cases for SOL logging functionality."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "test_config.yaml")

        # Create minimal config file
        config_data = {
            "settings": {"default_retry_count": 2},
            "variables": {"test_device_id": "compute1"},
            "connection": {
                "compute": {
                    "bmc": {
                        "ip": "192.168.1.100",
                        "username": "admin",
                        "password": "password",
                        "port": 443,
                    },
                    "os": {
                        "ip": "192.168.1.100",
                        "username": "root",
                        "password": "root_password",
                        "port": 22,
                    },
                }
            },
            "compute": {
                "DOT": "NoDOT",  # Required setting
                "post_logging_enabled": False,  # Disabled by default for tests
                "use_ssh_sol": False,  # Use IPMI by default for tests
            },
        }

        import yaml

        with open(self.config_path, "w") as f:
            yaml.dump(config_data, f)

        # Create ComputeFactoryFlow instance
        self.config = ComputeFactoryFlowConfig(self.config_path)
        self.flow = ComputeFactoryFlow(self.config, "compute1")

        # Mock logger to avoid logging output
        self.flow.logger = MagicMock()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        # Use the flow's built-in close method which handles SOL cleanup
        try:
            self.flow.close()
        except Exception as e:
            # Log but don't fail the test for cleanup errors
            print(f"Warning: Error during flow cleanup: {e}")

        # Clean up temporary directory
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_start_sol_logging_process_creation(self):
        """Test that _start_ipmi_sol_logging creates ipmitool subprocess correctly."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Mock subprocess.Popen and related operations
        mock_process = MagicMock()
        mock_process.pid = 12345
        # Create a mock stdout that properly ends iteration
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = [
            "SOL session activated\n",
            "",
        ]  # Empty string ends iteration
        mock_process.stdout = mock_stdout
        mock_process.terminate = MagicMock()
        mock_process.wait = MagicMock()
        mock_process.kill = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            # Mock execute_ipmitool_command for SOL deactivation
            self.flow.execute_ipmitool_command = MagicMock(return_value=True)

            result = self.flow._start_ipmi_sol_logging(timestamp)

            self.assertIsNotNone(result)

            # Verify subprocess.Popen was called with correct ipmitool command
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]  # First positional argument (command list)

            self.assertEqual(call_args[0], "ipmitool")
            self.assertIn("-I", call_args)
            self.assertIn("lanplus", call_args)
            self.assertIn("-H", call_args)
            self.assertIn("192.168.1.100", call_args)  # BMC IP
            self.assertIn("sol", call_args)
            self.assertIn("activate", call_args)

            # Verify process tracking is set up
            log_path = result
            self.assertIn(log_path, self.flow._sol_processes)
            process_info = self.flow._sol_processes[log_path]
            self.assertEqual(process_info["process"], mock_process)

            # Verify background thread was started (check it's a real thread)
            self.assertIn("thread", process_info)
            thread = process_info["thread"]
            self.assertIsInstance(thread, threading.Thread)
            self.assertTrue(thread.daemon)  # Should be daemon thread

            # Clean up
            stop_result = self.flow.stop_sol_logging(log_path)
            self.assertTrue(stop_result)

            # Wait for the thread to properly finish
            if thread and thread.is_alive():
                thread.join(timeout=1.0)

            # Give time for cleanup to complete
            time.sleep(0.2)

            # Ensure the log file path is removed from tracking
            self.assertNotIn(log_path, self.flow._sol_processes)

    def test_sol_output_timestamp_formatting(self):
        """Test that SOL output is formatted with [YYYY-MM-DD HH:MM:SS] timestamps."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create a real file to test timestamp formatting
        test_output_lines = [
            "System boot starting...\n",
            "Loading kernel modules\n",
            "Network interface up\n",
        ]

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.stdout.readline.side_effect = test_output_lines + [""]  # Empty string to end iteration

        with patch("subprocess.Popen", return_value=mock_process):
            self.flow.execute_ipmitool_command = MagicMock(return_value=True)

            log_file_path = self.flow._start_ipmi_sol_logging(timestamp)
            self.assertIsNotNone(log_file_path)

            # Wait a bit for the thread to process the output
            import time

            time.sleep(0.1)

            # Read the actual file to verify timestamp formatting
            if os.path.exists(log_file_path):
                with open(log_file_path) as f:
                    file_contents = f.read()
                    lines = file_contents.split("\n")

                    # Verify timestamp format in file contents
                    for line in lines:
                        if line.strip():  # Skip empty lines
                            # Each line should start with [YYYY-MM-DD HH:MM:SS] format
                            self.assertRegex(line, r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
                            # Should contain actual content after timestamp
                            self.assertIn("] ", line)

            # Clean up SOL logging
            self.flow.stop_sol_logging(log_file_path)

    def test_sol_output_carriage_return_handling(self):
        """Test that carriage return characters are properly stripped from SOL output."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Test output with carriage returns that should be stripped
        test_output_with_cr = [
            "Progress: 50%\r\n",  # Should strip \r but keep content
            "Progress: 100%\r\r\n",  # Multiple \r should be stripped
            "Complete!\r",  # \r without \n
            "Next line\n",  # Normal line without \r
        ]

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.stdout.readline.side_effect = test_output_with_cr + [""]

        with patch("subprocess.Popen", return_value=mock_process):
            self.flow.execute_ipmitool_command = MagicMock(return_value=True)

            log_file_path = self.flow._start_ipmi_sol_logging(timestamp)
            self.assertIsNotNone(log_file_path)

            # Wait a bit for the thread to process the output
            import time

            time.sleep(0.1)

            # Read the actual file to verify carriage returns were stripped
            if os.path.exists(log_file_path):
                with open(log_file_path) as f:
                    file_contents = f.read()

                    # Should not contain carriage returns
                    self.assertNotIn("\r", file_contents)
                    # Should contain the actual content with timestamps
                    self.assertIn("Progress: 50%", file_contents)
                    self.assertIn("Progress: 100%", file_contents)
                    self.assertIn("Complete!", file_contents)
                    self.assertIn("Next line", file_contents)

            # Clean up SOL logging
            self.flow.stop_sol_logging(log_file_path)

    def test_sol_process_tracking_registry(self):
        """Test that _sol_processes registry is maintained correctly."""
        import uuid
        from datetime import datetime

        # Use unique identifiers to ensure different log files
        timestamp1 = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
        timestamp2 = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]

        # Create distinct mock processes with different PIDs
        def create_mock_process(pid, stdout_lines):
            mock_process = MagicMock()
            mock_process.pid = pid
            mock_stdout = MagicMock()
            mock_stdout.readline.side_effect = stdout_lines
            mock_process.stdout = mock_stdout
            mock_process.terminate = MagicMock()
            mock_process.wait = MagicMock()
            return mock_process

        mock_process_1 = create_mock_process(12345, ["line1\n", ""])
        mock_process_2 = create_mock_process(12346, ["line2\n", ""])

        with patch("subprocess.Popen") as mock_popen:
            # Mock Popen to return different processes for different calls
            mock_popen.side_effect = [mock_process_1, mock_process_2]

            self.flow.execute_ipmitool_command = MagicMock(return_value=True)

            # Start first SOL logging session
            log_file_path_1 = self.flow._start_ipmi_sol_logging(timestamp1)
            self.assertIsNotNone(log_file_path_1)

            # Start second SOL logging session
            log_file_path_2 = self.flow._start_ipmi_sol_logging(timestamp2)
            self.assertIsNotNone(log_file_path_2)

            # Verify both processes are tracked
            self.assertIn(log_file_path_1, self.flow._sol_processes)
            self.assertIn(log_file_path_2, self.flow._sol_processes)

            # Verify they're different log files
            self.assertNotEqual(log_file_path_1, log_file_path_2)

            # Verify correct process objects are stored
            process1 = self.flow._sol_processes[log_file_path_1]["process"]
            process2 = self.flow._sol_processes[log_file_path_2]["process"]
            self.assertIsNotNone(process1)
            self.assertIsNotNone(process2)

            # Verify different PIDs
            self.assertEqual(process1.pid, 12345)
            self.assertEqual(process2.pid, 12346)
            self.assertNotEqual(process1.pid, process2.pid)

            # Stop first session
            result_stop = self.flow.stop_sol_logging(log_file_path_1)
            self.assertTrue(result_stop)

            # Wait for cleanup
            time.sleep(0.2)

            # Verify first session removed but second remains
            self.assertNotIn(log_file_path_1, self.flow._sol_processes)
            self.assertIn(log_file_path_2, self.flow._sol_processes)

            # Clean up second SOL session
            result_stop2 = self.flow.stop_sol_logging(log_file_path_2)
            self.assertTrue(result_stop2)

            # Wait for cleanup
            time.sleep(0.2)

    @patch("FactoryMode.output_manager.get_log_directory")
    def test_wait_for_boot_sol_integration(self, mock_get_log_dir):
        """Test that wait_for_boot automatically starts/stops SOL logging during boot sequence."""
        mock_log_dir = Path(self.test_dir)
        mock_get_log_dir.return_value = mock_log_dir

        # Enable POST logging via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        # Mock the power_on and check_boot_progress methods
        self.flow.power_on = MagicMock(return_value=True)
        self.flow.check_boot_progress = MagicMock(return_value=True)
        self.flow._start_ipmi_sol_logging = MagicMock(return_value="log_path")
        self.flow.stop_sol_logging = MagicMock(return_value=True)

        with patch("FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.datetime") as mock_datetime:
            # Mock datetime.now() to return a mock that has strftime method
            mock_now = MagicMock()
            mock_now.strftime.return_value = "20250101_123000"
            mock_datetime.now.return_value = mock_now

            result = self.flow.wait_for_boot(
                power_on_uri="/redfish/v1/Chassis/System/Actions/ComputerSystem.Reset",
                system_uri="/redfish/v1/Systems/System",
                state="OSRunning",
                timeout=600,
            )

            self.assertTrue(result)

            # Verify IPMI SOL logging was started with timestamp
            self.flow._start_ipmi_sol_logging.assert_called_once_with("20250101_123000")

            # Verify power_on was called
            self.flow.power_on.assert_called_once()

            # Verify boot progress check was called with keyword-only args
            self.flow.check_boot_progress.assert_called_once_with(
                base_uri="/redfish/v1/Systems/System", state="OSRunning", timeout=600
            )

            # Verify SOL logging was stopped after successful boot
            self.flow.stop_sol_logging.assert_called_once_with("log_path")

    def test_wait_for_boot_multi_state_handling(self):
        """Test that wait_for_boot accepts single state or list of states."""
        # Disable POST logging for this test
        self.flow.config.config["compute"]["post_logging_enabled"] = False
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        self.flow.power_on = MagicMock(return_value=True)
        self.flow.check_boot_progress = MagicMock(return_value=True)

        # Test with single state string
        result1 = self.flow.wait_for_boot(
            power_on_uri="/power",
            system_uri="/system",
            state="OSRunning",
        )

        self.assertTrue(result1)
        self.flow.check_boot_progress.assert_called_with(base_uri="/system", state="OSRunning", timeout=600)

        # Reset mock
        self.flow.check_boot_progress.reset_mock()

        # Test with list of states
        target_states = ["OSRunning", "OSBootStarted"]
        result2 = self.flow.wait_for_boot(
            power_on_uri="/power",
            system_uri="/system",
            state=target_states,
        )

        self.assertTrue(result2)
        self.flow.check_boot_progress.assert_called_with(base_uri="/system", state=target_states, timeout=600)

    def test_wait_for_boot_sol_disabled(self):
        """Test that wait_for_boot works correctly when post_logging_enabled=False in config."""
        # Disable POST logging via config (already set to false in setUp, but be explicit)
        self.flow.config.config["compute"]["post_logging_enabled"] = False
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        self.flow.power_on = MagicMock(return_value=True)
        self.flow.check_boot_progress = MagicMock(return_value=True)
        self.flow._start_ipmi_sol_logging = MagicMock(return_value="log_path")
        self.flow.stop_sol_logging = MagicMock(return_value=True)

        result = self.flow.wait_for_boot(
            power_on_uri="/power",
            system_uri="/system",
            state="OSRunning",
        )

        self.assertTrue(result)

        # Verify SOL logging methods were NOT called
        self.flow._start_ipmi_sol_logging.assert_not_called()
        self.flow.stop_sol_logging.assert_not_called()

        # But power and boot check should still work
        self.flow.power_on.assert_called_once()
        self.flow.check_boot_progress.assert_called_once()

    @patch("FactoryMode.output_manager.get_log_directory")
    @patch.object(ComputeFactoryFlow, "stop_sol_logging", return_value=True)
    @patch.object(ComputeFactoryFlow, "_start_ipmi_sol_logging", return_value="log_path_1")
    def test_wait_for_boot_auto_log_path_generation(self, mock_start_sol, mock_stop_sol, mock_get_log_dir):
        """Test that wait_for_boot auto-generates timestamped log file paths."""
        mock_log_dir = Path(self.test_dir)
        mock_get_log_dir.return_value = mock_log_dir

        # Enable POST logging via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        self.flow.power_on = MagicMock(return_value=True)
        self.flow.check_boot_progress = MagicMock(return_value=True)

        # Mock different timestamps for multiple calls
        with patch("FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.datetime") as mock_datetime:
            # Set up datetime mock to return different timestamps on each call
            timestamp_counter = [0]  # Use list to make it mutable in nested function

            def mock_datetime_now():
                timestamp_counter[0] += 1
                mock_dt = MagicMock()
                if timestamp_counter[0] == 1:
                    mock_dt.strftime.return_value = "20250101_123000"
                else:
                    mock_dt.strftime.return_value = "20250101_123001"
                return mock_dt

            mock_datetime.now.side_effect = mock_datetime_now

            # First call
            result1 = self.flow.wait_for_boot(
                power_on_uri="/power",
                system_uri="/system",
                state="OSRunning",
            )
            self.assertTrue(result1)

            # Second call - update mock return value
            mock_start_sol.return_value = "log_path_2"
            result2 = self.flow.wait_for_boot(
                power_on_uri="/power",
                system_uri="/system",
                state="OSRunning",
            )
            self.assertTrue(result2)

            # Verify unique timestamps were passed to the start method
            call_args_list = mock_start_sol.call_args_list
            self.assertEqual(len(call_args_list), 2)

            timestamp_1 = call_args_list[0][0][0]
            timestamp_2 = call_args_list[1][0][0]

            self.assertEqual(timestamp_1, "20250101_123000")
            self.assertEqual(timestamp_2, "20250101_123001")
            self.assertNotEqual(timestamp_1, timestamp_2)  # Should be different

    def test_sol_background_thread_management(self):
        """Test that SOL output processing thread is properly managed."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        mock_process = MagicMock()
        mock_process.pid = 12345
        with patch("subprocess.Popen", return_value=mock_process):
            self.flow.execute_ipmitool_command = MagicMock(return_value=True)

            log_file_path = self.flow._start_ipmi_sol_logging(timestamp)
            self.assertIsNotNone(log_file_path)

            # Verify process info was stored correctly
            self.assertIn(log_file_path, self.flow._sol_processes)
            process_info = self.flow._sol_processes[log_file_path]

            # Verify process is stored
            self.assertEqual(process_info["process"], mock_process)

            # Verify thread was created and is running (real thread)
            self.assertIn("thread", process_info)
            thread = process_info["thread"]
            self.assertIsNotNone(thread)

            # Verify thread is daemon thread (real threading property)
            self.assertTrue(thread.daemon)

            # Verify thread is alive (or was alive briefly)
            # Note: Thread might complete quickly, so we check it was created
            self.assertIsInstance(thread, threading.Thread)

            # Clean up SOL logging
            self.flow.stop_sol_logging(log_file_path)

    def test_sol_concurrent_sessions(self):
        """Test that multiple SOL sessions can run simultaneously on different devices."""
        import uuid
        from datetime import datetime

        # Use unique identifiers to ensure different log files
        timestamp1 = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
        timestamp2 = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]

        # Create distinct mock processes
        def create_mock_process(pid, stdout_lines):
            mock_process = MagicMock()
            mock_process.pid = pid
            mock_stdout = MagicMock()
            mock_stdout.readline.side_effect = stdout_lines
            mock_process.stdout = mock_stdout
            mock_process.terminate = MagicMock()
            mock_process.wait = MagicMock()
            return mock_process

        mock_process_1 = create_mock_process(12345, ["device1\n", ""])
        mock_process_2 = create_mock_process(12346, ["device2\n", ""])

        # Create second flow instance for different device
        config2 = ComputeFactoryFlowConfig(self.config_path)
        flow2 = ComputeFactoryFlow(config2, "compute2")
        flow2.logger = MagicMock()

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = [mock_process_1, mock_process_2]

            self.flow.execute_ipmitool_command = MagicMock(return_value=True)
            flow2.execute_ipmitool_command = MagicMock(return_value=True)

            # Start SOL logging on first device
            log_file_path_1 = self.flow._start_ipmi_sol_logging(timestamp1)
            self.assertIsNotNone(log_file_path_1)

            # Start SOL logging on second device
            log_file_path_2 = flow2._start_ipmi_sol_logging(timestamp2)
            self.assertIsNotNone(log_file_path_2)

            # Verify both sessions are running independently
            self.assertIn(log_file_path_1, self.flow._sol_processes)
            self.assertIn(log_file_path_2, flow2._sol_processes)

            # Verify different process IDs
            pid1 = self.flow._sol_processes[log_file_path_1]["process"].pid
            pid2 = flow2._sol_processes[log_file_path_2]["process"].pid
            self.assertEqual(pid1, 12345)
            self.assertEqual(pid2, 12346)
            self.assertNotEqual(pid1, pid2)

            # Stop first session - should not affect second
            stop_result1 = self.flow.stop_sol_logging(log_file_path_1)
            self.assertTrue(stop_result1, f"Failed to stop SOL logging for {log_file_path_1}")

            # Wait for cleanup
            time.sleep(0.2)

            # Verify first stopped but second still running
            self.assertNotIn(log_file_path_1, self.flow._sol_processes)
            self.assertIn(log_file_path_2, flow2._sol_processes)

            # Clean up second SOL session
            stop_result2 = flow2.stop_sol_logging(log_file_path_2)
            self.assertTrue(stop_result2, f"Failed to stop SOL logging for {log_file_path_2}")

            # Wait for cleanup
            time.sleep(0.2)

            # Also clean up the flow2 instance
            flow2.close()

    def test_sol_timeout_and_error_handling(self):
        """Test proper error handling and timeout management in SOL operations."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Test _start_ipmi_sol_logging error handling
        with patch("subprocess.Popen", side_effect=OSError("Failed to start ipmitool")):
            self.flow.execute_ipmitool_command = MagicMock(return_value=True)

            # Verify no processes are tracked before the test
            self.assertEqual(len(self.flow._sol_processes), 0)

            result = self.flow._start_ipmi_sol_logging(timestamp)

            self.assertIsNone(result)
            # Should not have any tracked processes after failure
            self.assertEqual(len(self.flow._sol_processes), 0)

        # Test stop_sol_logging with non-existent process
        result = self.flow.stop_sol_logging("nonexistent.log")
        self.assertTrue(result)  # Should return True (no-op for non-existent process)

        # Test wait_for_boot SOL failure handling
        # Enable POST logging via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = False

        self.flow.power_on = MagicMock(return_value=True)
        self.flow.check_boot_progress = MagicMock(return_value=True)
        self.flow._start_ipmi_sol_logging = MagicMock(return_value=None)  # SOL fails to start
        self.flow.stop_sol_logging = MagicMock(return_value=True)

        result = self.flow.wait_for_boot(
            power_on_uri="/power",
            system_uri="/system",
            state="OSRunning",
        )

        self.assertFalse(result)  # Should fail if SOL logging fails to start
        self.flow._start_ipmi_sol_logging.assert_called_once()
        # stop_sol_logging should not be called if start failed
        self.flow.stop_sol_logging.assert_not_called()

        # Test wait_for_boot power failure with SOL cleanup
        self.flow._start_ipmi_sol_logging = MagicMock(return_value="log_path")
        self.flow.power_on = MagicMock(return_value=False)  # Power on fails

        with patch(
            "FactoryMode.output_manager.get_log_directory",
            return_value=Path(self.test_dir),
        ):
            result = self.flow.wait_for_boot(
                power_on_uri="/power",
                system_uri="/system",
                state="OSRunning",
            )

            self.assertFalse(result)
            # Should have started SOL logging
            self.flow._start_ipmi_sol_logging.assert_called()
            # Should have cleaned up SOL logging after power failure
            self.flow.stop_sol_logging.assert_called()

    def test_start_ssh_sol_logging_single_socket(self):
        """Test SSH SOL logging for single socket system."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Mock paramiko SSH client
        mock_ssh_client = MagicMock()
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = ["Boot line 1\n", "Boot line 2\n", ""]
        mock_ssh_client.exec_command.return_value = (None, mock_stdout, None)

        # Mock single socket config
        self.flow.config.config["compute"]["num_sockets"] = 1

        with patch("paramiko.SSHClient", return_value=mock_ssh_client), patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.get_log_directory",
            return_value=Path(self.test_dir),
        ):
            result = self.flow._start_ssh_sol_logging(timestamp)
            self.assertIsNotNone(result)
            self.assertEqual(result, timestamp)

            # Verify SSH client was configured (called at least once)
            mock_ssh_client.set_missing_host_key_policy.assert_called()
            mock_ssh_client.connect.assert_called()

            # Verify socket log file was created
            log_dir = Path(self.test_dir)
            socket_0_log = log_dir / f"post_log_{timestamp}.txt"
            self.assertTrue(socket_0_log.exists())

            # Clean up
            self.flow._stop_ssh_sol_logging_by_timestamp(timestamp)

    def test_start_ssh_sol_logging_dual_socket(self):
        """Test SSH SOL logging for dual socket system."""
        import time
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Mock paramiko SSH clients - each gets its own mock stdout
        mock_ssh_client1 = MagicMock()
        mock_stdout1 = MagicMock()
        # Use an iterator to simulate reading lines
        mock_stdout1.readline = MagicMock(side_effect=["Socket 0 boot\n", ""])
        mock_ssh_client1.exec_command.return_value = (None, mock_stdout1, None)

        mock_ssh_client2 = MagicMock()
        mock_stdout2 = MagicMock()
        mock_stdout2.readline = MagicMock(side_effect=["Socket 1 boot\n", ""])
        mock_ssh_client2.exec_command.return_value = (None, mock_stdout2, None)

        # Mock dual socket config
        self.flow.config.config["compute"]["num_sockets"] = 2

        with patch("paramiko.SSHClient", side_effect=[mock_ssh_client1, mock_ssh_client2]), patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.get_log_directory",
            return_value=Path(self.test_dir),
        ):
            result = self.flow._start_ssh_sol_logging(timestamp)

            # Wait a bit for threads to process
            time.sleep(0.1)

            self.assertIsNotNone(result)
            self.assertEqual(result, timestamp)

            # Verify both SSH clients were created
            mock_ssh_client1.connect.assert_called()
            mock_ssh_client2.connect.assert_called()

            # Verify both log files were created
            log_dir = Path(self.test_dir)
            post_log_1 = log_dir / f"post_log_{timestamp}.txt"
            post_log_2 = log_dir / f"post_log_2_{timestamp}.txt"
            self.assertTrue(post_log_1.exists())
            self.assertTrue(post_log_2.exists())

            # Clean up
            self.flow._stop_ssh_sol_logging_by_timestamp(timestamp)

    def test_ssh_sol_authentication_error(self):
        """Test SSH SOL handling of authentication failures."""
        from datetime import datetime

        import paramiko

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        mock_ssh_client = MagicMock()
        mock_ssh_client.connect.side_effect = paramiko.AuthenticationException("Auth failed")

        with patch("paramiko.SSHClient", return_value=mock_ssh_client):
            result = self.flow._start_ssh_sol_logging(timestamp)
            self.assertIsNone(result)

            # Verify no processes were tracked after failure
            timestamp_keys = [k for k in self.flow._sol_processes.keys() if timestamp in str(k)]
            self.assertEqual(len(timestamp_keys), 0)

    def test_ssh_sol_connection_error(self):
        """Test SSH SOL handling of connection failures."""
        from datetime import datetime

        import paramiko

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        mock_ssh_client = MagicMock()
        mock_ssh_client.connect.side_effect = paramiko.SSHException("Connection failed")

        with patch("paramiko.SSHClient", return_value=mock_ssh_client):
            result = self.flow._start_ssh_sol_logging(timestamp)
            self.assertIsNone(result)

    def test_stop_sol_logging_ssh_mode(self):
        """Test unified stop_sol_logging handles SSH mode correctly."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Mock SSH client
        mock_ssh_client = MagicMock()
        mock_stdout = MagicMock()
        mock_stdout.readline = MagicMock(side_effect=["test\n", ""])
        mock_ssh_client.exec_command.return_value = (None, mock_stdout, None)
        mock_ssh_client.close = MagicMock()

        with patch("paramiko.SSHClient", return_value=mock_ssh_client), patch(
            "FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.get_log_directory",
            return_value=Path(self.test_dir),
        ):
            # Start SSH SOL
            self.flow.config.config["compute"]["num_sockets"] = 1
            result = self.flow._start_ssh_sol_logging(timestamp)
            self.assertIsNotNone(result, "Failed to start SSH SOL logging")

            # Wait for thread to start
            time.sleep(0.1)

            # Build the expected log file path
            log_dir = Path(self.test_dir)
            log_file = log_dir / f"post_log_{timestamp}.txt"

            # Verify it exists
            self.assertTrue(log_file.exists(), f"Log file {log_file} does not exist")

            # Verify it's tracked
            self.assertIn(str(log_file), self.flow._sol_processes, f"Log file {log_file} not in tracking")

            # Stop SSH SOL
            stop_result = self.flow.stop_sol_logging(str(log_file))
            self.assertTrue(stop_result, f"Failed to stop SOL logging for {log_file}")

            # Wait for cleanup
            time.sleep(0.2)

            # Verify SSH client was closed
            mock_ssh_client.close.assert_called()

            # Verify process was removed from tracking
            self.assertNotIn(str(log_file), self.flow._sol_processes)

    def test_wait_for_boot_with_ssh_sol_enabled(self):
        """Test wait_for_boot uses SSH SOL when configured."""

        # Enable SSH SOL via config
        self.flow.config.config["compute"]["post_logging_enabled"] = True
        self.flow.config.config["compute"]["use_ssh_sol"] = True
        self.flow.config.config["compute"]["num_sockets"] = 1

        # Mock dependencies
        self.flow.power_on = MagicMock(return_value=True)
        self.flow.check_boot_progress = MagicMock(return_value=True)
        self.flow._start_ssh_sol_logging = MagicMock(return_value="20250101_123000")
        self.flow.stop_sol_logging = MagicMock(return_value=True)

        with patch("FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.datetime") as mock_datetime:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "20250101_123000"
            mock_datetime.now.return_value = mock_now

            result = self.flow.wait_for_boot(
                power_on_uri="/redfish/v1/Systems/System_0/Actions/ComputerSystem.Reset",
                system_uri="/redfish/v1/Systems/System_0",
                state="OSRunning",
            )

            self.assertTrue(result)

            # Verify SSH SOL was started (not IPMI)
            self.flow._start_ssh_sol_logging.assert_called_once_with("20250101_123000")

            # Verify SSH SOL was stopped
            self.flow.stop_sol_logging.assert_called_once()


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
