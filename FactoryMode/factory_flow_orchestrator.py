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
Factory Flow Orchestrator - Unified Multi-Device Factory Automation Framework

This module provides the core orchestration capabilities for automated factory flows
across compute nodes, network switches, and power shelves. It implements a unified
execution engine that handles complex flow control, error recovery, parallel execution,
and comprehensive progress tracking.

Key Features:
    - **Unified Execution**: Single engine for all device types and step types
    - **Dynamic Flow Control**: Jump logic with conditional branching and loop prevention
    - **Parallel Execution**: Concurrent operations with thread-safe progress tracking
    - **Error Recovery**: Optional flows, retry mechanisms, and custom error handlers
    - **Progress Tracking**: Real-time updates with GUI and non-GUI output modes
    - **YAML Configuration**: Declarative flow definitions with variable expansion

Architecture Overview:
    The orchestrator uses a three-tier architecture:

    1. **Entry Layer**: YAML loading, variable expansion, flow object creation
    2. **Orchestration Layer**: Unified execution engine with flow routing
    3. **Device Layer**: Hardware-specific operations via factory flow classes

Example:
    Basic orchestrator usage:

    >>> from FactoryMode.factory_flow_orchestrator import FactoryFlowOrchestrator
    >>> orchestrator = FactoryFlowOrchestrator("config.yaml")
    >>>
    >>> # Load flow from YAML
    >>> steps = orchestrator.load_flow_from_yaml("compute_flow.yaml")
    >>>
    >>> # Execute with progress tracking
    >>> success = orchestrator.execute_flow(steps)
    >>> print(f"Flow completed successfully: {success}")

    Advanced usage with custom error handlers:

    >>> def custom_recovery(step, error, context):
    ...     print(f"Handling error in {step.name}: {error}")
    ...     return True  # Continue flow execution
    >>>
    >>> orchestrator.register_error_handler("custom_recovery", custom_recovery)
    >>> success = orchestrator.execute_flow(steps)

Supported Device Types:
    - **Compute Nodes**: BMC operations, firmware updates, boot sequences, SOL logging
    - **Network Switches**: Firmware updates, configuration management, OS operations
    - **Power Shelves**: PSU management, firmware updates, health monitoring

Flow Types:
    - **FlowStep**: Individual operation on a specific device
    - **ParallelFlowStep**: Multiple operations executed concurrently
    - **IndependentFlow**: Self-contained flow with isolated execution context

Configuration:
    Flows are defined in YAML files with support for:
    - Variable substitution (${variable_name})
    - Optional flows for error recovery
    - Jump conditions for conditional execution
    - Retry policies and timeout configuration
    - Output mode selection (GUI/console/filtered)

Progress Tracking:
    Comprehensive execution tracking including:
    - Step-level timing and retry counts
    - Jump operations and optional flow triggers
    - Error message collection and propagation
    - Thread-safe concurrent access
    - JSON output for integration and analysis

Thread Safety:
    All operations are thread-safe for concurrent execution:
    - Progress tracking uses RLock protection
    - Device flow instances are cached and reused safely
    - Error collection is isolated per step execution
    - GUI updates are synchronized across parallel flows

Error Handling:
    Multi-level error handling system:
    - Step-level error handlers for recovery attempts
    - Optional flows for complex recovery scenarios
    - Flow-level error handlers for final logging/cleanup
    - Custom error handler registration and execution

See Also:
    flow_types: Step and flow type definitions
    flow_progress_tracker: Progress tracking and JSON output
    TrayFlowFunctions: Device-specific operation implementations

Authors:
    NVIDIA Corporation Factory Automation Team

License:
    Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
"""
import concurrent.futures
import inspect
import os
import re
import threading
import time
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Union

import yaml
from rich.console import Group
from rich.live import Live
from rich.panel import Panel

from FactoryMode.flow_progress_tracker import FlowProgressTracker
from FactoryMode.flow_types import DeviceType, FlowStep, IndependentFlow, OutputMode, ParallelFlowStep
from FactoryMode.output_manager import (
    OutputModeManager,
    get_log_directory,
    setup_logging,
    start_collecting_errors,
    stop_collecting_errors,
)

# Import the following for flow testing with prints
# Import error handlers for global namespace availability
from FactoryMode.TrayFlowFunctions import error_handlers

# Import the following for flow testing with actual device functions
from FactoryMode.TrayFlowFunctions.compute_factory_flow_functions import (
    ComputeFactoryFlow,
    ComputeFactoryFlowConfig,
)
from FactoryMode.TrayFlowFunctions.power_shelf_factory_flow_functions import (
    PowerShelfFactoryFlow,
    PowerShelfFactoryFlowConfig,
)
from FactoryMode.TrayFlowFunctions.switch_factory_flow_functions import SwitchFactoryFlow, SwitchFactoryFlowConfig

# RealTimeElapsedColumn moved to output_manager.py


class FactoryFlowOrchestrator:
    """Orchestrates factory flow operations across different device types."""

    def __init__(self, config_path: str = "factory_flow_config.yaml"):
        """
        Initialize the orchestrator.

        Args:
            config_path (str): Path to the YAML configuration file
        """
        self.config_path = config_path
        # Lazy initialization - configs created only when first accessed
        self._compute_config = None
        self._switch_config = None
        self._power_shelf_config = None

        # Thread safety for lazy initialization
        self._config_lock = Lock()

        # Load variables from config first
        self.variables = self._load_variables()

        # Get output mode
        output_mode_str = self.variables.get("output_mode", "gui")

        # Map string output mode to enum
        output_mode_map = {
            "none": OutputMode.NONE,
            "gui": OutputMode.GUI,
            "log": OutputMode.LOG,
            "json": OutputMode.JSON,
            "all": OutputMode.LOG,  # Legacy: 'all' maps to 'log'
        }
        self.output_mode = output_mode_map.get(output_mode_str, OutputMode.GUI)

        # Set up logging - enable console output in LOG mode
        self.console_output_enabled = self.output_mode == OutputMode.LOG
        self.logger = setup_logging("factory_flow_orchestrator", console_output=self.console_output_enabled)

        # Initialize device flows
        self.compute_flows: Dict[str, ComputeFactoryFlow] = {}
        self.switch_flows: Dict[str, SwitchFactoryFlow] = {}
        self.power_shelf_flows: Dict[str, PowerShelfFactoryFlow] = {}

        # Initialize error handlers
        self.error_handlers: Dict[str, Callable] = {}
        self.default_error_handler: Optional[str] = None

        # Initialize optional flows
        self.optional_flows: Dict[str, List[Union[FlowStep, ParallelFlowStep, IndependentFlow]]] = {}

        # Initialize progress tracking with thread safety
        self.progress_lock = Lock()
        self.table_lock = Lock()
        self.steps_lock = Lock()
        self._thread_local = threading.local()

        # Initialize output manager first (centralized output control)
        json_path = get_log_directory() / "flow_progress.json"
        self.output_manager = OutputModeManager(
            mode=self.output_mode,
            log_directory=get_log_directory(),
            json_file_path=json_path,
            logger=self.logger,
        )

        # Initialize flow progress tracker with output manager for callbacks
        self.progress_tracker = FlowProgressTracker(json_path, output_manager=self.output_manager)

        # Load error handlers from config
        self._load_error_handlers()

    @property
    def compute_config(self):
        """Thread-safe lazy initialization of compute configuration."""
        if self._compute_config is None:
            with self._config_lock:
                # Double-check pattern to prevent race conditions
                if self._compute_config is None:
                    self._compute_config = ComputeFactoryFlowConfig(self.config_path)
        return self._compute_config

    @compute_config.setter
    def compute_config(self, value):
        """Allow setting compute config (needed for tests)."""
        self._compute_config = value

    @property
    def switch_config(self):
        """Thread-safe lazy initialization of switch configuration."""
        if self._switch_config is None:
            with self._config_lock:
                # Double-check pattern to prevent race conditions
                if self._switch_config is None:
                    self._switch_config = SwitchFactoryFlowConfig(self.config_path)
        return self._switch_config

    @switch_config.setter
    def switch_config(self, value):
        """Allow setting switch config (needed for tests)."""
        self._switch_config = value

    @property
    def power_shelf_config(self):
        """Thread-safe lazy initialization of power shelf configuration."""
        if self._power_shelf_config is None:
            with self._config_lock:
                # Double-check pattern to prevent race conditions
                if self._power_shelf_config is None:
                    self._power_shelf_config = PowerShelfFactoryFlowConfig(self.config_path)
        return self._power_shelf_config

    @power_shelf_config.setter
    def power_shelf_config(self, value):
        """Allow setting power shelf config (needed for tests)."""
        self._power_shelf_config = value

    def _get_default_retry_count(self) -> int:
        """
        Get default retry count without triggering device config creation.

        Returns:
            int: Default retry count value
        """
        # First try to get from variables
        if "default_retry_count" in self.variables:
            try:
                return int(self.variables["default_retry_count"])
            except (ValueError, TypeError):
                self.logger.warning(
                    f"Invalid default_retry_count in variables: {self.variables['default_retry_count']}"
                )

        # If compute_config is already initialized, check it (for test compatibility)
        if self._compute_config is not None:
            settings = self._compute_config.config.get("settings", {})
            if "default_retry_count" in settings:
                return settings["default_retry_count"]

        # Fallback: load directly from main config file (avoid triggering initialization)
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                settings = config.get("settings", {})
                if "default_retry_count" in settings:
                    return settings["default_retry_count"]
        except Exception as e:
            self.logger.warning(f"Could not load default_retry_count from config: {e}")

        # Final fallback - match original behavior (was probably 2 from compute config defaults)
        return 2

    def _load_error_handlers(self):
        """Load error handlers from configuration."""
        # Register built-in error handlers
        self.register_error_handler("default_error_handler", self._default_error_handler)

    def register_error_handler(self, name: str, handler: Callable):
        """
        Register an error handler function.

        Args:
            name (str): Name of the error handler
            handler (Callable): Error handler function

        Raises:
            ValueError: If name is empty or None
            TypeError: If handler is not callable or None
        """
        # Validate name
        if not name:
            raise ValueError("Error handler name cannot be empty or None")

        # Validate handler
        if handler is None:
            raise TypeError("Error handler cannot be None")

        if not callable(handler):
            raise TypeError("Error handler must be callable")

        self.error_handlers[name] = handler

    def _default_error_handler(self, step: FlowStep, error: Exception, _context: Dict[str, Any]) -> bool:
        """
        Default error handler implementation.

        Args:
            step (FlowStep): The step that failed
            error (Exception): The error that occurred
            context (Dict[str, Any]): Additional context

        Returns:
            bool: True to continue flow, False to abort
        """
        self.logger.error(f"{step.device_id} - Step {step.name or step.operation} failed: {str(error)}")
        return False

    def _execute_error_handler(self, step: FlowStep, error: Exception, context: Dict[str, Any]) -> bool:
        """
        Execute the appropriate error handler for a step.
        Only executes step-specific error handlers, not flow-level handlers.

        Error handlers are diagnostic only - they analyze failures but do not attempt recovery.
        Recovery should be handled by optional flows (execute_on_fail) before error handlers run.

        Args:
            step (FlowStep): The step that failed
            error (Exception): The error that occurred
            context (Dict[str, Any]): Additional context

        Returns:
            bool: Typically False (abort flow) as error handlers are diagnostic only.
                  True in rare cases where handler explicitly indicates flow can continue.
        """
        # Only use step-specific error handler (no flow-level fallback)
        handler_name = step.execute_on_error

        if not handler_name:
            # No step-specific handler, return False to continue with flow failure
            self.logger.info(
                f"{step.device_id} - No step-specific error handler for step {step.name or step.operation}"
            )
            return False

        handler = self.error_handlers.get(handler_name)
        if not handler:
            self.logger.error(f"{step.device_id} - Step error handler '{handler_name}' not found")
            return False

        try:
            result = handler(step, error, context)
            return result
        except Exception as e:
            self.logger.error(f"{step.device_id} - Step error handler '{handler_name}' failed: {str(e)}")
            return False

    def _execute_flow_error_handler(self, flow_name: str, error_message: str) -> None:
        """
        Execute the flow-level error handler for final log collection after flow failure.
        This runs AFTER flow progress tracking is finalized.

        Args:
            flow_name (str): Name of the failed flow
            error_message (str): Final error message from flow failure
        """
        if not self.default_error_handler:
            self.logger.info(f"No flow-level error handler configured for flow {flow_name}")
            return

        handler = self.error_handlers.get(self.default_error_handler)
        if not handler:
            self.logger.error(f"Flow-level error handler '{self.default_error_handler}' not found")
            return

        # Create context for flow-level error handler
        context = {
            "flow_name": flow_name,
            "error_message": error_message,
            "orchestrator": self,
            "is_flow_level": True,
        }

        # Create a dummy error object for the handler
        error = RuntimeError(f"Flow {flow_name} failed: {error_message}")

        try:
            self.logger.info(
                f"Executing flow-level error handler '{self.default_error_handler}' for failed flow {flow_name}"
            )
            # Note: Flow-level handlers are for log collection, result doesn't affect flow outcome
            handler(None, error, context)  # Pass None for step since this is flow-level
            self.logger.info(f"Flow-level error handler '{self.default_error_handler}' completed")
        except Exception as e:
            self.logger.error(f"Flow-level error handler '{self.default_error_handler}' failed: {str(e)}")
            # Don't re-raise - flow is already failed, this is just for log collection

    def _handle_step_failure_with_error_handler(
        self,
        *,
        step: FlowStep,
        retry_attempts: int,
        optional_flow_executed: str = None,
        original_exception: Exception = None,
    ) -> bool:
        """
        Handle step failure by executing the appropriate error handler after retries and optional flows are exhausted.

        Args:
            step (FlowStep): The step that failed
            retry_attempts (int): Number of retry attempts that were made
            optional_flow_executed (str, optional): Name of optional flow that was executed, if any
            original_exception (Exception, optional): The original exception that caused the step to fail

        Returns:
            bool: True if error handler says to continue flow, False to abort
        """
        # Create enhanced context for error handler
        context = {
            "device_type": step.device_type,
            "device_id": step.device_id,
            "operation": step.operation,
            "parameters": step.parameters,
            "orchestrator": self,
            "retry_attempts": retry_attempts,
            "optional_flow_executed": optional_flow_executed,
        }

        # Use original exception if provided, otherwise create descriptive error message
        if original_exception:
            error = original_exception
        else:
            # Create descriptive error message (fallback for cases where original exception not available)
            if optional_flow_executed:
                error_message = (
                    f"Step {step.name or step.operation} failed after "
                    f"{retry_attempts} retries and optional flow {optional_flow_executed}"
                )
            else:
                error_message = f"Step {step.name or step.operation} failed after {retry_attempts} retries"

            error = RuntimeError(error_message)

        # Execute error handler (diagnostic only - does not attempt recovery)
        self.logger.info(f"{step.device_id} - Executing error handler for step {step.name or step.operation}")
        handler_result = self._execute_error_handler(step, error, context)

        # Error handlers are diagnostic only and typically return False
        # Only return True if handler explicitly indicates flow should continue (rare case)
        if handler_result:
            self.logger.info(
                f"{step.device_id} - Error handler indicates flow can continue for step {step.name or step.operation}"
            )
            return True

        # Normal case: error handler completed diagnostic analysis, flow cannot continue
        self.logger.info(
            f"{step.device_id} - Error handler diagnostic analysis complete for step {step.name or step.operation}, aborting flow"
        )
        return False

    def _get_last_step_error_message(self, flow_name: str) -> str:
        """
        Get the actual error message from the last failed step in a flow.

        Args:
            flow_name (str): Name of the flow to check

        Returns:
            str: Error message from last failed step, or generic message if not found
        """
        flow_info = self.progress_tracker.get_flow_info(flow_name)
        if flow_info and flow_info.steps_executed:
            last_step = flow_info.steps_executed[-1]
            if not last_step.final_result:
                # Use the step's error message if available
                if last_step.error_message:
                    return f"Step '{last_step.step_name}' failed: {last_step.error_message}"
                # Use collected error messages if available
                if hasattr(last_step, "error_messages") and last_step.error_messages:
                    return f"Step '{last_step.step_name}' failed: {last_step.error_messages[-1]}"
                # Use step name only if no error details
                return f"Step '{last_step.step_name}' failed"

        # Fallback to generic message if no step info available
        return "Flow failed due to step failure"

    def _get_device_flow(
        self, device_type: DeviceType, device_id: str
    ) -> Union[ComputeFactoryFlow, SwitchFactoryFlow, PowerShelfFactoryFlow]:
        """
        Get or create a flow instance for the specified device.

        Args:
            device_type (DeviceType): Type of device
            device_id (str): Device identifier

        Returns:
            Union[ComputeFactoryFlow, SwitchFactoryFlow, PowerShelfFactoryFlow]: Flow instance
        """
        if device_type == DeviceType.COMPUTE:
            if device_id not in self.compute_flows:
                self.compute_flows[device_id] = ComputeFactoryFlow(
                    self.compute_config, device_id, console_output=self.console_output_enabled
                )
            return self.compute_flows[device_id]
        if device_type == DeviceType.SWITCH:
            if device_id not in self.switch_flows:
                self.switch_flows[device_id] = SwitchFactoryFlow(
                    self.switch_config, device_id, console_output=self.console_output_enabled
                )
            return self.switch_flows[device_id]
        if device_type == DeviceType.POWER_SHELF:
            if device_id not in self.power_shelf_flows:
                self.power_shelf_flows[device_id] = PowerShelfFactoryFlow(self.power_shelf_config, device_id)
            return self.power_shelf_flows[device_id]
        raise ValueError(f"Unsupported device type: {device_type}")

    def execute_step(self, step: FlowStep) -> bool:
        """
        Execute a single flow step.

        Args:
            step (FlowStep): Step to execute

        Returns:
            bool: True if step was successful, False otherwise
        """
        step_name = step.name or step.operation
        self.logger.info(f"{step.device_id} - Executing step: {step_name} on {step.device_type.value}")

        try:
            if step.operation == "execute_independent_flows":
                # Handle independent flows execution
                flows = step.parameters.get("flows", [])
                return self.execute_parallel_flows(flows)

            flow = self._get_device_flow(step.device_type, step.device_id)
            operation = getattr(flow, step.operation)

            # Execute operation with parameters
            result = operation(**step.parameters)

            return result
        except Exception as e:
            self.logger.error(f"{step.device_id} - Error executing step {step_name}: {str(e)}")
            # Store this as the last exception for potential error handler use
            step.last_exception = e
            # Don't call error handler here - let the retry logic handle it
            return False

    def execute_parallel_steps(self, parallel_step: ParallelFlowStep) -> bool:
        """
        Execute a group of steps in parallel.

        Args:
            parallel_step (ParallelFlowStep): Group of steps to execute in parallel

        Returns:
            bool: True if all steps were successful, False otherwise
        """
        step_name = parallel_step.name or "Parallel Steps"
        self.logger.info(f"Executing parallel steps: {step_name}")

        max_workers = parallel_step.max_workers or len(parallel_step.steps)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all steps to the executor
            future_to_step = {executor.submit(self.execute_step, step): step for step in parallel_step.steps}

            # Wait for all steps to complete
            success = True
            for future in concurrent.futures.as_completed(future_to_step):
                step = future_to_step[future]
                try:
                    if not future.result():
                        success = False
                        self.logger.error(f"Step {step.name or step.operation} failed")
                except Exception as e:
                    success = False
                    self.logger.error(f"Step {step.name or step.operation} raised an exception: {str(e)}")

        if parallel_step.wait_after_seconds > 0:
            self.logger.info(f"Waiting {parallel_step.wait_after_seconds} seconds after parallel steps")
            time.sleep(parallel_step.wait_after_seconds)

        return success

    def execute_flow(self, steps: List[Union[FlowStep, ParallelFlowStep, IndependentFlow]]) -> bool:
        """
        Unified execution engine entry point for all factory flow step types.

        This method serves as the primary interface to the unified execution engine,
        providing a single entry point for executing sequences of FlowStep, ParallelFlowStep,
        and IndependentFlow objects. All step types are processed through the same unified
        execution path, ensuring feature consistency and eliminating dual code paths.

        ## Unified Execution Architecture

        The method implements the **step wrapping strategy** from the unified execution engine:

        ### **Step Type Processing**
        1. **FlowStep**: Individual operations wrapped in IndependentFlow containers
        2. **ParallelFlowStep**: Parallel operations wrapped in IndependentFlow containers
        3. **IndependentFlow**: Container flows executed directly, potentially in parallel

        ### **Consecutive IndependentFlow Optimization**
        Multiple consecutive IndependentFlow objects are automatically batched for
        parallel execution via `execute_parallel_flows()`, improving performance while
        maintaining execution order for mixed step types.

        ### **Feature Consistency Guarantee**
        All factory flow features work identically across step types:
        - **Optional Flows**: `execute_optional_flow` triggers work for all step types
        - **Jump Logic**: `jump_on_success` and `jump_on_failure` work uniformly
        - **Retry Mechanisms**: `retry_count` and retry logic applied consistently
        - **Error Handling**: `execute_on_error` handlers called uniformly
        - **Progress Tracking**: All steps tracked with StepExecution objects

        ## Execution Flow

        ```
        execute_flow(steps)
        ├── Group consecutive IndependentFlows → execute_parallel_flows()
        ├── Wrap FlowStep/ParallelFlowStep → execute_independent_flow()
        └── Apply unified features (optional flows, jumps, retries, error handling)
        ```

        ## Step Wrapping Implementation

        Individual steps are automatically wrapped in IndependentFlow containers:

        ```python
        # FlowStep wrapping
        wrapper_flow = IndependentFlow(
            steps=[flow_step],
            name=f"Single Step: {flow_step.name or flow_step.operation}",
            max_workers=1,
            wait_after_seconds=0
        )

        # ParallelFlowStep wrapping
        wrapper_flow = IndependentFlow(
            steps=[parallel_step],
            name=f"Parallel Steps: {parallel_step.name or 'Unnamed'}",
            max_workers=1,
            wait_after_seconds=0
        )
        ```

        ## Error Handling and Flow Control

        ### **Immediate Failure Propagation**
        - Any step failure immediately terminates the entire flow execution
        - Optional flows are attempted but their failure also terminates execution
        - Error handlers can override failure behavior through return values

        ### **Jump Logic Integration**
        - Jump targets are resolved within the scope of the containing IndependentFlow
        - Cross-step jumps work correctly when steps are part of the same IndependentFlow
        - Jump loop prevention protects against infinite recursion

        ### **Progress Tracking Integration**
        - Each wrapped step tracked with unique StepExecution objects
        - Wrapper flow names clearly identify the original step type and name
        - Timing and performance metrics captured for all execution paths

        ## Usage Examples

        ### **Mixed Step Type Execution**
        ```python
        steps = [
            FlowStep(name="Power On", operation="power_on", device_type=DeviceType.COMPUTE, device_id="node1"),
            ParallelFlowStep(name="Parallel Operations", steps=[...], max_workers=4),
            IndependentFlow(name="Recovery Flow", steps=[...], max_workers=2),
            FlowStep(name="Verify System", operation="check_status", device_type=DeviceType.COMPUTE, device_id="node1")
        ]

        success = orchestrator.execute_flow(steps)
        ```

        ### **Consecutive IndependentFlow Optimization**
        ```python
        steps = [
            IndependentFlow(name="Flow A", steps=[...]),  # ┐
            IndependentFlow(name="Flow B", steps=[...]),  # ├─ Executed in parallel
            IndependentFlow(name="Flow C", steps=[...]),  # ┘
            FlowStep(name="Final Step", operation="cleanup", device_type=DeviceType.COMPUTE, device_id="node1")
        ]

        # Flows A, B, C execute concurrently, then Final Step executes
        success = orchestrator.execute_flow(steps)
        ```

        ### **Feature Consistency Across Types**
        ```python
        # Optional flows work identically for all step types
        flow_step = FlowStep(
            name="Flash Firmware",
            operation="pldm_fw_update",
            device_type=DeviceType.COMPUTE,
            device_id="node1",
            execute_optional_flow="recovery_flow",  # Works with wrapping
            jump_on_success="verify_firmware"       # Works with wrapping
        )

        parallel_step = ParallelFlowStep(
            name="Parallel Update",
            steps=[...],
            execute_optional_flow="parallel_recovery",  # Same feature support
            jump_on_failure="error_handling"            # Same feature support
        )

        independent_flow = IndependentFlow(
            name="Complex Flow",
            steps=[...],
            # Optional flows and jumps work at flow level
        )
        ```

        ## Performance Characteristics

        ### **Execution Overhead**
        - **Wrapping Cost**: Minimal overhead for IndependentFlow wrapper creation
        - **Parallel Optimization**: Consecutive IndependentFlows automatically batched
        - **Memory Efficiency**: Wrappers use minimal additional memory
        - **Progress Tracking**: Real-time tracking with negligible performance impact

        ### **Concurrency Benefits**
        - **IndependentFlow Parallelism**: Multiple flows execute concurrently when possible
        - **Thread Pool Reuse**: Efficient thread management across parallel operations
        - **Resource Optimization**: Automatic batching reduces thread creation overhead

        ## Error Scenarios and Recovery

        ### **Step Execution Failures**
        ```python
        # Any step failure terminates the flow
        steps = [step1, failing_step, step3]  # step3 never executes
        success = orchestrator.execute_flow(steps)  # Returns False
        ```

        ### **Optional Flow Failures**
        ```python
        # Optional flow failures also terminate (user policy)
        step_with_optional = FlowStep(
            name="Risky Operation",
            operation="risky_op",
            execute_optional_flow="recovery_flow"  # If this fails, flow terminates
        )
        ```

        ### **Error Handler Recovery**
        ```python
        # Error handlers can override failure behavior
        step_with_handler = FlowStep(
            name="Protected Operation",
            operation="protected_op",
            execute_on_error="recovery_handler"  # Can return True to continue
        )
        ```

        ## Integration with Progress Tracking

        All step executions are tracked with detailed StepExecution objects:
        - **Wrapper Identification**: Clear naming shows original step type
        - **Timing Analysis**: Execution time captured for performance analysis
        - **Error Collection**: Error messages captured and propagated
        - **JSON Output**: Complete execution history with hierarchical relationships

        Args:
            steps: List of flow steps of any supported type (FlowStep, ParallelFlowStep, IndependentFlow)
                  Can be mixed types, processed uniformly through unified execution engine

        Returns:
            bool: True if all steps executed successfully, False if any step failed
                 Immediate failure on first error (no partial success continuation)

        Raises:
            ValueError: If any step has invalid configuration
            RuntimeError: If critical execution errors occur (rare, most errors return False)

        Note:
            This method implements the core of the unified execution engine architecture.
            All feature development should focus on the IndependentFlow execution path
            to ensure consistent behavior across all step types.

        See Also:
            execute_independent_flow: Direct execution of IndependentFlow objects
            execute_parallel_flows: Concurrent execution of multiple IndependentFlow objects
            FlowStep: Individual operation step definition
            ParallelFlowStep: Parallel operation step definition
            IndependentFlow: Container flow definition with advanced features
        """
        if not steps:
            self.logger.info("No steps to execute")
            return True

        # Group consecutive independent flows for parallel execution,
        # convert everything else to individual independent flows
        i = 0

        while i < len(steps):
            step = steps[i]

            if isinstance(step, IndependentFlow):
                # Find all consecutive independent flows for parallel execution
                consecutive_independent = []
                while i < len(steps) and isinstance(steps[i], IndependentFlow):
                    consecutive_independent.append(steps[i])
                    i += 1

                # Execute consecutive independent flows in parallel
                if not self.execute_parallel_flows(consecutive_independent):
                    return False

            else:
                # Convert single steps (FlowStep or ParallelFlowStep) to IndependentFlow
                # and execute using unified system
                if isinstance(step, FlowStep):
                    flow_name = f"Single Step: {step.name or step.operation}"
                elif isinstance(step, ParallelFlowStep):
                    flow_name = f"Parallel Steps: {step.name or 'Unnamed'}"
                else:
                    flow_name = f"Step {i+1}"

                # Wrap the single step in an IndependentFlow
                wrapper_flow = IndependentFlow(steps=[step], name=flow_name, max_workers=1, wait_after_seconds=0)

                # Execute using unified system
                if not self.execute_independent_flow(wrapper_flow):
                    return False

                i += 1

        return True

    def execute_independent_flow(self, flow: IndependentFlow, is_optional_flow: bool = False) -> bool:
        """
        Execute an independent flow with unified progress tracking.
        Automatically adapts to GUI/non-GUI modes.

        Args:
            flow (IndependentFlow): Flow to execute
            is_optional_flow (bool): Whether this is an optional flow

        Returns:
            bool: True if flow was successful, False otherwise
        """
        flow_name = flow.name or "Independent Flow"
        self.logger.info(f"Executing independent flow: {flow_name}")

        # Start timing
        self.progress_tracker.start_flow_timing(flow_name)

        # Mark flow as running (updates status from Pending to Running)
        self.progress_tracker.set_flow_running(flow_name)

        try:
            # Execute steps with unified progress tracking
            success = self._execute_flow_steps_unified(flow, flow_name, is_optional_flow)

            # Handle normal step failures (not exceptions)
            if not success and not is_optional_flow:
                # Get actual error from last failed step instead of generic message
                last_step_error = self._get_last_step_error_message(flow_name)
                self.progress_tracker.set_flow_failed(flow_name, last_step_error)

                # Execute flow-level error handler AFTER flow failure tracking is complete
                self._execute_flow_error_handler(flow_name, last_step_error)

            return success

        except Exception as e:
            self.logger.error(f"Error executing independent flow {flow_name}: {str(e)}")
            # Update progress tracker with error status
            if not is_optional_flow:
                self.progress_tracker.set_flow_error(flow_name, str(e))

                # Execute flow-level error handler AFTER flow error tracking is complete
                self._execute_flow_error_handler(flow_name, str(e))
            return False
        finally:
            # Complete timing
            self.progress_tracker.complete_flow_timing(flow_name)

    def _execute_flow_steps_unified(self, flow: IndependentFlow, flow_name: str, is_optional_flow: bool) -> bool:
        """Execute flow steps with unified progress tracking."""
        # Create a map of tag to step index for quick lookup
        tag_to_index = {}
        for i, step in enumerate(flow.steps):
            if isinstance(step, FlowStep) and step.tag:
                tag_to_index[step.tag] = i

        # Execute steps sequentially with automatic progress management
        current_step_index = 0

        while current_step_index < len(flow.steps):
            step = flow.steps[current_step_index]

            # Step tracking is handled automatically in _execute_single_step_with_retries

            if isinstance(step, ParallelFlowStep):
                # Execute parallel steps
                if not self.execute_parallel_steps(step):
                    self.logger.error(f"Parallel steps failed in independent flow {flow_name}")
                    return False

                # Parallel step completed (individual steps within it are tracked separately)
                current_step_index += 1
            else:
                # Execute single step with retries and automatic progress tracking
                success = self._execute_single_step_with_retries(flow_name, step, current_step_index)

                if success:
                    # Check for jumps
                    if step.jump_on_success:
                        target_tag = step.jump_on_success
                        if target_tag in tag_to_index:
                            target_index = tag_to_index[target_tag]
                            # Check for infinite loop (jumping to self) - use isinstance to avoid True==1 bug
                            if isinstance(target_index, int) and target_index == current_step_index:
                                self.logger.error(
                                    f"Infinite loop detected: step {current_step_index} jumping to itself in independent flow {flow_name}"
                                )
                                return False

                            self.logger.info(
                                f"Jumping to tag '{target_tag}' on success in independent flow {flow_name}"
                            )
                            # Reset has_jumped_on_failure flags for all steps before the target
                            self._reset_jump_on_failure_flags(flow.steps, target_index)
                            current_step_index = target_index
                            continue
                        self.logger.error(
                            f"Tag '{target_tag}' not found in independent flow {flow_name} - flow will fail"
                        )
                        return False

                    current_step_index += 1
                else:
                    # Handle failure
                    failure_result = self._handle_step_failure_unified(
                        flow_name=flow_name,
                        step=step,
                        tag_to_index=tag_to_index,
                        steps=flow.steps,
                    )
                    if failure_result is False:
                        return False
                    if isinstance(failure_result, bool):
                        # Continue to next step (failure_result is True - step succeeded after optional flow)
                        current_step_index += 1
                    elif isinstance(failure_result, int):
                        # Jump to target step index
                        target_index = failure_result
                        # Check for infinite loop (jumping to self) - use isinstance to avoid True==1 bug
                        if isinstance(target_index, int) and target_index == current_step_index:
                            self.logger.error(
                                f"Infinite loop detected: step {current_step_index} jumping to itself in independent flow {flow_name}"
                            )
                            return False
                        current_step_index = target_index
                        continue
                    else:
                        # Unexpected return value
                        self.logger.error(
                            f"Unexpected return value from _handle_step_failure_unified: {failure_result} (type: {type(failure_result)})"
                        )
                        return False

        # Mark flow as completed
        if not is_optional_flow:
            self.progress_tracker.set_flow_completed(flow_name)

        # Flow completed successfully if we reached the end without early returns
        return True

    def _execute_single_step_with_retries(self, flow_name: str, step: FlowStep, step_index: int) -> bool:
        """Execute a single step with enhanced execution tracking."""
        step_name = step.name or step.operation

        # Start detailed step execution tracking
        execution_id = self.progress_tracker.start_step_execution(flow_name, step, step_index)

        # Store execution_id on step for later completion by failure handling
        step.current_execution_id = execution_id
        step.current_flow_name = flow_name

        # Update flow current step (for basic flow status tracking)
        self.progress_tracker.update_flow_current_step(flow_name, step_name, step_index + 1)

        final_result = False
        last_exception = None  # Preserve the original exception for error handler

        # Start collecting ERROR messages for this step
        start_collecting_errors()

        for attempt in range(step.retry_count + 1):
            retry_start = time.time()

            if attempt > 0:
                self.logger.info(f"{step.device_id} - Retry attempt {attempt}/{step.retry_count} for step {step_name}")
                # Update status for retry attempts
                status = f"retrying (attempt {attempt + 1})"
                self.progress_tracker.update_step_execution(flow_name, execution_id, status)

                # Wait between retries if specified
                if step.wait_between_retries_seconds > 0:
                    self.logger.info(
                        f"{step.device_id} - Waiting {step.wait_between_retries_seconds} seconds between retries for {step_name}"
                    )
                    time.sleep(step.wait_between_retries_seconds)

            # Execute the actual step
            try:
                if self.execute_step(step):
                    # Step succeeded
                    final_result = True
                    retry_duration = time.time() - retry_start

                    # Record retry attempt if applicable
                    if attempt > 0:
                        self.progress_tracker.add_step_retry(execution_id, attempt, retry_duration)

                    # Wait after step if specified
                    if step.wait_after_seconds > 0:
                        self.logger.info(
                            f"{step.device_id} - Waiting {step.wait_after_seconds} seconds after operation {step_name}"
                        )
                        time.sleep(step.wait_after_seconds)

                    # Complete step execution tracking immediately for successful steps
                    self.progress_tracker.complete_step_execution(execution_id, True, None)
                    # Clear the tracking info since we completed it
                    step.current_execution_id = None
                    step.current_flow_name = None

                    return True
                # Step failed this attempt - check if step has stored exception
                last_exception = getattr(step, "last_exception", None)
                retry_duration = time.time() - retry_start
                self.progress_tracker.add_step_retry(execution_id, attempt, retry_duration)

                if attempt == step.retry_count:  # Last attempt failed
                    pass  # Error is handled through last_exception and error collection

            except Exception as e:
                # Step execution raised an exception - this is always the LAST error
                last_exception = e
                retry_duration = time.time() - retry_start

                self.progress_tracker.add_step_retry(execution_id, attempt, retry_duration)

                if attempt == step.retry_count:  # Last attempt failed
                    break
                self.logger.warning(f"{step.device_id} - Step {step_name} failed on attempt {attempt + 1}: {str(e)}")

        # Store the LAST exception for error handler (could be from any attempt)
        if last_exception:
            step.last_exception = last_exception

        # Stop collecting and store error messages in step execution
        collected_errors = stop_collecting_errors()
        if execution_id and collected_errors:
            step_execution = self.progress_tracker.find_step_execution(flow_name, execution_id)
            if step_execution:
                step_execution.error_messages = collected_errors

        # Don't complete step execution here - let failure handling do it after optional flows
        return final_result

    def _handle_step_failure_unified(
        self,
        *,
        flow_name: str,
        step: FlowStep,
        tag_to_index: dict,
        steps: List[Union[FlowStep, ParallelFlowStep]],
    ) -> Union[bool, int]:
        """
        Handle step failure with jumps and error handlers.

        Returns:
            False: Flow should fail
            True: Continue to next step
            int: Jump to this step index
        """
        step_name = step.name or step.operation

        # Get execution tracking info from step
        execution_id = getattr(step, "current_execution_id", None)

        final_success = False
        optional_flow_executed = None

        try:
            # First, try to execute optional flow if configured
            if hasattr(step, "execute_optional_flow") and step.execute_optional_flow:
                optional_flow = self.optional_flows.get(step.execute_optional_flow)
                if optional_flow:
                    self.logger.info(
                        f"{step.device_id} - Found optional flow: {step.execute_optional_flow}, executing..."
                    )
                    optional_flow_executed = step.execute_optional_flow

                    # Track optional flow triggering
                    if execution_id:
                        self.progress_tracker.add_optional_flow_trigger(
                            execution_id,
                            step.execute_optional_flow,
                            False,
                        )

                    if self.execute_optional_flow(
                        optional_flow=optional_flow,
                        optional_flow_name=step.execute_optional_flow,
                        main_flow_name=flow_name,
                        triggering_step=step_name,
                    ):
                        self.logger.info(
                            f"{step.device_id} - Optional flow {step.execute_optional_flow} succeeded, retrying main step with fresh retry count"
                        )

                        # Update optional flow result
                        if execution_id:
                            self.progress_tracker.add_optional_flow_trigger(
                                execution_id,
                                step.execute_optional_flow,
                                True,
                            )

                        # Retry the main step with full retry count after optional flow succeeds
                        for attempt in range(step.retry_count + 1):
                            if attempt > 0:
                                self.logger.info(
                                    f"{step.device_id} - Post-optional retry attempt {attempt}/{step.retry_count}"
                                )
                                # Wait between retries if specified
                                if step.wait_between_retries_seconds > 0:
                                    self.logger.info(
                                        f"{step.device_id} - Waiting {step.wait_between_retries_seconds} seconds between retries for {step_name}"
                                    )
                                    time.sleep(step.wait_between_retries_seconds)

                            if self.execute_step(step):
                                self.logger.info(
                                    f"{step.device_id} - Step {step_name} succeeded after optional flow and retry"
                                )
                                final_success = True

                                if step.wait_after_seconds > 0:
                                    self.logger.info(
                                        f"{step.device_id} - Waiting {step.wait_after_seconds} seconds after operation {step_name}"
                                    )
                                    time.sleep(step.wait_after_seconds)

                                # Handle jump on success after optional flow
                                if step.jump_on_success:
                                    target_tag = step.jump_on_success
                                    if target_tag in tag_to_index:
                                        target_index = tag_to_index[target_tag]
                                        self.logger.info(
                                            f"{step.device_id} - Jumping to tag '{target_tag}' on success after optional flow"
                                        )
                                        # Return target index to indicate jump (same pattern as jump_on_failure)
                                        return target_index
                                    self.logger.warning(f"{step.device_id} - Tag '{target_tag}' not found")
                                    return False  # Fail the flow when jump target doesn't exist
                                break

                        if final_success:
                            return True
                        # Step still failed after optional flow and retries
                        self.logger.error(
                            f"{step.device_id} - Step failed even after executing optional flow {step.execute_optional_flow} and {step.retry_count} fresh retries"
                        )
                        # Continue to error handler below
                    else:
                        self.logger.error(f"{step.device_id} - Optional flow {step.execute_optional_flow} failed")
                        # Per user policy: if optional flow fails, fail the overall flow immediately
                        # Do not continue to jump logic or error handlers
                        return False
                else:
                    self.logger.warning(
                        f"{step.device_id} - Optional flow '{step.execute_optional_flow}' not found in loaded optional flows"
                    )

            # Handle jump on failure
            if step.jump_on_failure and not getattr(step, "has_jumped_on_failure", False):
                target_tag = step.jump_on_failure
                if target_tag in tag_to_index:
                    self.logger.info(
                        f"{step.device_id} - Jumping to tag '{target_tag}' on failure in independent flow {flow_name}"
                    )
                    step.has_jumped_on_failure = True
                    target_index = tag_to_index[target_tag]
                    # Reset has_jumped_on_failure flags for all steps before the target
                    self._reset_jump_on_failure_flags(steps, target_index)
                    return target_index  # Return target index to indicate jump
                self.logger.error(
                    f"{step.device_id} - Tag '{target_tag}' not found in independent flow {flow_name} - flow will fail"
                )
                return False  # Fail the flow when jump target doesn't exist

            # Use error handler as last resort (only if execute_on_error is defined)
            if hasattr(step, "execute_on_error") and step.execute_on_error:
                original_exception = getattr(step, "last_exception", None)
                error_handler_result = self._handle_step_failure_with_error_handler(
                    step=step,
                    retry_attempts=step.retry_count,
                    optional_flow_executed=optional_flow_executed,
                    original_exception=original_exception,
                )
                return bool(error_handler_result)
            # No error handler defined, flow fails
            return False

        finally:
            # Complete step execution tracking if not already done
            if execution_id and hasattr(step, "current_execution_id") and step.current_execution_id:
                error_msg = (
                    None
                    if final_success
                    else f"Step failed after retries{' and optional flow' if optional_flow_executed else ''}"
                )
                self.progress_tracker.complete_step_execution(execution_id, final_success, error_msg)
                # Clear tracking info
                step.current_execution_id = None
                step.current_flow_name = None

    def _update_live_display(self):
        """Update the live display with current progress tracker data."""
        flow_status = self.progress_tracker.get_flow_status_dict()
        self.output_manager.update_live_display(flow_status)

    def _count_total_steps(self, flows: List[IndependentFlow]) -> int:
        """Count total number of steps across all flows."""
        total = 0
        for flow in flows:
            for step in flow.steps:
                if isinstance(step, ParallelFlowStep):
                    total += len(step.steps)
                else:
                    total += 1
        return total

    def execute_parallel_flows(self, flows: List[IndependentFlow]) -> bool:
        """
        Execute multiple independent flows in parallel with unified progress tracking.
        Automatically adapts to GUI/non-GUI modes.

        Args:
            flows (List[IndependentFlow]): List of flows to execute in parallel

        Returns:
            bool: True if all flows were successful, False otherwise
        """
        self.logger.info(f"Executing {len(flows)} independent flows in parallel")

        # Initialize flows in progress tracker
        self.progress_tracker.clear()  # Start fresh
        for flow in flows:
            flow_name = flow.name or "Unnamed Flow"
            total_steps = self._count_total_steps([flow])
            self.progress_tracker.add_flow(flow_name=flow_name, total_steps=total_steps)

        # Set up GUI mode if active
        if self.output_mode == OutputMode.GUI:
            # Create display and execute with Live
            flow_status = self.progress_tracker.get_flow_status_dict()
            initial_table = self.output_manager.build_progress_table_from_tracker(flow_status)
            progress = self.output_manager.get_progress_component()

            display = Group(
                Panel(
                    initial_table,
                    title="Independent Flows Progress",
                    border_style="blue",
                ),
                "\n",
                Panel(progress, title="Progress", border_style="green"),
            )

            with Live(display, refresh_per_second=1, vertical_overflow="visible") as live:
                # Enable GUI mode in progress tracker and output manager
                self.progress_tracker.set_gui_mode(live, progress, self._update_live_display)
                self.output_manager.set_gui_live_display(live, self._update_live_display)
                return self._execute_flows_parallel(flows)
        else:
            # Non-GUI mode: Simple execution without Live display
            # Don't display table in LOG or NONE modes - let logger output flow naturally
            return self._execute_flows_parallel(flows)

    def _execute_flows_parallel(self, flows: List[IndependentFlow]) -> bool:
        """Single parallel execution method for both GUI and non-GUI modes."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(flows)) as executor:
            # Submit all flows to the executor
            future_to_flow = {executor.submit(self.execute_independent_flow, flow): flow for flow in flows}

            # Wait for all flows to complete
            success = True
            for future in concurrent.futures.as_completed(future_to_flow):
                flow = future_to_flow[future]
                try:
                    if not future.result():
                        success = False
                        self.logger.error(f"Flow {flow.name or 'Unnamed'} failed")
                except Exception as e:
                    success = False
                    self.logger.error(f"Flow {flow.name or 'Unnamed'} raised an exception: {str(e)}")
                    self.progress_tracker.set_flow_error(flow.name or "Unnamed Flow", str(e))
                finally:
                    # Clean up resources
                    self.progress_tracker.cleanup_flow(flow.name or "Unnamed Flow")

        return success

    def execute_optional_flow(
        self,
        *,
        optional_flow: List[Union[FlowStep, ParallelFlowStep, IndependentFlow]],
        optional_flow_name: str,
        main_flow_name: str = None,
        triggering_step: str = None,
    ) -> bool:
        """
        Execute an optional flow using unified flow tracking.

        Args:
            optional_flow: Optional flow steps to execute
            optional_flow_name: Name of the optional flow for logging
            main_flow_name: Name of the main flow that triggered this optional flow
            triggering_step: Name of the step that triggered this optional flow

        Returns:
            bool: True if all steps in optional flow succeeded, False otherwise
        """
        self.logger.info(f"Executing optional flow '{optional_flow_name}'")

        # Convert optional flow to IndependentFlow object
        optional_flow_obj = IndependentFlow(
            steps=optional_flow,
            name=optional_flow_name,
            max_workers=1,  # Sequential execution for optional flows
            wait_after_seconds=0,
        )

        # Add optional flow to progress tracker with parent relationship
        total_steps = self._count_total_steps([optional_flow_obj])
        self.progress_tracker.add_flow(
            flow_name=optional_flow_name,
            total_steps=total_steps,
            parent_flow_name=main_flow_name,
            triggered_by_step=triggering_step,
        )

        # Execute the optional flow with unified tracking
        try:
            result = self.execute_independent_flow(optional_flow_obj)
            return result

        except Exception as e:
            # Update flow with error status
            self.progress_tracker.set_flow_error(optional_flow_name, str(e))
            raise
        finally:
            # Clean up resources
            self.progress_tracker.cleanup_flow(optional_flow_name)

    def _collect_error_handler_names(self, flow_config: Dict[str, Any]) -> Set[str]:
        """
        Recursively collect all error handler names from a flow configuration.

        Args:
            flow_config (Dict[str, Any]): Flow configuration dictionary

        Returns:
            Set[str]: Set of error handler names
        """
        handler_names = set()

        # Check settings for global error handler
        settings = flow_config.get("settings", {})
        if "execute_on_error" in settings:
            handler_names.add(settings["execute_on_error"])

        # Process steps
        for step in flow_config.get("steps", []):
            # Check for error handler in step
            if "execute_on_error" in step:
                handler_names.add(step["execute_on_error"])

            # Check parallel steps
            if "parallel" in step:
                for parallel_step in step["parallel"]:
                    if "execute_on_error" in parallel_step:
                        handler_names.add(parallel_step["execute_on_error"])

            # Check independent flows
            if "independent_flows" in step:
                for flow in step["independent_flows"]:
                    for sub_step in flow.get("steps", []):
                        if "execute_on_error" in sub_step:
                            handler_names.add(sub_step["execute_on_error"])
                        # Check nested steps
                        if "steps" in sub_step:
                            for nested_step in sub_step["steps"]:
                                if "execute_on_error" in nested_step:
                                    handler_names.add(nested_step["execute_on_error"])

        return handler_names

    def _register_error_handlers_from_config(self, flow_config: Dict[str, Any]):
        """
        Register all error handlers found in the flow configuration.

        Args:
            flow_config (Dict[str, Any]): Flow configuration dictionary
        """
        handler_names = self._collect_error_handler_names(flow_config)

        for handler_name in handler_names:
            if handler_name not in self.error_handlers:
                handler = None

                # Check if handler exists in global namespace
                if handler_name in globals():
                    handler = globals()[handler_name]
                # Check if handler exists in imported error_handlers module
                elif hasattr(error_handlers, handler_name):
                    handler = getattr(error_handlers, handler_name)

                if handler is not None:
                    # Verify it's a callable with the correct signature
                    if callable(handler):
                        sig = inspect.signature(handler)
                        if len(sig.parameters) == 3:  # step, error, context
                            self.logger.info(f"Registering error handler: {handler_name}")
                            self.register_error_handler(handler_name, handler)
                        else:
                            self.logger.warning(f"Error handler {handler_name} has incorrect signature")
                    else:
                        self.logger.warning(f"Error handler {handler_name} is not callable")
                else:
                    self.logger.warning(f"Could not find error handler: {handler_name}")

    def _load_optional_flows(self, flow_config: Dict[str, Any]):
        """
        Load optional flows from the flow configuration.

        Args:
            flow_config (Dict[str, Any]): Flow configuration dictionary
        """
        optional_flows = flow_config.get("optional_flows", {})
        for flow_name, flow_steps in optional_flows.items():
            self.optional_flows[flow_name] = self._convert_steps_to_flow_objects(flow_steps)

    def _validate_step_fields(self, step_config: Dict[str, Any], location: str) -> None:
        """
        Validate that a step has all required fields.

        Args:
            step_config: The step configuration dictionary
            location: Description of where this step is located (for error messages)

        Raises:
            ValueError: If required fields are missing or invalid
        """
        step_name = step_config.get("name", "unnamed step")

        # Check required fields
        required_fields = ["device_type", "device_id", "operation"]
        for field in required_fields:
            if field not in step_config:
                raise ValueError(f"Missing required field '{field}' in step '{step_name}' at {location}")
            if not step_config[field]:  # Check for empty strings
                raise ValueError(f"Empty value for required field '{field}' in step '{step_name}' at {location}")

        # Validate device_type is valid
        device_type = step_config["device_type"]
        valid_types = ["compute", "switch", "power_shelf"]
        if device_type not in valid_types:
            raise ValueError(
                f"Invalid device_type '{device_type}' in step '{step_name}' at {location}. "
                f"Must be one of: {valid_types}"
            )

        # Validate parameters is a dict if present
        if "parameters" in step_config and not isinstance(step_config.get("parameters"), dict):
            raise ValueError(
                f"Invalid 'parameters' field in step '{step_name}' at {location}. "
                f"Must be a dictionary, got: {type(step_config['parameters']).__name__}"
            )

    def _convert_steps_to_flow_objects(
        self, steps_config: List[Dict[str, Any]]
    ) -> List[Union[FlowStep, ParallelFlowStep, IndependentFlow]]:
        """
        Convert step configurations to flow objects.

        Args:
            steps_config (List[Dict[str, Any]]): List of step configurations

        Returns:
            List[Union[FlowStep, ParallelFlowStep, IndependentFlow]]: List of flow objects
        """
        steps = []
        # Get default retry count without triggering config creation
        default_retry_count = self._get_default_retry_count()

        for i, step_config in enumerate(steps_config):
            if "independent_flows" in step_config:
                # Handle independent flows directly
                for j, flow_config in enumerate(step_config["independent_flows"]):
                    flow_steps = []
                    for k, sub_step in enumerate(flow_config.get("steps", [])):
                        if "steps" in sub_step:
                            # Handle nested parallel steps
                            parallel_steps = []
                            for m, nested_step in enumerate(sub_step["steps"]):
                                # Validate before creating FlowStep
                                self._validate_step_fields(
                                    nested_step,
                                    f"independent_flow[{j}].steps[{k}].steps[{m}]",
                                )
                                step = FlowStep(
                                    device_type=DeviceType(nested_step["device_type"]),
                                    device_id=nested_step["device_id"],
                                    operation=nested_step["operation"],
                                    parameters=nested_step.get("parameters", {}),
                                    retry_count=nested_step.get("retry_count", default_retry_count),
                                    timeout_seconds=nested_step.get("timeout_seconds"),
                                    wait_after_seconds=nested_step.get("wait_after_seconds", 0),
                                    wait_between_retries_seconds=nested_step.get("wait_between_retries_seconds", 0),
                                    name=nested_step.get("name"),
                                    execute_on_error=nested_step.get("execute_on_error"),
                                    execute_optional_flow=nested_step.get("execute_optional_flow"),
                                    jump_on_success=nested_step.get("jump_on_success"),
                                    jump_on_failure=nested_step.get("jump_on_failure"),
                                    tag=nested_step.get("tag"),
                                )
                                parallel_steps.append(step)
                            parallel_step = ParallelFlowStep(
                                steps=parallel_steps,
                                name=sub_step.get("name"),
                                max_workers=sub_step.get("max_workers"),
                                wait_after_seconds=sub_step.get("wait_after_seconds", 0),
                            )
                            flow_steps.append(parallel_step)
                        else:
                            # Handle single step
                            # Validate before creating FlowStep
                            self._validate_step_fields(sub_step, f"independent_flow[{j}].steps[{k}]")
                            step = FlowStep(
                                device_type=DeviceType(sub_step["device_type"]),
                                device_id=sub_step["device_id"],
                                operation=sub_step["operation"],
                                parameters=sub_step.get("parameters", {}),
                                retry_count=sub_step.get("retry_count", default_retry_count),
                                timeout_seconds=sub_step.get("timeout_seconds"),
                                wait_after_seconds=sub_step.get("wait_after_seconds", 0),
                                wait_between_retries_seconds=sub_step.get("wait_between_retries_seconds", 0),
                                name=sub_step.get("name"),
                                execute_on_error=sub_step.get("execute_on_error"),
                                execute_optional_flow=sub_step.get("execute_optional_flow"),
                                jump_on_success=sub_step.get("jump_on_success"),
                                jump_on_failure=sub_step.get("jump_on_failure"),
                                tag=sub_step.get("tag"),
                            )
                            flow_steps.append(step)

                    flow = IndependentFlow(
                        steps=flow_steps,
                        name=flow_config.get("name"),
                        max_workers=flow_config.get("max_workers"),
                        wait_after_seconds=flow_config.get("wait_after_seconds", 0),
                    )
                    steps.append(flow)
            elif "steps" in step_config:
                # Handle nested steps - execute sequentially
                for m, nested_step in enumerate(step_config["steps"]):
                    # Validate before creating FlowStep
                    self._validate_step_fields(nested_step, f"step[{i}].steps[{m}]")
                    step = FlowStep(
                        device_type=DeviceType(nested_step["device_type"]),
                        device_id=nested_step["device_id"],
                        operation=nested_step["operation"],
                        parameters=nested_step.get("parameters", {}),
                        retry_count=nested_step.get("retry_count", default_retry_count),
                        timeout_seconds=nested_step.get("timeout_seconds"),
                        wait_after_seconds=nested_step.get("wait_after_seconds", 0),
                        wait_between_retries_seconds=nested_step.get("wait_between_retries_seconds", 0),
                        name=nested_step.get("name"),
                        execute_on_error=nested_step.get("execute_on_error"),
                        execute_optional_flow=nested_step.get("execute_optional_flow"),
                        jump_on_success=nested_step.get("jump_on_success"),
                        jump_on_failure=nested_step.get("jump_on_failure"),
                        tag=nested_step.get("tag"),
                    )
                    steps.append(step)
            elif "parallel" in step_config:
                # Handle parallel steps - special case
                parallel_steps = []
                for m, parallel_step_config in enumerate(step_config["parallel"]):
                    # Validate before creating FlowStep
                    self._validate_step_fields(parallel_step_config, f"step[{i}].parallel[{m}]")
                    step = FlowStep(
                        device_type=DeviceType(parallel_step_config["device_type"]),
                        device_id=parallel_step_config["device_id"],
                        operation=parallel_step_config["operation"],
                        parameters=parallel_step_config.get("parameters", {}),
                        retry_count=parallel_step_config.get("retry_count", default_retry_count),
                        timeout_seconds=parallel_step_config.get("timeout_seconds"),
                        wait_after_seconds=parallel_step_config.get("wait_after_seconds", 0),
                        wait_between_retries_seconds=parallel_step_config.get("wait_between_retries_seconds", 0),
                        name=parallel_step_config.get("name"),
                        execute_on_error=parallel_step_config.get("execute_on_error"),
                        execute_optional_flow=parallel_step_config.get("execute_optional_flow"),
                        jump_on_success=parallel_step_config.get("jump_on_success"),
                        jump_on_failure=parallel_step_config.get("jump_on_failure"),
                        tag=parallel_step_config.get("tag"),
                    )
                    parallel_steps.append(step)

                # Create ParallelFlowStep
                parallel_flow = ParallelFlowStep(
                    steps=parallel_steps,
                    name=step_config.get("name"),
                    max_workers=step_config.get("max_workers"),
                    wait_after_seconds=step_config.get("wait_after_seconds", 0),
                )
                steps.append(parallel_flow)
            else:
                # Handle single step
                # Validate before creating FlowStep
                self._validate_step_fields(step_config, f"step[{i}]")
                step = FlowStep(
                    device_type=DeviceType(step_config["device_type"]),
                    device_id=step_config["device_id"],
                    operation=step_config["operation"],
                    parameters=step_config.get("parameters", {}),
                    retry_count=step_config.get("retry_count", default_retry_count),
                    timeout_seconds=step_config.get("timeout_seconds"),
                    wait_after_seconds=step_config.get("wait_after_seconds", 0),
                    wait_between_retries_seconds=step_config.get("wait_between_retries_seconds", 0),
                    name=step_config.get("name"),
                    execute_on_error=step_config.get("execute_on_error"),
                    execute_optional_flow=step_config.get("execute_optional_flow"),
                    jump_on_success=step_config.get("jump_on_success"),
                    jump_on_failure=step_config.get("jump_on_failure"),
                    tag=step_config.get("tag"),
                )
                steps.append(step)

        return steps

    def _load_variables(self) -> Dict[str, Any]:
        """Load variables from configuration file."""
        if not os.path.exists(self.config_path):
            self.logger.warning(f"Configuration file not found: {self.config_path}")
            return {}

        with open(self.config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        return config.get("variables", {})

    def _expand_variables(self, value: Any) -> Any:
        """
        Recursively expand variables in a value.

        Args:
            value: The value to expand variables in

        Returns:
            The value with variables expanded
        """
        if isinstance(value, str):
            # Check if the string contains a variable reference
            if "${" in value and "}" in value:
                # Find all well-formed variable references
                pattern = r"\${([^}]+)}"
                matches = list(re.finditer(pattern, value))

                # Only process if we found complete matches
                if matches:
                    # Replace each variable reference
                    result = value
                    for match in matches:
                        var_name = match.group(1)
                        # Skip empty variable names or malformed patterns
                        if not var_name or var_name.startswith("${"):
                            continue

                        if var_name in self.variables:
                            var_value = str(self.variables[var_name])
                            result = result.replace(match.group(0), var_value)
                        else:
                            # Undefined variables should cause flow loading to fail
                            raise ValueError(
                                f"Undefined variable '{var_name}' referenced in flow configuration. "
                                f"Variable must be defined in config file under 'variables' section. "
                                f"Available variables: {list(self.variables.keys())}"
                            )
                    return result
                # No complete variable patterns found, return as-is
                return value
            return value
        if isinstance(value, dict):
            return {k: self._expand_variables(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._expand_variables(item) for item in value]
        return value

    def load_flow_from_yaml(self, flow_path: str) -> List[Union[FlowStep, ParallelFlowStep, IndependentFlow]]:
        """
        Load flow steps from a YAML file.

        Args:
            flow_path (str): Path to the YAML file containing flow steps

        Returns:
            List[Union[FlowStep, ParallelFlowStep, IndependentFlow]]: List of flow steps
        """
        if not os.path.exists(flow_path):
            raise FileNotFoundError(f"Flow configuration file not found: {flow_path}")

        self.logger.info(f"Loading flow from YAML file: {flow_path}")

        with open(flow_path, encoding="utf-8") as f:
            flow_config = yaml.safe_load(f)

        self.logger.info(f"YAML loaded successfully. Top-level keys: {list(flow_config.keys())}")

        # Validate the YAML structure before processing
        self._validate_flow_yaml(flow_config)

        # Check optional flows
        optional_flows_raw = flow_config.get("optional_flows", {})
        self.logger.info(f"Found {len(optional_flows_raw)} optional flows in YAML: {list(optional_flows_raw.keys())}")

        # Check main steps
        main_steps_raw = flow_config.get("steps", [])
        self.logger.info(f"Found {len(main_steps_raw)} main flow steps in YAML")

        # Expand variables in the flow configuration
        flow_config = self._expand_variables(flow_config)

        # Register any new error handlers found in the flow configuration
        self._register_error_handlers_from_config(flow_config)

        # Load optional flows
        self.logger.info("About to load optional flows...")
        self._load_optional_flows(flow_config)
        self.logger.info(f"Finished loading optional flows. Total loaded: {len(self.optional_flows)}")
        self.logger.info(f"Optional flows in memory: {list(self.optional_flows.keys())}")

        # Get global error handler from settings and update the orchestrator's default
        settings = flow_config.get("settings", {})
        if "execute_on_error" in settings:
            self.default_error_handler = settings.get("execute_on_error")
            self.logger.info(f"Default error handler set from flow file: {self.default_error_handler}")

        # Convert main flow steps to flow objects
        main_flow_steps = self._convert_steps_to_flow_objects(flow_config.get("steps", []))
        self.logger.info(f"Converted {len(main_flow_steps)} main flow steps to objects")

        return main_flow_steps

    def close(self):
        """Close all connections and cleanup resources."""
        # Only close configs that were actually created
        if self._compute_config is not None:
            self._compute_config.close()
        if self._switch_config is not None:
            self._switch_config.close()
        if self._power_shelf_config is not None:
            self._power_shelf_config.close()

        # Cleanup output manager resources
        self.output_manager.cleanup()

    def _validate_flow_yaml(self, flow_config: Dict[str, Any]) -> None:
        """
        Validate YAML flow configuration for correctness and consistency.

        Args:
            flow_config: The loaded YAML configuration dictionary

        Raises:
            ValueError: If validation fails
        """
        # Collect all tags and check for duplicates
        all_tags = []
        tag_locations = {}  # tag -> (location, step_name)

        def collect_tags_from_steps(steps: List[Dict[str, Any]], location: str):
            """Recursively collect tags from steps."""
            for i, step in enumerate(steps):
                if "tag" in step and step["tag"]:
                    tag = step["tag"]
                    step_name = step.get("name", f"Step {i+1}")
                    if tag in all_tags:
                        raise ValueError(
                            f"Duplicate tag '{tag}' found. "
                            f"First occurrence: {tag_locations[tag][1]} in {tag_locations[tag][0]}. "
                            f"Second occurrence: {step_name} in {location}"
                        )
                    all_tags.append(tag)
                    tag_locations[tag] = (location, step_name)

                # Check nested structures
                if "parallel" in step:
                    collect_tags_from_steps(step["parallel"], f"{location} -> parallel steps")
                if "steps" in step:
                    collect_tags_from_steps(step["steps"], f"{location} -> nested steps")
                if "independent_flows" in step:
                    for flow in step["independent_flows"]:
                        if "steps" in flow:
                            flow_name = flow.get("name", "unnamed flow")
                            collect_tags_from_steps(flow["steps"], f"{location} -> {flow_name}")

        # Collect tags from main steps
        main_steps = flow_config.get("steps", [])
        collect_tags_from_steps(main_steps, "main flow")

        # Collect tags from optional flows
        optional_flows = flow_config.get("optional_flows", {})
        for flow_name, flow_steps in optional_flows.items():
            collect_tags_from_steps(flow_steps, f"optional flow '{flow_name}'")

        # Now validate references
        def validate_step_references(step: Dict[str, Any], location: str):
            """Validate references in a single step."""
            step_name = step.get("name", "unnamed step")

            # Check jump targets
            if "jump_on_success" in step and step["jump_on_success"]:
                target = step["jump_on_success"]
                if target not in all_tags:
                    raise ValueError(
                        f"Invalid jump target '{target}' in step '{step_name}' at {location}. "
                        f"Target tag does not exist. Available tags: {sorted(all_tags)}"
                    )

            if "jump_on_failure" in step and step["jump_on_failure"]:
                target = step["jump_on_failure"]
                if target not in all_tags:
                    raise ValueError(
                        f"Invalid jump target '{target}' in step '{step_name}' at {location}. "
                        f"Target tag does not exist. Available tags: {sorted(all_tags)}"
                    )

            # Check optional flow references
            if "execute_optional_flow" in step and step["execute_optional_flow"]:
                flow_name = step["execute_optional_flow"]
                if flow_name not in optional_flows:
                    raise ValueError(
                        f"Invalid optional flow reference '{flow_name}' in step '{step_name}' at {location}. "
                        f"Optional flow does not exist. Available flows: {sorted(optional_flows.keys())}"
                    )

            # Check error handler references
            if "execute_on_error" in step and step["execute_on_error"]:
                handler_name = step["execute_on_error"]
                # Get registered handlers from error_handlers module
                known_handlers = error_handlers.get_handler_names()
                # Add default handler if not in registry
                if "default_error_handler" not in known_handlers:
                    known_handlers.append("default_error_handler")
                error_handlers_in_config = flow_config.get("error_handlers", {})

                if (
                    handler_name not in self.error_handlers
                    and handler_name not in known_handlers
                    and handler_name not in error_handlers_in_config
                ):
                    raise ValueError(
                        f"Invalid error handler reference '{handler_name}' in step '{step_name}' at {location}. "
                        f"Handler is not a known built-in handler. "
                        f"Known handlers: {sorted(known_handlers)}"
                    )

        def validate_steps_recursively(steps: List[Dict[str, Any]], location: str):
            """Recursively validate all steps."""
            for i, step in enumerate(steps):
                step_location = f"{location}[{i}]"
                validate_step_references(step, step_location)

                # Validate nested structures
                if "parallel" in step:
                    validate_steps_recursively(step["parallel"], f"{step_location} -> parallel")
                if "steps" in step:
                    validate_steps_recursively(step["steps"], f"{step_location} -> steps")
                if "independent_flows" in step:
                    for j, flow in enumerate(step["independent_flows"]):
                        if "steps" in flow:
                            flow_name = flow.get("name", f"flow {j}")
                            validate_steps_recursively(flow["steps"], f"{step_location} -> {flow_name}")

        # Validate all steps
        validate_steps_recursively(main_steps, "main flow")

        # Validate optional flows
        for flow_name, flow_steps in optional_flows.items():
            validate_steps_recursively(flow_steps, f"optional flow '{flow_name}'")

        # Check for circular jump dependencies
        def check_circular_jumps(all_tags: Dict[str, Dict[str, Any]]) -> None:
            """Check for circular dependencies in jump_on_failure references."""
            for tag, step in all_tags.items():
                if "jump_on_failure" in step and step["jump_on_failure"]:
                    visited = set()
                    current = tag
                    path = []

                    while current:
                        if current in visited:
                            # Found a cycle - reconstruct the cycle path
                            cycle_start_idx = path.index(current)
                            cycle_path = path[cycle_start_idx:] + [current]
                            raise ValueError(
                                f"Circular jump dependency detected: {' -> '.join(cycle_path)}. "
                                f"Steps cannot form a cycle through jump_on_failure references."
                            )

                        visited.add(current)
                        path.append(current)

                        # Get the jump target for the current step
                        current_step = all_tags.get(current)
                        if current_step and "jump_on_failure" in current_step:
                            current = current_step["jump_on_failure"]
                        else:
                            current = None

        # Build tag-to-step mapping for circular jump checking
        tag_to_step = {}

        def collect_tagged_steps(steps: List[Dict[str, Any]]):
            """Collect all tagged steps into a mapping."""
            for step in steps:
                if "tag" in step and step["tag"]:
                    tag_to_step[step["tag"]] = step

                # Check nested structures
                if "parallel" in step:
                    collect_tagged_steps(step["parallel"])
                if "steps" in step:
                    collect_tagged_steps(step["steps"])
                if "independent_flows" in step:
                    for flow in step["independent_flows"]:
                        if "steps" in flow:
                            collect_tagged_steps(flow["steps"])

        # Collect from main flow
        collect_tagged_steps(main_steps)

        # Collect from optional flows
        for _flow_name, flow_steps in optional_flows.items():
            collect_tagged_steps(flow_steps)

        # Now check for circular jumps
        check_circular_jumps(tag_to_step)

        # Check for circular optional flow references
        def check_circular_optional_flows(optional_flows: Dict[str, List]) -> None:
            """Check for circular dependencies in execute_optional_flow references."""

            def check_flow_recursively(flow_name: str, visited: Set[str], path: List[str]) -> None:
                if flow_name in visited:
                    # Found a cycle
                    cycle_start = path.index(flow_name)
                    cycle_path = path[cycle_start:] + [flow_name]
                    raise ValueError(
                        f"Circular optional flow reference detected: {' -> '.join(cycle_path)}. "
                        f"Optional flows cannot form a cycle through execute_optional_flow references."
                    )

                visited.add(flow_name)
                path.append(flow_name)

                # Check steps in this optional flow for references to other optional flows
                if flow_name in optional_flows:
                    for step in optional_flows[flow_name]:
                        if isinstance(step, dict) and "execute_optional_flow" in step and step["execute_optional_flow"]:
                            check_flow_recursively(
                                step["execute_optional_flow"],
                                visited.copy(),
                                path.copy(),
                            )

                path.pop()

            # Check all optional flows
            for flow_name in optional_flows:
                check_flow_recursively(flow_name, set(), [])

        check_circular_optional_flows(optional_flows)

        self.logger.info("YAML flow validation completed successfully")

    def _reset_jump_on_failure_flags(
        self,
        steps: List[Union[FlowStep, ParallelFlowStep, IndependentFlow]],
        target_index: int,
    ):
        """
        Reset has_jumped_on_failure flag for all steps before the target index.
        This implements sophisticated loop prevention by allowing steps to retry
        jumping only after making progress past them.

        Args:
            steps (List[Union[FlowStep, ParallelFlowStep, IndependentFlow]]): List of flow steps
            target_index (int): Target step index (steps before this will have flags reset)
        """
        for i in range(target_index):
            step = steps[i]
            if isinstance(step, FlowStep):
                step.has_jumped_on_failure = False
            elif isinstance(step, ParallelFlowStep):
                # Reset flags for all steps in parallel flow
                for parallel_step in step.steps:
                    if isinstance(parallel_step, FlowStep):
                        parallel_step.has_jumped_on_failure = False
            elif isinstance(step, IndependentFlow):
                # Reset flags for all steps in independent flow
                for independent_step in step.steps:
                    if isinstance(independent_step, FlowStep):
                        independent_step.has_jumped_on_failure = False
                    elif isinstance(independent_step, ParallelFlowStep):
                        for parallel_step in independent_step.steps:
                            if isinstance(parallel_step, FlowStep):
                                parallel_step.has_jumped_on_failure = False
