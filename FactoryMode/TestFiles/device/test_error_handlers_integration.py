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
Error Handler Integration Tests

This module provides integration-level testing for error handler execution,
focusing on real error scenarios, nvdebug log collection, cascading failures,
and custom error handler integration.
"""

import os
import subprocess

# Add the parent directory to the path
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from FactoryMode.factory_flow_orchestrator import FactoryFlowOrchestrator
from FactoryMode.flow_types import DeviceType, FlowStep
from FactoryMode.TrayFlowFunctions.error_handlers import error_handler_collect_nvdebug_logs

from .integration_test_base import IntegrationTestBase

# Mark all tests in this file
pytestmark = pytest.mark.device


class TestErrorHandlersIntegration(IntegrationTestBase):
    """Integration tests for error handler execution with real flow scenarios."""

    def setUp(self):
        """Set up test fixtures and mocks."""
        super().setUp()

        # Create test configuration for orchestrator
        self.config_file = self.create_test_config_file("compute")

        # Create orchestrator with mocked logging directory
        with patch("FactoryMode.output_manager.get_log_directory") as mock_get_log_dir:
            mock_get_log_dir.return_value = Path(self.test_dir) / "logs"
            Path(self.test_dir, "logs").mkdir(exist_ok=True)
            self.orchestrator = FactoryFlowOrchestrator(self.config_file)

        # Track error handler calls for verification
        self.error_handler_calls = []

    def tearDown(self):
        """Clean up test fixtures."""
        super().tearDown()

    # Test 1: nvdebug log collection on error
    @patch("FactoryMode.TrayFlowFunctions.error_handlers.get_log_directory")
    @patch("subprocess.run")
    def test_nvdebug_log_collection_flow(self, mock_subprocess, mock_get_log_dir):
        """Test nvdebug log collection when error handler is triggered."""
        # Set up mock log directory - this is the base log directory
        log_dir = Path(self.test_dir) / "logs"
        mock_get_log_dir.return_value = log_dir
        log_dir.mkdir(exist_ok=True)

        # Ensure the device-specific nvdebug directory does NOT exist
        # The error handler creates: log_dir / f"nvdebug_logs_{device_id}"
        device_log_dir = log_dir / "nvdebug_logs_compute1"
        if device_log_dir.exists():
            import shutil

            shutil.rmtree(device_log_dir)

        # Add compute_config to orchestrator with proper structure
        mock_compute_config = MagicMock()
        mock_compute_config.config = {
            "connection": {
                "compute": {
                    "bmc": {
                        "ip": "192.168.1.100",
                        "username": "root",
                        "password": "test123",
                        "port": 22,
                    },
                    "os": {
                        "ip": "192.168.1.101",
                        "username": "root",
                        "password": "test123",
                        "port": 22,
                    },
                }
            },
            "variables": {"nvdebug_path": "Error_Handler/nvdebug"},
        }
        self.orchestrator.compute_config = mock_compute_config

        # Mock successful nvdebug execution
        mock_result = MagicMock()
        mock_result.stdout = "NVDebug collection completed successfully"
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result

        # Create test step
        step = FlowStep(
            name="test_compute_operation",
            operation="pldm_fw_update",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={"bundle_path": "/test/firmware.pldm"},
            execute_on_error="nvdebug_collector",
        )

        # Register nvdebug error handler
        self.orchestrator.register_error_handler("nvdebug_collector", error_handler_collect_nvdebug_logs)

        # Create context with orchestrator
        context = {
            "orchestrator": self.orchestrator,
            "device_type": DeviceType.COMPUTE,
            "device_id": "compute1",
        }

        # Execute error handler
        test_error = RuntimeError("Firmware update failed")
        result = error_handler_collect_nvdebug_logs(step, test_error, context)

        # Verify error handler behavior
        self.assertFalse(result)  # Should abort flow after collecting logs

        # Verify nvdebug command was called
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args[0][0]

        # Verify nvdebug command structure
        self.assertIn("Error_Handler/nvdebug", call_args[0])  # nvdebug path
        self.assertIn("-i", call_args)  # BMC IP
        self.assertIn("-u", call_args)  # BMC username
        self.assertIn("-p", call_args)  # BMC password
        self.assertIn("-t", call_args)  # Platform
        self.assertIn("-b", call_args)  # Baseboard
        self.assertIn("-o", call_args)  # Output directory

        # Verify the output directory is the device-specific one
        output_dir_index = call_args.index("-o") + 1
        output_dir = call_args[output_dir_index]
        self.assertIn("nvdebug_logs_compute1", str(output_dir))

    # Test 2: nvdebug collection error handling
    @patch("subprocess.run")
    @patch("FactoryMode.output_manager.get_log_directory")
    def test_nvdebug_collection_error_scenarios(self, mock_get_log_dir, mock_subprocess):
        """Test error scenarios during nvdebug collection."""
        # Set up mock log directory
        log_dir = Path(self.test_dir) / "logs"
        mock_get_log_dir.return_value = log_dir
        log_dir.mkdir(exist_ok=True)

        # Test 1: nvdebug command failure
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "nvdebug", stderr="Failed to connect to BMC")

        step = FlowStep(
            name="test_operation",
            operation="power_cycle",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={},
        )

        context = {"orchestrator": self.orchestrator}
        test_error = RuntimeError("Power cycle failed")

        # Execute error handler - should handle nvdebug failure gracefully
        result = error_handler_collect_nvdebug_logs(step, test_error, context)
        self.assertFalse(result)

        # Test 2: Missing credentials
        mock_subprocess.side_effect = None

        # Create config with missing BMC credentials
        config_file = self.create_test_config_file(
            "compute",
            {
                "connection": {
                    "compute": {
                        "bmc": {},  # Empty BMC credentials
                        "os": {
                            "ip": "192.168.1.101",
                            "username": "root",
                            "password": "test123",
                        },
                    }
                }
            },
        )

        with patch("FactoryMode.output_manager.get_log_directory", return_value=log_dir):
            orchestrator = FactoryFlowOrchestrator(config_file)

        context = {"orchestrator": orchestrator}
        result = error_handler_collect_nvdebug_logs(step, test_error, context)
        self.assertFalse(result)

    # Test 3: Cascading error scenarios
    def test_cascading_error_handlers(self):
        """Test multiple error handlers executing in sequence."""
        handler_execution_order = []

        def first_error_handler(step, error, context):
            handler_execution_order.append("first_handler")
            self.error_handler_calls.append(
                {
                    "handler": "first_handler",
                    "step": step.name,
                    "error": str(error),
                    "context_keys": list(context.keys()),
                }
            )
            return True  # Continue to next handler

        def second_error_handler(step, error, context):
            handler_execution_order.append("second_handler")
            self.error_handler_calls.append(
                {
                    "handler": "second_handler",
                    "step": step.name,
                    "error": str(error),
                    "context_keys": list(context.keys()),
                }
            )
            return True  # Continue flow

        def third_error_handler(step, error, context):
            handler_execution_order.append("third_handler")
            self.error_handler_calls.append(
                {
                    "handler": "third_handler",
                    "step": step.name,
                    "error": str(error),
                    "context_keys": list(context.keys()),
                }
            )
            return False  # Abort flow

        # Register handlers
        self.orchestrator.register_error_handler("first_handler", first_error_handler)
        self.orchestrator.register_error_handler("second_handler", second_error_handler)
        self.orchestrator.register_error_handler("third_handler", third_error_handler)

        # Test sequential execution by manually calling handlers
        step = FlowStep(
            name="cascading_test",
            operation="test_operation",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={},
        )

        context = {"orchestrator": self.orchestrator, "test_data": "cascading_test"}
        test_error = RuntimeError("Cascading failure test")

        # Execute handlers in sequence
        result1 = first_error_handler(step, test_error, context)
        self.assertTrue(result1)

        result2 = second_error_handler(step, test_error, context)
        self.assertTrue(result2)

        result3 = third_error_handler(step, test_error, context)
        self.assertFalse(result3)

        # Verify execution order
        self.assertEqual(
            handler_execution_order,
            ["first_handler", "second_handler", "third_handler"],
        )
        self.assertEqual(len(self.error_handler_calls), 3)

        # Verify context propagation
        for call in self.error_handler_calls:
            self.assertIn("orchestrator", call["context_keys"])
            self.assertIn("test_data", call["context_keys"])

    # Test 4: Resource cleanup during error conditions
    def test_resource_cleanup_error_handler(self):
        """Test resource cleanup operations during error handling."""
        cleanup_operations = []

        def resource_cleanup_handler(step, error, context):
            """Error handler that performs resource cleanup."""
            self.error_handler_calls.append(
                {
                    "handler": "resource_cleanup",
                    "step": step.name,
                    "error": str(error),
                    "device_id": step.device_id,
                }
            )

            # Simulate cleanup operations
            cleanup_operations.append(f"cleanup_sessions_{step.device_id}")
            cleanup_operations.append(f"release_locks_{step.device_id}")
            cleanup_operations.append(f"reset_device_state_{step.device_id}")

            # Simulate cleanup success
            return False  # Abort flow after cleanup

        # Register cleanup handler
        self.orchestrator.register_error_handler("resource_cleanup", resource_cleanup_handler)

        # Create step that would require cleanup
        step = FlowStep(
            name="firmware_update_with_cleanup",
            operation="pldm_fw_update",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={"bundle_path": "/test/fw.pldm"},
            execute_on_error="resource_cleanup",
        )

        context = {
            "orchestrator": self.orchestrator,
            "active_sessions": ["session1", "session2"],
            "allocated_resources": ["lock1", "lock2"],
        }

        # Execute cleanup handler
        test_error = RuntimeError("Firmware update failed, cleanup required")
        result = resource_cleanup_handler(step, test_error, context)

        # Verify cleanup was performed
        self.assertFalse(result)
        self.assertEqual(len(cleanup_operations), 3)
        self.assertIn("cleanup_sessions_compute1", cleanup_operations)
        self.assertIn("release_locks_compute1", cleanup_operations)
        self.assertIn("reset_device_state_compute1", cleanup_operations)

        # Verify error handler was called with correct information
        self.assertEqual(len(self.error_handler_calls), 1)
        call = self.error_handler_calls[0]
        self.assertEqual(call["handler"], "resource_cleanup")
        self.assertEqual(call["step"], "firmware_update_with_cleanup")
        self.assertEqual(call["device_id"], "compute1")

    # Test 5: Custom error handler integration
    def test_custom_error_handler_integration(self):
        """Test integration of user-defined custom error handlers."""
        custom_handler_actions = []

        def custom_recovery_handler(step, error, context):
            """Custom error handler that attempts recovery."""
            custom_handler_actions.append("analyze_error")

            # Analyze error type
            if "connection" in str(error).lower() or isinstance(error, ConnectionError):
                custom_handler_actions.append("retry_connection")
                return True  # Retry the operation
            elif "timeout" in str(error).lower() or isinstance(error, TimeoutError):
                custom_handler_actions.append("extend_timeout")
                return True  # Continue with extended timeout
            else:
                custom_handler_actions.append("log_unknown_error")
                return False  # Abort for unknown errors

        def custom_notification_handler(step, error, context):
            """Custom error handler that sends notifications."""
            custom_handler_actions.append("send_notification")
            custom_handler_actions.append(f"notify_device_{step.device_id}_failed")

            # Record error details
            self.error_handler_calls.append(
                {
                    "handler": "notification",
                    "step": step.name,
                    "error_type": type(error).__name__,
                    "device_id": step.device_id,
                    "operation": step.operation,
                }
            )

            return True  # Continue flow after notification

        # Register custom handlers
        self.orchestrator.register_error_handler("custom_recovery", custom_recovery_handler)
        self.orchestrator.register_error_handler("custom_notification", custom_notification_handler)

        # Test connection error scenario
        step1 = FlowStep(
            name="connection_test",
            operation="check_bmc_connectivity",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={},
        )

        context = {"orchestrator": self.orchestrator}
        connection_error = ConnectionError("Failed to connect to BMC")

        result1 = custom_recovery_handler(step1, connection_error, context)
        self.assertTrue(result1)  # Should retry

        # Test timeout error scenario
        step2 = FlowStep(
            name="timeout_test",
            operation="firmware_update",
            device_type=DeviceType.COMPUTE,
            device_id="compute2",
            parameters={},
        )

        timeout_error = TimeoutError("Operation timed out")
        result2 = custom_recovery_handler(step2, timeout_error, context)
        self.assertTrue(result2)  # Should continue with extended timeout

        # Test notification handler
        unknown_error = RuntimeError("Unknown error occurred")
        result3 = custom_notification_handler(step2, unknown_error, context)
        self.assertTrue(result3)  # Should continue after notification

        # Verify custom actions were performed
        expected_actions = [
            "analyze_error",
            "retry_connection",  # Connection error
            "analyze_error",
            "extend_timeout",  # Timeout error
            "send_notification",
            "notify_device_compute2_failed",  # Notification
        ]
        self.assertEqual(custom_handler_actions, expected_actions)

        # Verify notification handler call was recorded
        self.assertEqual(len(self.error_handler_calls), 1)
        call = self.error_handler_calls[0]
        self.assertEqual(call["handler"], "notification")
        self.assertEqual(call["error_type"], "RuntimeError")
        self.assertEqual(call["device_id"], "compute2")

    # Test 6: Error context propagation
    def test_error_context_propagation(self):
        """Test that error context is properly propagated through handlers."""
        context_validation_results = []

        def context_validating_handler(step, error, context):
            """Error handler that validates context contents."""
            # Validate required context fields
            required_fields = [
                "orchestrator",
                "device_type",
                "device_id",
                "operation",
                "parameters",
            ]

            validation_result = {
                "step_name": step.name,
                "has_all_required_fields": True,
                "missing_fields": [],
                "extra_fields": [],
            }

            for field in required_fields:
                if field not in context:
                    validation_result["has_all_required_fields"] = False
                    validation_result["missing_fields"].append(field)

            # Check for additional context fields
            expected_fields = set(required_fields + ["retry_attempts", "optional_flow_executed"])
            actual_fields = set(context.keys())
            validation_result["extra_fields"] = list(actual_fields - expected_fields)

            context_validation_results.append(validation_result)
            return False  # Abort flow

        # Register context validation handler
        self.orchestrator.register_error_handler("context_validator", context_validating_handler)

        # Create comprehensive context
        step = FlowStep(
            name="context_test_step",
            operation="test_context_propagation",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={"test_param": "test_value"},
            execute_on_error="context_validator",
        )

        context = {
            "orchestrator": self.orchestrator,
            "device_type": DeviceType.COMPUTE,
            "device_id": "compute1",
            "operation": "test_context_propagation",
            "parameters": {"test_param": "test_value"},
            "retry_attempts": 3,
            "optional_flow_executed": None,
            "custom_field": "custom_value",
        }

        # Execute context validation
        test_error = RuntimeError("Context validation test")
        result = context_validating_handler(step, test_error, context)

        # Verify context validation
        self.assertFalse(result)
        self.assertEqual(len(context_validation_results), 1)

        validation = context_validation_results[0]
        self.assertEqual(validation["step_name"], "context_test_step")
        self.assertTrue(validation["has_all_required_fields"])
        self.assertEqual(validation["missing_fields"], [])
        self.assertEqual(validation["extra_fields"], ["custom_field"])

    # Test 7: Error handler registration validation
    def test_error_handler_registration_validation(self):
        """Test error handler registration validation and error conditions."""

        # Test valid handler registration
        def valid_handler(step, error, context):
            return True

        # Should succeed
        self.orchestrator.register_error_handler("valid_handler", valid_handler)
        self.assertIn("valid_handler", self.orchestrator.error_handlers)

        # Test invalid registrations
        with self.assertRaises(ValueError):
            self.orchestrator.register_error_handler("", valid_handler)  # Empty name

        with self.assertRaises(ValueError):
            self.orchestrator.register_error_handler(None, valid_handler)  # None name

        with self.assertRaises(TypeError):
            self.orchestrator.register_error_handler("invalid_handler", None)  # None handler

        with self.assertRaises(TypeError):
            self.orchestrator.register_error_handler("invalid_handler", "not_callable")  # Non-callable

        # Test handler overwriting
        def replacement_handler(step, error, context):
            return False

        self.orchestrator.register_error_handler("valid_handler", replacement_handler)
        self.assertEqual(self.orchestrator.error_handlers["valid_handler"], replacement_handler)

    # Test 8: Switch device error handling
    @patch("subprocess.run")
    @patch("FactoryMode.output_manager.get_log_directory")
    def test_switch_device_error_handling(self, mock_get_log_dir, mock_subprocess):
        """Test error handling for switch device types."""
        # Set up mock log directory
        log_dir = Path(self.test_dir) / "logs"
        mock_get_log_dir.return_value = log_dir
        log_dir.mkdir(exist_ok=True)

        # Create switch configuration
        switch_config_file = self.create_test_config_file("switch")

        with patch("FactoryMode.output_manager.get_log_directory", return_value=log_dir):
            switch_orchestrator = FactoryFlowOrchestrator(switch_config_file)

        # Add switch_config to orchestrator with proper structure
        mock_switch_config = MagicMock()
        mock_switch_config.config = {
            "connection": {
                "switch": {
                    "bmc": {
                        "ip": "192.168.1.200",
                        "username": "admin",
                        "password": "test123",
                        "port": 22,
                    }
                }
            },
            "variables": {"nvdebug_path": "Error_Handler/nvdebug"},
        }
        switch_orchestrator.switch_config = mock_switch_config

        # Mock successful nvdebug execution
        mock_result = MagicMock()
        mock_result.stdout = "Switch NVDebug collection completed"
        mock_subprocess.return_value = mock_result

        # Create switch step
        step = FlowStep(
            name="switch_firmware_update",
            operation="update_switch_firmware",
            device_type=DeviceType.SWITCH,
            device_id="switch1",
            parameters={"firmware_path": "/test/switch_fw.bin"},
        )

        context = {
            "orchestrator": switch_orchestrator,
            "device_type": DeviceType.SWITCH,
            "device_id": "switch1",
        }

        # Execute error handler for switch
        test_error = RuntimeError("Switch firmware update failed")
        result = error_handler_collect_nvdebug_logs(step, test_error, context)

        # Verify error handler behavior for switch
        self.assertFalse(result)

        # Verify nvdebug was called with switch-specific parameters
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args[0][0]

        # Should contain switch-specific platform and baseboard
        self.assertIn("-t", call_args)
        platform_index = call_args.index("-t") + 1
        self.assertEqual(call_args[platform_index], "NVSwitch")

        self.assertIn("-b", call_args)
        baseboard_index = call_args.index("-b") + 1
        self.assertEqual(call_args[baseboard_index], "GB200 NVL NVSwitchTray")

    def test_nvdebug_handler_unsupported_device_type(self):
        """Handler should return False and log error when device type unsupported."""
        step = FlowStep(
            name="unsupported_device_step",
            operation="noop",
            device_type=DeviceType.POWER_SHELF,  # not supported by handler
            device_id="ps1",
            parameters={},
        )
        context = {"orchestrator": self.orchestrator}
        result = error_handler_collect_nvdebug_logs(step, RuntimeError("boom"), context)
        self.assertFalse(result)

    def test_nvdebug_handler_missing_orchestrator_in_context(self):
        """Handler should early-return False when orchestrator missing from context."""
        step = FlowStep(
            name="missing_ctx",
            operation="noop",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={},
        )
        result = error_handler_collect_nvdebug_logs(step, RuntimeError("boom"), context={})
        self.assertFalse(result)

    @patch("FactoryMode.TrayFlowFunctions.error_handlers.get_log_directory")
    @patch("subprocess.run")
    def test_nvdebug_skip_when_device_log_dir_exists(self, mock_subprocess, mock_get_log_dir):
        """If nvdebug log dir exists, handler should skip running nvdebug."""
        log_dir = Path(self.test_dir) / "logs"
        device_dir = log_dir / "nvdebug_logs_compute1"
        device_dir.mkdir(parents=True, exist_ok=True)
        mock_get_log_dir.return_value = log_dir

        # Ensure compute credentials are present
        mock_compute_config = MagicMock()
        mock_compute_config.config = {
            "connection": {"compute": {"bmc": {"ip": "1.1.1.1", "username": "u", "password": "p"}}}
        }
        self.orchestrator.compute_config = mock_compute_config

        step = FlowStep(
            name="already_collected",
            operation="noop",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={},
        )

        res = error_handler_collect_nvdebug_logs(step, RuntimeError("boom"), {"orchestrator": self.orchestrator})
        self.assertFalse(res)
        mock_subprocess.assert_not_called()

    @patch("FactoryMode.TrayFlowFunctions.error_handlers.get_log_directory")
    @patch("subprocess.run", side_effect=Exception("unexpected error"))
    def test_nvdebug_generic_exception_is_caught(self, _mock_subprocess, mock_get_log_dir):
        log_dir = Path(self.test_dir) / "logs"
        mock_get_log_dir.return_value = log_dir
        log_dir.mkdir(exist_ok=True)

        mock_compute_config = MagicMock()
        mock_compute_config.config = {
            "connection": {"compute": {"bmc": {"ip": "1.1.1.1", "username": "u", "password": "p"}}}
        }
        self.orchestrator.compute_config = mock_compute_config

        step = FlowStep(
            name="generic_exception",
            operation="noop",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={},
        )

        res = error_handler_collect_nvdebug_logs(step, RuntimeError("boom"), {"orchestrator": self.orchestrator})
        self.assertFalse(res)

    @patch("FactoryMode.TrayFlowFunctions.error_handlers.get_log_directory")
    @patch("subprocess.run")
    def test_nvdebug_os_inclusive_and_bmc_only_command_paths(self, mock_subprocess, mock_get_log_dir):
        log_dir = Path(self.test_dir) / "logs"
        mock_get_log_dir.return_value = log_dir
        log_dir.mkdir(exist_ok=True)

        # Case 1: OS creds present -> OS-inclusive command
        mock_compute_config = MagicMock()
        mock_compute_config.config = {
            "connection": {
                "compute": {
                    "bmc": {"ip": "1.1.1.1", "username": "u", "password": "p"},
                    "os": {"ip": "2.2.2.2", "username": "ou", "password": "op"},
                }
            }
        }
        self.orchestrator.compute_config = mock_compute_config

        step = FlowStep(
            name="os_inclusive",
            operation="noop",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            parameters={},
        )

        mock_result = MagicMock()
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result

        res = error_handler_collect_nvdebug_logs(step, RuntimeError("boom"), {"orchestrator": self.orchestrator})
        self.assertFalse(res)
        cmd = mock_subprocess.call_args[0][0]
        self.assertIn("-I", cmd)
        self.assertIn("-U", cmd)
        self.assertIn("-H", cmd)

        # Case 2: OS creds missing -> BMC-only command
        mock_compute_config.config["connection"]["compute"].pop("os", None)
        mock_subprocess.reset_mock()

        # Remove device-specific log dir created by the first call so handler does not short-circuit
        device_dir = log_dir / "nvdebug_logs_compute1"
        import shutil

        shutil.rmtree(device_dir, ignore_errors=True)

        res2 = error_handler_collect_nvdebug_logs(step, RuntimeError("boom2"), {"orchestrator": self.orchestrator})
        self.assertFalse(res2)
        cmd2 = mock_subprocess.call_args[0][0]
        self.assertNotIn("-I", cmd2)
        self.assertNotIn("-U", cmd2)
        self.assertNotIn("-H", cmd2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
