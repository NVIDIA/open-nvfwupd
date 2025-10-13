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
Shared mock classes for NVFWUPD Factory Mode testing.

This module provides standardized mock implementations that are used across
all test files to ensure consistency and maintainability.

Usage:
    from FactoryMode.TestFiles.test_mocks import MockFlow, standard_orchestrator_mocker
"""

import logging
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Tuple
from unittest.mock import MagicMock, patch

from FactoryMode.flow_types import DeviceType

if TYPE_CHECKING:
    from FactoryMode.factory_flow_orchestrator import FactoryFlowOrchestrator


class MockFlow:
    """Standard mock flow implementation for testing.

    This class provides a consistent interface for all factory flow testing,
    including standard operations for success/failure testing, error handling,
    and performance testing.
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.execution_log = []  # For tracking execution in performance tests

    # === BASIC TESTING OPERATIONS ===
    def pass_test(self, message: str = "Test passed", **kwargs) -> bool:
        """Standard operation that always succeeds."""
        self.execution_log.append(f"pass_test_{self.device_id}")
        return True

    def fail_test(self, message: str = "Test failed", **kwargs) -> bool:
        """Standard operation that always fails."""
        self.execution_log.append(f"fail_test_{self.device_id}")
        return False

    def exception_operation(self, **kwargs) -> bool:
        """Standard operation that raises an exception for error testing."""
        self.execution_log.append(f"exception_operation_{self.device_id}")
        raise RuntimeError("Test exception for error handler testing")

    # === CONDITIONAL OPERATIONS ===
    def conditional_operation(self, should_fail: bool = False, **kwargs) -> bool:
        """Operation that can succeed or fail based on parameters."""
        self.execution_log.append(f"conditional_operation_{self.device_id}_fail={should_fail}")
        if should_fail:
            raise RuntimeError("Conditional operation failed")
        return True

    # === DEVICE-SPECIFIC OPERATIONS ===
    def check_bmc_version(self, **kwargs) -> Dict[str, Any]:
        """Mock BMC version check for compute devices."""
        self.execution_log.append(f"check_bmc_version_{self.device_id}")
        return {"version": "1.0.0", "device_id": self.device_id}

    def check_switch_version(self, **kwargs) -> Dict[str, Any]:
        """Mock switch version check for switch devices."""
        self.execution_log.append(f"check_switch_version_{self.device_id}")
        return {"version": "2.0.0", "device_id": self.device_id}

    def check_pmc_version(self, **kwargs) -> Dict[str, Any]:
        """Mock PMC version check for power shelf devices."""
        self.execution_log.append(f"check_pmc_version_{self.device_id}")
        return {"version": "3.0.0", "device_id": self.device_id}

    # === PERFORMANCE TESTING OPERATIONS ===
    def slow_operation(self, delay: float = 0.1, **kwargs) -> bool:
        """Operation with configurable delay for performance testing."""
        thread_id = threading.current_thread().ident
        self.execution_log.append(f"slow_operation_start_{self.device_id}_{thread_id}")
        time.sleep(delay)
        self.execution_log.append(f"slow_operation_end_{self.device_id}_{thread_id}")
        return True

    # === VARIABLE EXPANSION TESTING ===
    def variable_test_operation(self, expanded_param: str = None, **kwargs) -> bool:
        """Special operation for variable expansion testing."""
        self.execution_log.append(f"variable_test_operation_{self.device_id}_param={expanded_param}")
        return True

    # === BACKWARD COMPATIBILITY ALIASES ===
    def test_operation(self, **kwargs) -> bool:
        print(f"DEBUG: MockFlow.test_operation called for device_id={self.device_id}")
        thread_id = threading.current_thread().ident
        self.execution_log.append(f"test_operation_{self.device_id}_{thread_id}")
        return True

    def fail_operation(self, **kwargs) -> bool:
        """Alias for fail_test for backward compatibility."""
        return self.fail_test(**kwargs)

    def failing_operation(self, **kwargs) -> Dict[str, Any]:
        """Alias for exception_operation with Dict return type compatibility."""
        self.exception_operation(**kwargs)
        return {}  # Never reached due to exception


class MockUtils:
    """
    Mock implementation of Utils (Redfish utilities) for testing device operations.

    This mock replaces the real Utils class to avoid actual network calls during tests.
    All device integration tests should use this instead of creating their own mocks.

    Usage:
        # In test setup:
        with patch('FactoryMode.TrayFlowFunctions.compute_factory_flow_functions.Utils', MockUtils):
            flow = ComputeFactoryFlow(config, "compute1")
    """

    def __init__(
        self,
        dut_ip: str = None,
        dut_username: str = None,
        dut_password: str = None,
        dut_service_port: int = 443,
        dut_service_type: str = "https",
        logger: logging.Logger = None,
    ):
        """Initialize MockUtils with the same signature as real Utils."""
        # Store init params for assertions if needed
        self.dut_ip = dut_ip
        self.dut_username = dut_username
        self.dut_password = dut_password
        self.dut_service_port = dut_service_port
        self.dut_service_type = dut_service_type
        self.logger = logger or logging.getLogger(__name__)

        # Create mocks for all Utils methods
        self.get_request = MagicMock(name="get_request")
        self.post_request = MagicMock(name="post_request")
        self.patch_request = MagicMock(name="patch_request")
        self.post_upload_request = MagicMock(name="post_upload_request")
        self.monitor_job = MagicMock(name="monitor_job")
        self.ping_dut = MagicMock(name="ping_dut")

        # Set default successful return values
        self.get_request.return_value = (True, {})
        self.post_request.return_value = (True, {})
        self.patch_request.return_value = (True, {})
        self.post_upload_request.return_value = (
            True,
            {"Location": "/redfish/v1/TaskService/Tasks/0"},
        )
        self.monitor_job.return_value = (
            True,
            {"TaskState": "Completed", "PercentComplete": 100},
        )
        self.ping_dut.return_value = True

        # Track calls for debugging
        self._all_calls = []

    def reset_all_mocks(self):
        """Reset all mock objects to clear call history."""
        self.get_request.reset_mock()
        self.post_request.reset_mock()
        self.patch_request.reset_mock()
        self.post_upload_request.reset_mock()
        self.monitor_job.reset_mock()
        self.ping_dut.reset_mock()
        self._all_calls = []

    def configure_response(self, method_name: str, return_value: Any = None, side_effect: Any = None):
        """
        Configure a specific method's response.

        Args:
            method_name: Name of the method to configure (e.g., 'get_request')
            return_value: Value to return when method is called
            side_effect: Side effect (exception or callable) for the method
        """
        method = getattr(self, method_name, None)
        if method and isinstance(method, MagicMock):
            if return_value is not None:
                method.return_value = return_value
            if side_effect is not None:
                method.side_effect = side_effect
        else:
            raise ValueError(f"Method {method_name} not found or not a mock")

    @staticmethod
    def compare_versions(current_version, expected_version, operator="=="):
        """Mock implementation of static compare_versions method."""
        # Simple string comparison for testing
        if operator == "==":
            return current_version == expected_version
        elif operator == "!=":
            return current_version != expected_version
        elif operator == ">":
            return current_version > expected_version
        elif operator == ">=":
            return current_version >= expected_version
        elif operator == "<":
            return current_version < expected_version
        elif operator == "<=":
            return current_version <= expected_version
        else:
            raise ValueError(f"Invalid operator: {operator}")


def standard_device_flow_mocker(orchestrator):
    """Standard function to apply device flow mocking to an orchestrator.

    Args:
        orchestrator: The FactoryFlowOrchestrator instance to mock

    Returns:
        tuple: (mock_compute_flow, mock_switch_flow, mock_power_shelf_flow)
    """
    # Create standard mock flows
    mock_compute_flow = MockFlow("compute1")
    mock_switch_flow = MockFlow("switch1")
    mock_power_shelf_flow = MockFlow("ps1")

    # Standard device flow mocking function
    def mock_get_device_flow(device_type, device_id):
        """Standard device flow factory for testing."""
        if device_type == DeviceType.COMPUTE:
            return mock_compute_flow
        elif device_type == DeviceType.SWITCH:
            return mock_switch_flow
        elif device_type == DeviceType.POWER_SHELF:
            return mock_power_shelf_flow
        else:
            raise ValueError(f"Unsupported device type: {device_type}")

    # Apply the mock to the orchestrator
    orchestrator._get_device_flow = mock_get_device_flow

    return mock_compute_flow, mock_switch_flow, mock_power_shelf_flow


def standard_error_handler_mocker(orchestrator):
    """Standard function to create error handler mocking setup.

    Args:
        orchestrator: The FactoryFlowOrchestrator instance to register handlers on

    Returns:
        tuple: (test_handler_calls_list, error_handler_function)
    """
    test_handler_calls = []

    def test_error_handler(step, error, context):
        """Standard error handler that logs calls and succeeds."""
        test_handler_calls.append(
            {
                "step_name": step.name if hasattr(step, "name") else str(step),
                "error_type": type(error).__name__,
                "error_message": str(error),
                "context": context,
            }
        )
        return True  # Continue flow execution

    orchestrator.register_error_handler("test_handler", test_error_handler)

    return test_handler_calls, test_error_handler


def standard_orchestrator_mocker(
    config_path: str = "FactoryMode/TestFiles/test_config.yaml",
    test_name: str = "default",
) -> Tuple["FactoryFlowOrchestrator", "MockFlow", "MockFlow", "MockFlow", Path, Callable]:
    """Standard function to create a fully mocked FactoryFlowOrchestrator with real temporary files.

    This function provides complete test isolation by:
    - Creating real temporary directories for all file operations
    - Using real files for logging, JSON progress tracking, SOL logs, etc.
    - Setting up standard device flows for all device types
    - Providing cleanup function for proper teardown

    Args:
        config_path: Path to test configuration file
        test_name: Identifier for temporary directory (helps with debugging)

    Returns:
        tuple: (orchestrator, mock_compute_flow, mock_switch_flow, mock_power_shelf_flow, temp_dir, cleanup_function)

    Usage:
        def setUp(self):
            self.orchestrator, self.mock_compute_flow, self.mock_switch_flow, self.mock_power_shelf_flow, self.temp_dir, self.cleanup = standard_orchestrator_mocker(test_name="my_test")

        def tearDown(self):
            self.cleanup()
    """
    # Import here to avoid circular imports
    from FactoryMode.factory_flow_orchestrator import FactoryFlowOrchestrator

    # Create real temporary directory for all file operations
    temp_dir = Path(tempfile.mkdtemp(prefix=f"nvfwupd_test_{test_name}_"))

    # Create logs subdirectory
    logs_dir = temp_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Cleanup function
    def cleanup():
        """Clean up temporary directory and all contents."""
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Use real temporary directory for all logging and file operations
    with patch("FactoryMode.output_manager.get_log_directory", return_value=logs_dir):
        orchestrator = FactoryFlowOrchestrator(config_path)

    # Apply standard device flow mocking (only mock device hardware, not file operations)
    mock_compute_flow, mock_switch_flow, mock_power_shelf_flow = standard_device_flow_mocker(orchestrator)

    return (
        orchestrator,
        mock_compute_flow,
        mock_switch_flow,
        mock_power_shelf_flow,
        temp_dir,
        cleanup,
    )


def standard_orchestrator_with_error_handler_mocker(
    config_path: str = "FactoryMode/TestFiles/test_config.yaml",
    test_name: str = "default",
) -> Tuple[
    "FactoryFlowOrchestrator",
    "MockFlow",
    "MockFlow",
    "MockFlow",
    list,
    callable,
    Path,
    Callable,
]:
    """Standard function to create a fully mocked FactoryFlowOrchestrator with error handler and real temp files.

    This extends standard_orchestrator_mocker by also setting up error handler mocking.

    Args:
        config_path: Path to test configuration file
        test_name: Identifier for temporary directory

    Returns:
        tuple: (orchestrator, mock_compute_flow, mock_switch_flow, mock_power_shelf_flow, test_handler_calls, test_error_handler, temp_dir, cleanup_function)

    Usage:
        def setUp(self):
            self.orchestrator, self.mock_compute_flow, self.mock_switch_flow, self.mock_power_shelf_flow, self.test_handler_calls, _, self.temp_dir, self.cleanup = standard_orchestrator_with_error_handler_mocker(test_name="my_test")

        def tearDown(self):
            self.cleanup()
    """
    (
        orchestrator,
        mock_compute_flow,
        mock_switch_flow,
        mock_power_shelf_flow,
        temp_dir,
        cleanup,
    ) = standard_orchestrator_mocker(config_path, test_name)

    # Add error handler mocking
    test_handler_calls, test_error_handler = standard_error_handler_mocker(orchestrator)

    return (
        orchestrator,
        mock_compute_flow,
        mock_switch_flow,
        mock_power_shelf_flow,
        test_handler_calls,
        test_error_handler,
        temp_dir,
        cleanup,
    )


def get_temp_file_path(temp_dir: Path, filename: str) -> str:
    """Helper function to create a temp file path within the test temporary directory.

    This should be used for all file operations in tests (SOL logs, JSON files, etc.)
    to ensure consistent temporary file handling.

    Args:
        temp_dir: The temporary directory from standard_orchestrator_mocker
        filename: The desired filename (e.g., "test_sol.log", "custom_progress.json")

    Returns:
        str: Full path to the temporary file

    Usage:
        def test_sol_logging(self):
            log_file_path = get_temp_file_path(self.temp_dir, "test_sol.log")
            result = self.flow.start_sol_logging(log_file_path)
    """
    return str(temp_dir / filename)


class MockFactoryFlowOrchestrator:
    """
    Drop-in replacement for FactoryFlowOrchestrator that automatically handles temp directories.

    Usage:
        # Instead of: orchestrator = FactoryFlowOrchestrator(config_path)
        orchestrator = MockFactoryFlowOrchestrator(config_path)

        # Everything else works exactly the same
        steps = orchestrator.load_flow_from_yaml("flow.yaml")
        result = orchestrator.execute_flow(steps)

        # Automatic cleanup when done
        orchestrator.cleanup()
    """

    def __init__(self, config_path: str, test_name: str = "mock_orchestrator"):
        """Initialize with automatic temp directory setup."""
        from FactoryMode.factory_flow_orchestrator import FactoryFlowOrchestrator

        # Create temp directory for this orchestrator instance
        self._temp_dir = Path(tempfile.mkdtemp(prefix=f"nvfwupd_mock_{test_name}_"))
        self._logs_dir = self._temp_dir / "logs"
        self._logs_dir.mkdir(exist_ok=True)

        # Create a permanent patch for get_log_directory
        self._log_dir_patcher = patch("FactoryMode.output_manager.get_log_directory", return_value=self._logs_dir)
        self._log_dir_patcher.start()

        # Create the real orchestrator with patched log directory
        self._orchestrator = FactoryFlowOrchestrator(config_path)

        # Store cleanup function
        self._cleanup_func = lambda: shutil.rmtree(self._temp_dir, ignore_errors=True)

    def setup_device_mocking(self) -> Tuple["MockFlow", "MockFlow", "MockFlow"]:
        """Set up standard device flow mocking and return mock flow instances."""
        mock_compute_flow, mock_switch_flow, mock_power_shelf_flow = standard_device_flow_mocker(self._orchestrator)

        # Store references for easy access
        self.mock_compute_flow = mock_compute_flow
        self.mock_switch_flow = mock_switch_flow
        self.mock_power_shelf_flow = mock_power_shelf_flow

        return mock_compute_flow, mock_switch_flow, mock_power_shelf_flow

    def setup_error_handler_mocking(self) -> Tuple[list, callable]:
        """Set up standard error handler mocking."""
        test_handler_calls, test_error_handler = standard_error_handler_mocker(self._orchestrator)

        # Store references for easy access
        self.test_handler_calls = test_handler_calls
        self.test_error_handler = test_error_handler

        return test_handler_calls, test_error_handler

    def cleanup(self):
        """Clean up temp directory and patches."""
        # Stop the log directory patch
        if hasattr(self, "_log_dir_patcher"):
            self._log_dir_patcher.stop()

        # Clean up temp directory
        self._cleanup_func()

    def __getattr__(self, name):
        """Delegate all other attributes to the real orchestrator."""
        # Avoid infinite recursion - only delegate if _orchestrator is already set
        if "_orchestrator" not in self.__dict__:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        return getattr(self.__dict__["_orchestrator"], name)

    def __setattr__(self, name, value):
        # Allow setting internal attributes on the wrapper itself
        if name.startswith("_"):
            # All private attributes stay on the wrapper
            super().__setattr__(name, value)
        else:
            # Public attributes get delegated to the orchestrator
            # But check if _orchestrator exists first to avoid recursion
            if "_orchestrator" in self.__dict__:
                setattr(self.__dict__["_orchestrator"], name, value)
            else:
                # During __init__, before _orchestrator is set
                super().__setattr__(name, value)

    def __del__(self):
        """Automatic cleanup on destruction."""
        try:
            self.cleanup()
        except Exception:
            pass
