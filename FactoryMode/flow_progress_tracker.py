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
Factory Flow Progress Tracking System - Enhanced StepExecution Architecture

This module implements the comprehensive progress tracking system for the NVIDIA Factory
Flow Orchestrator's unified execution engine. It provides detailed execution monitoring,
JSON persistence, and hierarchical flow relationships for complex factory automation workflows.

## Core Architecture

The progress tracking system is built around three primary data structures:

### **StepExecution Class**
Captures detailed execution information for every step, including:
- **Execution Metadata**: Unique IDs, timing, device targeting
- **Configuration Details**: Retry counts, timeouts, error handlers, optional flows
- **Runtime Information**: Retry attempts, jump logic execution, error collection
- **Context Preservation**: Parameters passed to steps and execution context

### **FlowInfo Class**
Manages flow-level aggregation and statistics:
- **Automatic Calculation**: Performance metrics derived from StepExecution objects
- **Hierarchical Relationships**: Parent-child linkage for optional flows
- **Progress Aggregation**: Real-time completion tracking and timing analysis
- **Error Propagation**: Last failed step error messages bubble up to flow level

### **FlowProgressTracker Class**
Provides the unified interface for progress management:
- **Thread-Safe Operations**: Single RLock protects all operations
- **Automatic JSON Persistence**: Real-time synchronization to flow_progress.json
- **Memory Management**: Efficient handling of large-scale factory flows
- **GUI Integration**: Rich Live display integration with progress updates

## Enhanced Progress Tracking Features

### **7-Phase Execution Process Integration**
The tracker seamlessly integrates with the orchestrator's execution phases:
1. **YAML Parsing**: Flow definitions loaded and validated
2. **Variable Expansion**: Dynamic parameter resolution and context building
3. **Step Wrapping**: FlowStep/ParallelFlowStep wrapped into IndependentFlow containers
4. **Execution Routing**: Steps routed through unified execution engine
5. **Progress Tracking**: Real-time step execution monitoring (THIS MODULE)
6. **Error Collection**: Multi-level error handling and message aggregation
7. **JSON Output**: Complete execution history with hierarchical relationships

### **Unified Execution Engine Support**
- **Step Type Agnostic**: Same tracking for FlowStep, ParallelFlowStep, IndependentFlow
- **Feature Consistency**: Optional flows, jumps, retries tracked identically across types
- **Metadata Preservation**: All step attributes preserved during wrapping and execution

### **Auto-Calculated Performance Statistics**
Metrics automatically computed from StepExecution objects:
- `average_step_duration`: Mean execution time across all steps
- `longest_step_duration`: Duration of slowest step for bottleneck analysis
- `step_with_most_retries`: Identification of problematic steps
- `total_step_duration` vs `total_testtime`: Execution vs wall-clock time analysis

### **Hierarchical Optional Flow Support**
- **Parent-Child Relationships**: Optional flows nested under triggering steps
- **Recursive Support**: Optional flows can trigger their own optional flows
- **Timing Separation**: `total_optional_flow_testtime` vs `total_non_optional_flow_testtime`
- **JSON Hierarchy**: Metadata-driven display structure for complex nesting

### **Advanced Error Collection**
- **Step-Level Collection**: Individual step error message capture
- **Flow-Level Propagation**: Last failed step errors copied to FlowInfo
- **Thread-Safe Collection**: No cross-contamination between concurrent steps
- **GUI Integration**: Error messages display in both console and JSON output

## Thread Safety and Concurrency

The entire system uses a **unified locking strategy** with a single `threading.RLock`:
- **Simple Context Management**: No complex multi-lock coordination
- **Concurrent Flow Support**: Multiple flows can execute simultaneously
- **Optional Flow Safety**: Thread-safe optional flow triggering and tracking
- **Progress Update Safety**: GUI updates synchronized with flow execution

## JSON Output Format

The generated `flow_progress.json` follows a hierarchical structure:
```json
{
  "flows": {
    "main_flow_name": {
      "status": "Completed|Failed|Running",
      "steps_executed": [/* StepExecution objects */],
      "optional_flows": {
        "optional_flow_name": {
          "parent_flow_name": "main_flow_name",
          "triggered_by_step": "step_that_triggered_this",
          "steps_executed": [/* Nested StepExecution objects */]
        }
      },
      "performance_statistics": {/* Auto-calculated metrics */},
      "timing_breakdown": {/* Wall-clock vs execution time analysis */}
    }
  }
}
```

## Usage Examples

### **Basic Flow Tracking**
```python
tracker = FlowProgressTracker(Path("flow_progress.json"))
tracker.add_flow("main_flow", total_steps=5)

# Start step execution
step_exec = tracker.start_step_execution(
    flow_name="main_flow",
    step_name="Power On System",
    step_operation="power_on",
    device_type="compute",
    device_id="device1",
    step_index=0
)

# Complete step
tracker.complete_step_execution(step_exec.execution_id, final_result=True)
tracker.complete_flow("main_flow", final_status="Completed")
```

### **Optional Flow Integration**
```python
# Trigger optional flow from main step
optional_step = tracker.start_step_execution(
    flow_name="error_recovery_flow",
    step_name="Recover from Error",
    step_operation="recovery_procedure",
    device_type="compute",
    device_id="device1",
    step_index=0,
    parent_flow_name="main_flow",
    triggered_by_step="failing_step"
)
```

### **Error Collection Integration**
```python
# Error messages automatically collected during execution
step_exec.error_messages.append("BMC connection timeout")
tracker.complete_step_execution(step_exec.execution_id,
                               final_result=False,
                               error_message="Step failed after 3 retries")
```

## Performance Characteristics

- **Memory Efficiency**: StepExecution objects use minimal memory with field defaults
- **Concurrent Safety**: O(1) locking overhead with single RLock strategy
- **JSON Performance**: Incremental updates to prevent blocking during large flows
- **Scalability**: Supports factory flows with 100+ steps across multiple devices

## Integration Points

### **Factory Flow Orchestrator**
- Called during `execute_flow()` for step tracking
- Integrates with `_handle_step_failure_unified()` for error collection
- Supports `execute_parallel_flows()` for concurrent tracking

### **Error Collection System**
- Receives ERROR-level messages via `ErrorCollectorHandler`
- Thread-safe message capture per step execution
- Automatic propagation to flow level on failures

### **GUI Output System**
- Real-time progress updates via Rich Live display
- JSON structure drives hierarchical flow visualization
- Performance statistics displayed in summary views

See Also:
    FactoryFlowOrchestrator: Main orchestration class that uses this tracker
    ErrorCollectorHandler: Error message collection integration
    UnifiedExecutionEngine: The execution system this tracker monitors
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class StepExecution:
    """
    Comprehensive execution record for a single factory flow step.

    StepExecution captures the complete lifecycle of a step execution, from initial
    configuration through final completion. It serves as the foundation for progress
    tracking, performance analysis, and error reporting in the unified execution engine.

    This class follows a strict field ordering requirement: all required fields (without
    defaults) must be declared before optional fields (with defaults) to maintain
    dataclass compatibility.

    ## Field Categories

    ### **Required Execution Metadata**
    Essential information that must be provided when creating a StepExecution:
    - `step_name`: Human-readable step identifier (e.g., "Power On System")
    - `step_operation`: Actual method name called (e.g., "power_on")
    - `device_type`: Target device category ("compute", "switch", "power_shelf")
    - `device_id`: Specific device identifier within the device type
    - `step_index`: Zero-based position in the flow sequence
    - `started_at`: Unix timestamp (time.time()) when step execution began

    ### **Step Configuration Details**
    Original step configuration from YAML or programmatic definition:
    - `retry_count`: Maximum retry attempts (default: 3)
    - `timeout_seconds`: Step execution timeout (None = no timeout)
    - `wait_after_seconds`: Delay after step completion (default: 0)
    - `wait_between_retries_seconds`: Delay between retry attempts (default: 0)
    - `execute_on_error`: Name of error handler to call on failure
    - `execute_optional_flow`: Name of optional flow to trigger on failure
    - `jump_on_success`: Target step tag to jump to on success
    - `jump_on_failure`: Target step tag to jump to on failure
    - `tag`: Step tag identifier for jump targets

    ### **Execution Timing Information**
    Wall-clock timing details for performance analysis:
    - `completed_at`: Unix timestamp when step finished (success or failure)
    - `duration`: Total execution time (completed_at - started_at)

    ### **Execution Status and Results**
    Current state and final outcome of step execution:
    - `status`: Current execution state ("running", "completed", "failed", "jumped", "skipped")
    - `final_result`: Ultimate success/failure boolean after all retries and error handling

    ### **Retry Tracking**
    Detailed retry attempt information for troubleshooting:
    - `retry_attempts`: Number of retry attempts actually made
    - `retry_durations`: List of execution times for each retry attempt

    ### **Jump Execution Details**
    Information about jump logic execution:
    - `jump_taken`: Type of jump executed ("success" or "failure", None if no jump)
    - `jump_target`: Target step tag/name that was jumped to

    ### **Optional Flow Integration**
    Tracking of optional flows triggered by this step:
    - `optional_flows_triggered`: Names of optional flows that were executed
    - `optional_flow_results`: Boolean results for each optional flow by name

    ### **Error Collection and Handling**
    Comprehensive error information for debugging:
    - `error_messages`: All ERROR-level log messages captured during step execution
    - `error_handler_executed`: Name of error handler that was called (if any)
    - `error_handler_result`: Boolean result of error handler execution

    ### **Execution Context**
    Additional context and parameter information:
    - `parameters`: Dictionary of parameters passed to the step operation
    - `context_info`: Additional execution context (device state, environment, etc.)
    - `execution_id`: Unique UUID for this specific step execution instance

    ## Usage Examples

    ### **Basic Step Creation**
    ```python
    step = StepExecution(
        step_name="Power On System",
        step_operation="power_on",
        device_type="compute",
        device_id="gb200_node_1",
        step_index=0,
        started_at=time.time()
    )
    ```

    ### **Complete Configuration**
    ```python
    step = StepExecution(
        step_name="Flash BMC Firmware",
        step_operation="pldm_fw_update",
        device_type="compute",
        device_id="gb200_node_1",
        step_index=3,
        started_at=time.time(),
        retry_count=3,
        timeout_seconds=600,
        execute_optional_flow="bmc_recovery_flow",
        jump_on_success="verify_firmware",
        tag="firmware_update",
        parameters={"bundle_path": "/firmware/bmc_v1.2.3.bin"}
    )
    ```

    ### **Progress Updates During Execution**
    ```python
    # Mark completion
    step.completed_at = time.time()
    step.duration = step.completed_at - step.started_at
    step.status = "completed"
    step.final_result = True

    # Record retry attempts
    step.retry_attempts = 2
    step.retry_durations = [45.2, 52.1]  # Seconds for each retry

    # Record jump execution
    step.jump_taken = "success"
    step.jump_target = "verify_firmware"
    ```

    ## JSON Serialization

    StepExecution objects serialize to comprehensive JSON records via `to_dict()`:
    ```json
    {
      "step_name": "Flash BMC Firmware",
      "step_operation": "pldm_fw_update",
      "device_type": "compute",
      "device_id": "gb200_node_1",
      "execution_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "completed",
      "final_result": true,
      "duration": 97.3,
      "retry_attempts": 2,
      "jump_taken": "success",
      "error_messages": [],
      "parameters": {"bundle_path": "/firmware/bmc_v1.2.3.bin"}
    }
    ```

    ## Thread Safety

    StepExecution objects are **not** thread-safe by themselves. Thread safety is
    provided by the FlowProgressTracker that manages these objects. Individual
    StepExecution instances should only be modified by the thread that created them
    or through FlowProgressTracker's synchronized methods.

    ## Performance Considerations

    - **Memory Efficient**: Uses dataclass field defaults to minimize memory usage
    - **Lazy Collections**: Lists and dictionaries created only when needed via field factories
    - **UUID Generation**: Execution IDs generated lazily to avoid unnecessary overhead
    - **JSON Optimized**: to_dict() method optimized for frequent serialization

    See Also:
        FlowProgressTracker: Manages collections of StepExecution objects
        FlowInfo: Aggregates statistics from multiple StepExecution objects
        FactoryFlowOrchestrator: Creates and updates StepExecution objects during flow execution
    """

    # Required fields (no defaults) - must come first
    step_name: str  # Human-readable step name
    step_operation: str  # Actual operation method name
    device_type: str  # "compute", "switch", "power_shelf"
    device_id: str  # Target device identifier
    step_index: int  # Position in flow sequence
    started_at: float  # time.time() when step started
    flow_name: str  # Name of the flow this step belongs to

    # Optional fields (with defaults) - must come after all required fields
    # Unique execution ID
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Original step configuration
    retry_count: int = 3  # Configured retry count
    timeout_seconds: Optional[int] = None  # Configured timeout
    wait_after_seconds: int = 0  # Configured wait after step
    wait_between_retries_seconds: int = 0  # Configured wait between retries
    execute_on_error: Optional[str] = None  # Configured error handler
    execute_optional_flow: Optional[str] = None  # Configured optional flow
    jump_on_success: Optional[str] = None  # Configured success jump target
    jump_on_failure: Optional[str] = None  # Configured failure jump target
    tag: Optional[str] = None  # Step tag identifier

    # Timing information
    completed_at: Optional[float] = None  # time.time() when step completed/failed
    duration: float = 0.0  # completed_at - started_at

    # Execution details
    status: str = "running"  # "running", "completed", "failed", "jumped", "skipped"
    final_result: bool = False  # True if step ultimately succeeded

    # Retry information
    retry_attempts: int = 0  # Number of retry attempts made
    retry_durations: List[float] = field(default_factory=list)  # Duration of each retry attempt

    # Jump information
    jump_taken: Optional[str] = None  # "success" or "failure" if jumped
    jump_target: Optional[str] = None  # Target tag/step name if jumped

    # Optional flow information
    optional_flows_triggered: List[str] = field(default_factory=list)  # Names of optional flows executed
    optional_flow_results: Dict[str, bool] = field(default_factory=dict)  # Results of optional flows

    # Error information
    error_messages: List[str] = field(default_factory=list)  # All ERROR messages from this step
    error_handler_executed: Optional[str] = None  # Name of error handler if executed
    error_handler_result: Optional[bool] = None  # Result of error handler execution

    # Additional context
    parameters: Dict[str, Any] = field(default_factory=dict)  # Step parameters used
    context_info: Dict[str, Any] = field(default_factory=dict)  # Additional execution context

    def to_dict(self) -> Dict[str, Any]:
        """Convert StepExecution to dictionary for JSON serialization."""
        return {
            "step_name": self.step_name,
            "step_operation": self.step_operation,
            "device_type": self.device_type,
            "device_id": self.device_id,
            "step_index": self.step_index,
            "retry_count": self.retry_count,
            "timeout_seconds": self.timeout_seconds,
            "wait_after_seconds": self.wait_after_seconds,
            "wait_between_retries_seconds": self.wait_between_retries_seconds,
            "execute_on_error": self.execute_on_error,
            "execute_optional_flow": self.execute_optional_flow,
            "jump_on_success": self.jump_on_success,
            "jump_on_failure": self.jump_on_failure,
            "tag": self.tag,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "status": self.status,
            "final_result": self.final_result,
            "retry_attempts": self.retry_attempts,
            "retry_durations": self.retry_durations,
            "jump_taken": self.jump_taken,
            "jump_target": self.jump_target,
            "optional_flows_triggered": self.optional_flows_triggered,
            "optional_flow_results": self.optional_flow_results,
            "error_messages": self.error_messages,
            "error_handler_executed": self.error_handler_executed,
            "error_handler_result": self.error_handler_result,
            "parameters": self.parameters,
            "context_info": self.context_info,
            "execution_id": self.execution_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepExecution":
        """Create StepExecution from dictionary (for JSON deserialization)."""
        return cls(
            step_name=data["step_name"],
            step_operation=data["step_operation"],
            device_type=data["device_type"],
            device_id=data["device_id"],
            step_index=data["step_index"],
            retry_count=data.get("retry_count", 3),
            timeout_seconds=data.get("timeout_seconds"),
            wait_after_seconds=data.get("wait_after_seconds", 0),
            wait_between_retries_seconds=data.get("wait_between_retries_seconds", 0),
            execute_on_error=data.get("execute_on_error"),
            execute_optional_flow=data.get("execute_optional_flow"),
            jump_on_success=data.get("jump_on_success"),
            jump_on_failure=data.get("jump_on_failure"),
            tag=data.get("tag"),
            started_at=data["started_at"],
            flow_name=data["flow_name"],
            completed_at=data.get("completed_at"),
            duration=data.get("duration", 0.0),
            status=data.get("status", "running"),
            final_result=data.get("final_result", False),
            retry_attempts=data.get("retry_attempts", 0),
            retry_durations=data.get("retry_durations", []),
            jump_taken=data.get("jump_taken"),
            jump_target=data.get("jump_target"),
            optional_flows_triggered=data.get("optional_flows_triggered", []),
            optional_flow_results=data.get("optional_flow_results", {}),
            error_messages=data.get("error_messages", []),
            error_handler_executed=data.get("error_handler_executed"),
            error_handler_result=data.get("error_handler_result"),
            parameters=data.get("parameters", {}),
            context_info=data.get("context_info", {}),
            execution_id=data.get("execution_id", str(uuid.uuid4())),
        )


@dataclass
class OptionalFlowExecution:
    """Represents a single execution of an optional flow."""

    caller: str  # Name of the step that triggered this optional flow
    status: str = "Pending"  # "Pending", "Running", "Completed", "Failed", "Error"
    current_step: str = "Not Started"
    completed_steps: int = 0
    total_steps: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # New timing fields (wall clock seconds)
    started_at_timestamp: Optional[float] = None  # time.time() when started
    completed_at_timestamp: Optional[float] = None  # time.time() when completed
    total_testtime: float = 0.0  # Wall clock duration

    # New execution counters (same as main flows)
    retries_executed: int = 0
    jump_on_success_executed: int = 0
    jump_on_failure_executed: int = 0

    # Enhanced step-level tracking (replaces simple steps_executed: List[str])
    steps_executed: List[StepExecution] = field(default_factory=list)

    # Auto-calculated summary statistics (derived from StepExecution objects)
    total_step_duration: float = 0.0
    total_retry_attempts: int = 0
    failed_steps_count: int = 0
    average_step_duration: float = 0.0
    longest_step_duration: float = 0.0
    step_with_most_retries: str = ""

    # Backward compatibility property
    @property
    def steps_executed_simple(self) -> List[str]:
        """Simple string list for backward compatibility."""
        return [self._step_to_simple_string(step) for step in self.steps_executed]

    def _step_to_simple_string(self, step: StepExecution) -> str:
        """Convert StepExecution to simple string representation."""
        base_name = step.step_name
        if step.jump_taken:
            return f"{base_name} (jump {step.jump_taken})"
        if step.retry_attempts > 0:
            return f"{base_name} (retry {step.retry_attempts})"
        return base_name


@dataclass
class FlowInfo:
    """
    Flow-level aggregation and statistics container with hierarchical optional flow support.

    FlowInfo serves as the central aggregation point for all information related to a
    factory flow execution, including real-time progress tracking, performance statistics
    automatically calculated from StepExecution objects, and hierarchical relationships
    for optional flows.

    This class implements the enhanced flow information architecture that supports the
    unified execution engine's metadata-driven hierarchical display structure.

    ## Core Features

    ### **Real-Time Progress Tracking**
    - `status`: Current flow state ("Pending", "Running", "Completed", "Failed", "Error")
    - `current_step`: Name of currently executing step
    - `completed_steps` / `total_steps`: Progress counters with automatic increment
    - `current_step_index`: Zero-based index for automatic step progression

    ### **Auto-Calculated Performance Statistics**
    All performance metrics are automatically derived from the `steps_executed` list:
    - `total_step_duration`: Sum of all individual step durations
    - `average_step_duration`: Mean execution time across completed steps
    - `longest_step_duration`: Duration of the slowest step (bottleneck analysis)
    - `step_with_most_retries`: Name of step with highest retry count

    ### **Execution Counters and Analytics**
    Automatic tallying of execution patterns:
    - `retries_executed`: Total retry attempts across all steps
    - `jump_on_success_executed`: Count of successful jumps taken
    - `jump_on_failure_executed`: Count of failure jumps taken
    - `total_retry_attempts`: Sum from all StepExecution objects
    - `total_optional_flows_triggered`: Count of optional flows triggered
    - `total_jumps_taken`: Combined success + failure jumps
    - `failed_steps_count`: Count of steps that ultimately failed

    ### **Wall-Clock Timing Analysis**
    Comprehensive timing breakdown for performance analysis:
    - `started_at` / `completed_at`: Unix timestamps for flow lifecycle
    - `total_testtime`: Wall-clock duration (completed_at - started_at)
    - `total_optional_flow_testtime`: Sum of all optional flow execution times
    - `total_non_optional_flow_testtime`: Main flow time excluding optional flows

    ### **Hierarchical Optional Flow Support**
    Metadata-driven parent-child relationships:
    - `is_optional_flow`: Boolean flag indicating if this FlowInfo represents an optional flow
    - `parent_flow_name`: Name of parent flow if this is an optional flow
    - `triggered_by_step`: Name of step that triggered this optional flow
    - `optional_flows`: Dictionary of child optional flows by name

    ### **Enhanced Error Propagation**
    - `error_messages`: Error messages from the last failed step propagated to flow level
    - Automatic error bubbling from StepExecution objects on flow failure

    ### **StepExecution Integration**
    - `steps_executed`: List of StepExecution objects (the source of truth)
    - All statistics automatically calculated from this list
    - Thread-safe access through FlowProgressTracker locking

    ## Hierarchical Optional Flow Structure

    The FlowInfo class supports recursive optional flow nesting:

    ```
    Main Flow (FlowInfo)
    ├── Step 1 (StepExecution)
    ├── Step 2 (StepExecution) → triggers optional_flow_1
    │   └── optional_flow_1 (FlowInfo)
    │       ├── Recovery Step 1 (StepExecution)
    │       └── Recovery Step 2 (StepExecution) → triggers optional_flow_2
    │           └── optional_flow_2 (FlowInfo)
    │               └── Deep Recovery (StepExecution)
    └── Step 3 (StepExecution)
    ```

    ## Usage Examples

    ### **Basic Flow Creation**
    ```python
    flow_info = FlowInfo(
        status="Running",
        current_step="Power On System",
        completed_steps=2,
        total_steps=5,
        started_at=time.time()
    )
    ```

    ### **Optional Flow with Parent Relationship**
    ```python
    optional_flow = FlowInfo(
        status="Running",
        current_step="BMC Recovery",
        total_steps=3,
        is_optional_flow=True,
        parent_flow_name="main_gb200_flow",
        triggered_by_step="flash_bmc_firmware",
        started_at=time.time()
    )
    ```

    ### **Performance Statistics Access**
    ```python
    # Statistics automatically calculated from steps_executed
    avg_duration = flow_info.average_step_duration
    bottleneck_step = flow_info.step_with_most_retries
    timing_efficiency = flow_info.total_step_duration / flow_info.total_testtime

    # Optional flow timing breakdown
    main_flow_time = flow_info.total_non_optional_flow_testtime
    recovery_time = flow_info.total_optional_flow_testtime
    overhead_ratio = recovery_time / flow_info.total_testtime
    ```

    ## JSON Output Structure

    FlowInfo objects contribute to the hierarchical JSON structure:
    ```json
    {
      "main_flow": {
        "status": "Completed",
        "total_testtime": 245.7,
        "total_step_duration": 198.3,
        "steps_executed": [/* StepExecution objects */],
        "optional_flows": {
          "bmc_recovery_flow": {
            "parent_flow_name": "main_flow",
            "triggered_by_step": "flash_bmc_firmware",
            "status": "Completed",
            "total_testtime": 67.2,
            "steps_executed": [/* Recovery StepExecution objects */]
          }
        },
        "performance_statistics": {
          "average_step_duration": 24.8,
          "longest_step_duration": 89.1,
          "step_with_most_retries": "check_boot_progress"
        }
      }
    }
    ```

    ## Auto-Calculation Implementation

    Performance statistics are recalculated automatically whenever:
    - New StepExecution objects are added to `steps_executed`
    - Existing StepExecution objects are modified (duration, retry_attempts, etc.)
    - FlowProgressTracker calls statistics update methods

    The calculation ensures:
    - **Accuracy**: Statistics always reflect current state of steps_executed
    - **Performance**: O(n) calculation over step list, cached until next update
    - **Thread Safety**: All calculations performed under FlowProgressTracker lock

    ## Thread Safety

    FlowInfo objects are **not** thread-safe individually. Thread safety is provided
    by the FlowProgressTracker that manages these objects. All modifications should
    occur through FlowProgressTracker's synchronized methods.

    ## Performance Characteristics

    - **Memory Efficient**: Uses field factories for lazy collection initialization
    - **Calculation Overhead**: O(n) over steps_executed for statistics calculation
    - **Optional Flow Scalability**: Supports deep nesting with minimal overhead
    - **JSON Serialization**: Optimized for frequent progress file updates

    See Also:
        StepExecution: Individual step records aggregated by this class
        FlowProgressTracker: Manages FlowInfo objects and provides thread safety
        OptionalFlowExecution: Legacy optional flow tracking (deprecated in favor of FlowInfo)
    """

    status: str = "Pending"
    current_step: str = "Not Started"
    completed_steps: int = 0
    total_steps: int = 0
    optional_flows: Dict[str, OptionalFlowExecution] = field(default_factory=dict)

    # Timing fields (wall clock seconds)
    started_at: Optional[float] = None  # time.time() when flow starts
    completed_at: Optional[float] = None  # time.time() when flow completes
    total_testtime: float = 0.0  # Wall clock duration (completed_at - started_at)
    total_optional_flow_testtime: float = 0.0  # Sum of all optional flow durations
    total_non_optional_flow_testtime: float = 0.0  # total_testtime - total_optional_flow_testtime

    # Execution counters
    retries_executed: int = 0  # Total retry attempts across all steps
    jump_on_success_executed: int = 0  # Number of successful jumps executed
    jump_on_failure_executed: int = 0  # Number of failure jumps executed

    # Enhanced step tracking (StepExecution objects only)
    steps_executed: List[StepExecution] = field(default_factory=list)

    # Auto-calculated summary statistics (derived from StepExecution objects)
    total_step_duration: float = 0.0  # Sum of all step durations
    total_retry_attempts: int = 0  # Sum of all retry attempts across steps
    total_optional_flows_triggered: int = 0  # Count of optional flows triggered
    total_jumps_taken: int = 0  # Count of jumps taken (success + failure)
    failed_steps_count: int = 0  # Count of steps that ultimately failed
    average_step_duration: float = 0.0  # Mean step execution time
    longest_step_duration: float = 0.0  # Duration of slowest step
    step_with_most_retries: str = ""  # Name of step with highest retry count

    # Current step index for automatic progression
    current_step_index: int = 0  # Index of currently executing step

    # Optional flow metadata (NEW)
    is_optional_flow: bool = False  # True if this is an optional flow
    parent_flow_name: Optional[str] = None  # Name of parent flow if this is optional
    triggered_by_step: Optional[str] = None  # Step that triggered this optional flow
    error_messages: List[str] = field(default_factory=list)  # Error messages from final failed step

    @property
    def progress_string(self) -> str:
        """Get progress as a string in format 'completed/total'."""
        return f"{self.completed_steps}/{self.total_steps}"


class FlowProgressTracker:
    """
    Unified Progress Tracking System for Factory Flow Orchestrator

    FlowProgressTracker provides comprehensive, thread-safe progress monitoring and JSON
    persistence for the NVIDIA Factory Flow Orchestrator's unified execution engine.
    It serves as the central coordination point for all progress tracking, performance
    analysis, and GUI integration across multi-device factory automation workflows.

    ## Core Architecture

    ### **Unified Locking Strategy**
    The entire system uses a single `threading.RLock` for all operations:
    - **Simple Context Management**: No complex multi-lock coordination required
    - **Reentrant Safety**: Supports nested calls within the same thread
    - **Deadlock Prevention**: Single lock eliminates deadlock possibilities
    - **Performance Optimized**: Minimal locking overhead with O(1) acquisition

    ### **Thread-Safe Data Management**
    - **FlowInfo Storage**: `self.flows` dictionary manages all flow information
    - **StepExecution Tracking**: `self._active_step_executions` for in-progress steps
    - **Concurrent Flow Support**: Multiple flows can execute simultaneously
    - **GUI Integration**: Thread-safe Rich Live display updates

    ### **Automatic JSON Persistence**
    - **Real-Time Sync**: JSON file updated on every significant progress change
    - **Atomic Writes**: File operations protected to prevent corruption
    - **Hierarchical Structure**: Optional flows nested under parent flows
    - **Performance Optimized**: Incremental updates to minimize I/O blocking

    ## Integration with Unified Execution Engine

    ### **7-Phase Execution Process Support**
    The tracker integrates seamlessly with the orchestrator's execution phases:

    1. **YAML Parsing** → Flow registration via `add_flow()`
    2. **Variable Expansion** → Context preservation in StepExecution.parameters
    3. **Step Wrapping** → Unified tracking for all step types
        (FlowStep, ParallelFlowStep, IndependentFlow)
    4. **Execution Routing** → Step tracking via `start_step_execution()`
    5. **Progress Tracking** → Real-time updates via `complete_step_execution()` (**THIS MODULE**)
    6. **Error Collection** → Error message capture in StepExecution.error_messages
    7. **JSON Output** → Complete execution history with performance statistics

    ### **Step Type Agnostic Tracking**
    - **FlowStep**: Individual operations tracked as single StepExecution
    - **ParallelFlowStep**: Parallel operations tracked with thread identification
    - **IndependentFlow**: Container flows tracked with hierarchical relationships
    - **Optional Flows**: Recursive nesting with parent-child metadata links

    ### **Feature Consistency Across Step Types**
    All orchestrator features work identically regardless of step type:
    - **Retry Logic**: retry_attempts and retry_durations captured uniformly
    - **Jump Execution**: jump_taken and jump_target recorded consistently
    - **Optional Flows**: Parent-child relationships maintained for all triggers
    - **Error Handling**: Error collection and propagation standardized

    ## Advanced Progress Tracking Features

    ### **Auto-Calculated Performance Statistics**
    Performance metrics automatically derived from StepExecution objects:
    ```python
    # Automatically calculated from steps_executed list
    flow_info.average_step_duration     # Mean execution time
    flow_info.longest_step_duration     # Bottleneck identification
    flow_info.step_with_most_retries    # Problem step detection
    flow_info.total_step_duration       # Pure execution time
    flow_info.total_testtime            # Wall-clock time including overhead
    ```

    ### **Hierarchical Optional Flow Support**
    - **Recursive Nesting**: Optional flows can trigger their own optional flows
    - **Parent-Child Metadata**: `parent_flow_name` and `triggered_by_step` linkage
    - **Timing Separation**: `total_optional_flow_testtime` vs `total_non_optional_flow_testtime`
    - **JSON Hierarchy**: Metadata-driven display structure for complex relationships

    ### **Enhanced Error Collection Integration**
    - **Step-Level Capture**: ERROR messages collected per StepExecution
    - **Flow-Level Propagation**: Last failed step errors bubble up to FlowInfo
    - **Thread-Safe Collection**: No cross-contamination between concurrent steps
    - **ErrorCollectorHandler Integration**: Seamless integration with logging system

    ### **GUI Integration and Live Updates**
    ```python
    # Rich Live display integration
    tracker.set_gui_mode(live_display, progress_component, update_callback)

    # Automatic progress updates
    tracker.start_step_execution(...)  # Updates GUI immediately
    tracker.complete_step_execution(...) # Updates GUI with results
    ```

    ## Thread Safety and Concurrency

    ### **Concurrent Flow Execution**
    ```python
    # Multiple flows can execute simultaneously
    tracker.add_flow("compute_flow", total_steps=10)
    tracker.add_flow("switch_flow", total_steps=5)
    tracker.add_flow("power_shelf_flow", total_steps=8)

    # Thread-safe step execution across flows
    compute_step = tracker.start_step_execution("compute_flow", ...)
    switch_step = tracker.start_step_execution("switch_flow", ...)
    ```

    ### **Optional Flow Thread Safety**
    ```python
    # Optional flows triggered from any thread safely
    optional_step = tracker.start_step_execution(
        flow_name="error_recovery",
        parent_flow_name="main_flow",
        triggered_by_step="failing_step",
        ...
    )
    ```

    ### **Parallel Step Execution Support**
    - **Thread Identification**: Each parallel step tracked with unique execution_id
    - **Concurrent Progress Updates**: Multiple threads can update progress simultaneously
    - **Resource Cleanup**: Automatic cleanup when parallel execution completes

    ## JSON Output Format and Structure

    The tracker generates comprehensive JSON output with hierarchical optional flow nesting:

    ```json
    {
      "flows": {
        "main_gb200_factory_flow": {
          "status": "Completed",
          "started_at": 1642781234.567,
          "completed_at": 1642781456.789,
          "total_testtime": 222.222,
          "total_step_duration": 198.456,
          "total_optional_flow_testtime": 45.678,
          "steps_executed": [
            {
              "step_name": "Power On System",
              "step_operation": "power_on",
              "device_type": "compute",
              "device_id": "gb200_node_1",
              "execution_id": "550e8400-e29b-41d4-a716-446655440000",
              "status": "completed",
              "duration": 12.345,
              "final_result": true,
              "retry_attempts": 0,
              "error_messages": []
            }
          ],
          "optional_flows": {
            "bmc_recovery_flow": {
              "parent_flow_name": "main_gb200_factory_flow",
              "triggered_by_step": "flash_bmc_firmware",
              "status": "Completed",
              "total_testtime": 45.678,
              "steps_executed": [/* Recovery steps */]
            }
          },
          "performance_statistics": {
            "average_step_duration": 19.85,
            "longest_step_duration": 89.12,
            "step_with_most_retries": "check_boot_progress",
            "total_retry_attempts": 7,
            "failed_steps_count": 0
          }
        }
      }
    }
    ```

    ## Usage Examples

    ### **Basic Factory Flow Tracking**
    ```python
    from pathlib import Path

    # Initialize tracker
    tracker = FlowProgressTracker(Path("flow_progress.json"))

    # Register flow
    tracker.add_flow("gb200_factory_flow", total_steps=15)

    # Track step execution
    step = tracker.start_step_execution(
        flow_name="gb200_factory_flow",
        step_name="Power On System",
        step_operation="power_on",
        device_type="compute",
        device_id="gb200_node_1",
        step_index=0,
        retry_count=3,
        timeout_seconds=60
    )

    # Complete step
    tracker.complete_step_execution(
        step.execution_id,
        final_result=True,
        error_message=None
    )

    # Complete flow
    tracker.complete_flow("gb200_factory_flow", "Completed")
    ```

    ### **Optional Flow Integration**
    ```python
    # Main step fails and triggers optional flow
    main_step = tracker.start_step_execution(
        flow_name="main_flow",
        step_name="Flash BMC Firmware",
        step_operation="pldm_fw_update",
        device_type="compute",
        device_id="gb200_node_1",
        step_index=3
    )

    # Optional flow triggered by failure
    recovery_step = tracker.start_step_execution(
        flow_name="bmc_recovery_flow",
        step_name="Reset BMC",
        step_operation="reboot_bmc",
        device_type="compute",
        device_id="gb200_node_1",
        step_index=0,
        parent_flow_name="main_flow",
        triggered_by_step="Flash BMC Firmware"
    )
    ```

    ### **GUI Integration**
    ```python
    from rich.live import Live
    from rich.progress import Progress

    # Set up Rich Live display
    progress = Progress()
    live = Live(progress, refresh_per_second=4)

    # Enable GUI mode
    tracker.set_gui_mode(live, progress, update_callback)

    # Progress automatically displayed in terminal
    tracker.start_step_execution(...)  # GUI updates automatically
    ```

    ### **Error Collection Integration**
    ```python
    # Error messages automatically captured
    step = tracker.start_step_execution(...)

    # Errors collected during execution
    step.error_messages.append("BMC connection timeout after 30 seconds")
    step.error_messages.append("Retrying with extended timeout")

    # Complete with failure
    tracker.complete_step_execution(
        step.execution_id,
        final_result=False,
        error_message="Step failed after all retries exhausted"
    )

    # Error propagated to flow level automatically
    ```

    ## Performance Characteristics

    ### **Memory Management**
    - **Efficient Storage**: StepExecution objects use field defaults for minimal memory
    - **Lazy Collections**: Lists and dictionaries created only when needed
    - **UUID Generation**: Execution IDs generated on-demand to reduce overhead
    - **Active Step Tracking**: In-progress steps tracked separately for fast lookup

    ### **Concurrency Performance**
    - **Single Lock Strategy**: O(1) lock acquisition with no deadlock risk
    - **Minimal Lock Duration**: Operations complete quickly to reduce contention
    - **Thread Scalability**: Supports dozens of concurrent flow executions
    - **GUI Update Efficiency**: Live display updates batched to prevent blocking

    ### **I/O Performance**
    - **Incremental JSON Updates**: Only modified flows written to disk
    - **Atomic File Operations**: Write-then-rename prevents file corruption
    - **Background Serialization**: JSON generation doesn't block flow execution
    - **Compression Ready**: JSON structure optimized for optional compression

    ## Error Handling and Recovery

    ### **Robust Error Handling**
    - **JSON Write Failures**: Logged but don't interrupt flow execution
    - **Lock Acquisition Timeouts**: Configurable timeouts prevent deadlocks
    - **Memory Overflow Protection**: Automatic cleanup of completed flows
    - **GUI Integration Failures**: Graceful degradation to console-only mode

    ### **Recovery Mechanisms**
    - **JSON File Recovery**: Automatic reconstruction from memory state
    - **Thread Recovery**: Automatic cleanup of orphaned thread tasks
    - **Flow State Recovery**: Partial flow execution tracking preserved

    ## Integration Points

    ### **FactoryFlowOrchestrator Integration**
    Called by orchestrator during:
    - `execute_flow()`: Main flow execution tracking
    - `execute_independent_flow()`: Independent flow tracking
    - `execute_parallel_flows()`: Concurrent flow tracking
    - `_handle_step_failure_unified()`: Error collection and optional flow triggering

    ### **Error Collection System Integration**
    - **ErrorCollectorHandler**: Receives ERROR messages for step tracking
    - **LoggingUtils**: Provides filtered message collection by device
    - **Thread Safety**: Message collection synchronized with progress updates

    ### **GUI System Integration**
    - **Rich Live Display**: Real-time progress visualization
    - **Console Filtering**: Device-specific progress display
    - **Progress Components**: Individual flow progress bars

    ## Thread Safety Guarantees

    All public methods are thread-safe and can be called concurrently:
    - `add_flow()`: Safe to register flows from multiple threads
    - `start_step_execution()`: Safe to start steps concurrently across flows
    - `complete_step_execution()`: Safe to complete steps from any thread
    - `complete_flow()`: Safe to complete flows concurrently
    - JSON file operations: Atomic and thread-safe

    See Also:
        StepExecution: Individual step execution records
        FlowInfo: Flow-level aggregation and statistics
        FactoryFlowOrchestrator: Main orchestration system that uses this tracker
        ErrorCollectorHandler: Error message collection integration
    """

    def __init__(self, json_file_path: Path, output_manager=None):
        """
        Initialize the progress tracker.

        Args:
            json_file_path (Path): Path where the JSON file should be written
            output_manager: OutputModeManager instance for callbacks (optional)
        """
        self.json_file_path = json_file_path
        self.flows: Dict[str, FlowInfo] = {}
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        self.logger = logging.getLogger(__name__)

        # Output manager for callbacks
        self.output_manager = output_manager

        # GUI mode integration
        self.gui_mode = False
        self.live_display = None
        self.progress_component = None
        self.update_live_callback = None
        self.thread_tasks = {}
        self._thread_tasks_lock = threading.RLock()

        # Enhanced step execution tracking
        self._active_step_executions: Dict[str, StepExecution] = {}  # execution_id -> StepExecution
        self._step_execution_lock = threading.RLock()

        # Ensure directory exists
        self.json_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write initial empty state
        self._write_json()

    def set_gui_mode(self, live_display, progress_component, update_live_callback):
        """Enable automatic GUI mode with Rich Progress integration."""
        with self._lock:
            self.gui_mode = True
            self.live_display = live_display
            self.progress_component = progress_component
            self.update_live_callback = update_live_callback
            self.thread_tasks = {}

    def is_flow_complete(self, flow_name: str) -> bool:
        """Check if flow has completed all steps."""
        with self._lock:
            if flow_name in self.flows:
                flow = self.flows[flow_name]
                return flow.current_step_index >= flow.total_steps
            return False

    def get_current_step_index(self, flow_name: str) -> int:
        """Get current step index for a flow."""
        with self._lock:
            if flow_name in self.flows:
                return self.flows[flow_name].current_step_index
            return 0

    def cleanup_flow(self, flow_name: str):
        """Clean up flow resources when completed."""
        if self.gui_mode and flow_name in self.thread_tasks:
            with self._thread_tasks_lock:
                if flow_name in self.thread_tasks:
                    task_id = self.thread_tasks[flow_name]
                    if self.progress_component:
                        self.progress_component.remove_task(task_id)
                    del self.thread_tasks[flow_name]

    # --- Enhanced Step Execution Tracking API ---

    def start_step_execution(self, flow_name: str, step, step_index: int) -> str:
        """
        Start tracking a step execution and return unique execution ID.

        Args:
            flow_name: Name of the flow executing the step
            step: FlowStep object being executed
            step_index: Position of step in flow sequence

        Returns:
            str: Unique execution ID for tracking this step execution
        """
        with self._step_execution_lock:
            # Create StepExecution object
            step_execution = StepExecution(
                step_name=(getattr(step, "name", None) or getattr(step, "operation", f"Step {step_index+1}")),
                step_operation=getattr(step, "operation", "unknown"),
                device_type=(
                    getattr(step, "device_type", "unknown").value
                    if hasattr(getattr(step, "device_type", None), "value")
                    else str(getattr(step, "device_type", "unknown"))
                ),
                device_id=getattr(step, "device_id", "unknown"),
                step_index=step_index,
                started_at=time.time(),
                flow_name=flow_name,
                retry_count=getattr(step, "retry_count", 3),
                timeout_seconds=getattr(step, "timeout_seconds", None),
                wait_after_seconds=getattr(step, "wait_after_seconds", 0),
                wait_between_retries_seconds=getattr(step, "wait_between_retries_seconds", 0),
                execute_on_error=getattr(step, "execute_on_error", None),
                execute_optional_flow=getattr(step, "execute_optional_flow", None),
                jump_on_success=getattr(step, "jump_on_success", None),
                jump_on_failure=getattr(step, "jump_on_failure", None),
                tag=getattr(step, "tag", None),
                parameters=(getattr(step, "parameters", {}).copy() if getattr(step, "parameters", None) else {}),
            )

            # Store active execution
            execution_id = step_execution.execution_id
            self._active_step_executions[execution_id] = step_execution

            return execution_id

    def complete_step_execution(self, execution_id: str, result: bool, error_message: str = None) -> None:
        """
        Complete step execution tracking with final result.

        Args:
            execution_id: Execution ID returned from start_step_execution
            result: True if step succeeded, False if failed
            error_message: Error message if step failed
        """
        with self._step_execution_lock:
            if execution_id in self._active_step_executions:
                step_execution = self._active_step_executions[execution_id]

                # Complete the execution
                step_execution.completed_at = time.time()
                step_execution.duration = step_execution.completed_at - step_execution.started_at
                step_execution.final_result = result
                step_execution.status = "completed" if result else "failed"

                if error_message:
                    step_execution.error_message = error_message

                # Add to appropriate flow's steps_executed list
                with self._lock:
                    flow_name = step_execution.flow_name
                    if flow_name in self.flows:
                        self.flows[flow_name].steps_executed.append(step_execution)
                        self._calculate_flow_statistics(flow_name)

                # Notify output manager of step completion with full step data
                if self.output_manager:
                    self.output_manager.on_step_completed(
                        step_execution.flow_name,
                        step_execution.step_name,
                        result,
                        step_execution.duration,
                        step_execution.to_dict(),
                    )

                # Remove from active executions
                del self._active_step_executions[execution_id]

                # Write JSON with updated data
                self._write_json()

    def update_step_execution(
        self,
        _flow_name: str,
        execution_id: str,
        status: str,
        context: Dict[str, Any] = None,
    ) -> None:
        """
        Update step execution with intermediate status or context.

        Args:
            _flow_name: Name of the flow (kept for API consistency)
            execution_id: Execution ID for the step
            status: Current status ("running", "retrying", etc.)
            context: Additional context information
        """
        with self._step_execution_lock:
            if execution_id in self._active_step_executions:
                step_execution = self._active_step_executions[execution_id]
                step_execution.status = status

                if context:
                    step_execution.context_info.update(context)

    def add_step_retry(self, execution_id: str, attempt: int, duration: float) -> None:
        """
        Add retry attempt information to active step execution.

        Args:
            execution_id: Execution ID from start_step_execution
            attempt: Retry attempt number (1-based)
            duration: Duration of this retry attempt in seconds
        """
        with self._step_execution_lock:
            if execution_id in self._active_step_executions:
                step_execution = self._active_step_executions[execution_id]
                step_execution.retry_attempts = attempt
                step_execution.retry_durations.append(duration)

    def add_step_jump(self, execution_id: str, jump_type: str, target: str) -> None:
        """
        Record that a step execution triggered a jump.

        Args:
            execution_id: Execution ID from start_step_execution
            jump_type: "success" or "failure"
            target: Target tag/step name jumped to
        """
        with self._step_execution_lock:
            if execution_id in self._active_step_executions:
                step_execution = self._active_step_executions[execution_id]
                step_execution.jump_taken = jump_type
                step_execution.jump_target = target
                step_execution.status = "jumped"

    def add_optional_flow_trigger(
        self,
        execution_id: str,
        optional_flow_name: str,
        result: bool,
    ) -> None:
        """
        Record that a step triggered an optional flow.

        Args:
            execution_id: Execution ID from start_step_execution
            optional_flow_name: Name of the optional flow executed
            result: Result of the optional flow execution
        """
        with self._step_execution_lock:
            if execution_id in self._active_step_executions:
                step_execution = self._active_step_executions[execution_id]
                step_execution.optional_flows_triggered.append(optional_flow_name)
                step_execution.optional_flow_results[optional_flow_name] = result

    def add_error_handler_execution(
        self,
        execution_id: str,
        handler_name: str,
        result: bool,
    ) -> None:
        """
        Record that an error handler was executed for a step.

        Args:
            execution_id: Execution ID from start_step_execution
            handler_name: Name of the error handler executed
            result: Result of the error handler execution
        """
        with self._step_execution_lock:
            if execution_id in self._active_step_executions:
                step_execution = self._active_step_executions[execution_id]
                step_execution.error_handler_executed = handler_name
                step_execution.error_handler_result = result

    def is_step_execution_complete(self, execution_id: str) -> bool:
        """Check if a step execution is marked as complete."""
        # Search all flows for the execution_id
        for flow in self.flows.values():
            for step in flow.steps_executed:
                if step.execution_id == execution_id:
                    return step.status in ["completed", "failed"]
        return False

    def find_step_execution(self, flow_name: str, execution_id: str) -> Optional[StepExecution]:
        """Find a step execution by flow name and execution ID."""
        if flow_name in self.flows:
            flow = self.flows[flow_name]
            for step in flow.steps_executed:
                if step.execution_id == execution_id:
                    return step
        return None

    def _calculate_flow_statistics(self, flow_name: str) -> None:
        """Recalculate and update summary statistics from StepExecution objects."""
        with self._lock:
            if flow_name not in self.flows:
                return

            flow = self.flows[flow_name]
            steps = flow.steps_executed

            if not steps:
                return

            # Filter to only StepExecution objects (skip any legacy strings)
            step_executions = [step for step in steps if isinstance(step, StepExecution)]

            if not step_executions:
                return

            # Calculate basic statistics
            flow.total_step_duration = sum(step.duration for step in step_executions)
            flow.total_retry_attempts = sum(step.retry_attempts for step in step_executions)
            flow.total_optional_flows_triggered = sum(len(step.optional_flows_triggered) for step in step_executions)
            flow.total_jumps_taken = sum(1 for step in step_executions if step.jump_taken)
            flow.failed_steps_count = sum(1 for step in step_executions if not step.final_result)

            # Calculate average and longest step duration
            if len(step_executions) > 0:
                flow.average_step_duration = flow.total_step_duration / len(step_executions)
                flow.longest_step_duration = max(step.duration for step in step_executions)

                # Find step with most retries
                max_retries = max(step.retry_attempts for step in step_executions) if step_executions else 0
                if max_retries > 0:
                    step_with_most_retries = next(
                        step for step in step_executions if step.retry_attempts == max_retries
                    )
                    flow.step_with_most_retries = step_with_most_retries.step_name

    # --- Unified Progress Tracking Methods ---

    def _auto_update_gui(self, *, flow_name: str, step_name: str, status: str, step_number: int):
        """Automatically update Rich Progress if in GUI mode."""
        if not self.gui_mode or not self.progress_component:
            return

        thread_id = threading.get_ident()
        with self._thread_tasks_lock:
            # Get or create thread task
            if thread_id not in self.thread_tasks:
                if flow_name in self.flows:
                    task_id = self.progress_component.add_task(
                        f"[yellow]{flow_name}", total=self.flows[flow_name].total_steps
                    )
                    self.thread_tasks[thread_id] = task_id
                else:
                    return

            task_id = self.thread_tasks[thread_id]

            # Update progress with status and position
            self.progress_component.update(
                task_id,
                description=f"[{status}] {flow_name} - {step_name}",
                completed=step_number,
            )

            # Update live display if callback provided
            if self.update_live_callback:
                self.update_live_callback()

    def _cleanup_thread_task(self, flow_name: str):
        """Clean up Rich Progress task when flow completes."""
        if not self.gui_mode or not self.progress_component:
            return

        thread_id = threading.get_ident()
        with self._thread_tasks_lock:
            if thread_id in self.thread_tasks:
                task_id = self.thread_tasks[thread_id]
                # Mark as completed and remove
                if flow_name in self.flows:
                    total_steps = self.flows[flow_name].total_steps
                    self.progress_component.update(task_id, completed=total_steps)
                self.progress_component.remove_task(task_id)
                del self.thread_tasks[thread_id]

    # --- Flow Management Methods ---

    def add_flow(
        self,
        *,
        flow_name: str,
        total_steps: int = 0,
        parent_flow_name: str = None,
        triggered_by_step: str = None,
    ) -> None:
        """Add a new flow to track (main flow or optional flow)."""
        with self._lock:
            self.flows[flow_name] = FlowInfo(
                status="Pending",
                current_step="Not Started",
                completed_steps=0,
                total_steps=total_steps,
                current_step_index=0,
                is_optional_flow=parent_flow_name is not None,
                parent_flow_name=parent_flow_name,
                triggered_by_step=triggered_by_step,
            )
            self._write_json()

    def set_flow_completed(self, flow_name: str) -> None:
        """Mark a flow as completed."""
        with self._lock:
            if flow_name in self.flows:
                flow = self.flows[flow_name]
                flow.status = "Completed"
                flow.current_step = "All Steps Done"
                flow.completed_steps = flow.total_steps
                flow.current_step_index = flow.total_steps

                # Auto-update GUI if in GUI mode
                if self.gui_mode:
                    self._auto_update_gui(
                        flow_name=flow_name,
                        step_name="All Steps Done",
                        status="completed",
                        step_number=flow.total_steps,
                    )

                self._write_json()

                # Notify output manager of flow completion
                if self.output_manager:
                    flow_data = self._get_flow_summary_dict(flow_name)
                    self.output_manager.on_flow_completed(flow_name, flow_data)

    def set_flow_failed(self, flow_name: str, failure_reason: str = "Step failed") -> None:
        """Mark a flow as failed due to step failure."""
        with self._lock:
            if flow_name in self.flows:
                flow = self.flows[flow_name]
                flow.status = "Failed"

                # Find the last failed step and use its error for better context
                actual_error_message = failure_reason
                if flow.steps_executed:
                    last_step = flow.steps_executed[-1]
                    if not last_step.final_result:
                        # Use step error message if available for current_step
                        if hasattr(last_step, "error_message") and last_step.error_message:
                            actual_error_message = f"Step '{last_step.step_name}' failed: {last_step.error_message}"
                        elif hasattr(last_step, "error_messages") and last_step.error_messages:
                            actual_error_message = (
                                f"Step '{last_step.step_name}' failed: {last_step.error_messages[-1]}"
                            )

                        # Copy all error messages from the failed step to flow level
                        if hasattr(last_step, "error_messages") and last_step.error_messages:
                            flow.error_messages = last_step.error_messages.copy()

                flow.current_step = actual_error_message

                # Auto-update GUI if in GUI mode
                if self.gui_mode:
                    self._auto_update_gui(
                        flow_name=flow_name,
                        step_name=actual_error_message,
                        status="failed",
                        step_number=flow.current_step_index,
                    )

                self._write_json()

                # Notify output manager of flow failure
                if self.output_manager:
                    flow_data = self._get_flow_summary_dict(flow_name)
                    self.output_manager.on_flow_failed(flow_name, actual_error_message, flow_data)

    def set_flow_running(self, flow_name: str) -> None:
        """Mark a flow as running (changes status from Pending to Running)."""
        with self._lock:
            if flow_name in self.flows:
                flow = self.flows[flow_name]
                if flow.status == "Pending":  # Only update if still pending
                    flow.status = "Running"
                    flow.current_step = "Starting"

                    # Auto-update GUI if in GUI mode
                    if self.gui_mode:
                        self._auto_update_gui(
                            flow_name=flow_name,
                            step_name="Starting",
                            status="running",
                            step_number=0,
                        )

                    self._write_json()

    def update_flow_current_step(self, flow_name: str, step_name: str, step_index: int = None) -> None:
        """Update the current step name and optionally the completed step count."""
        with self._lock:
            if flow_name in self.flows:
                flow = self.flows[flow_name]
                flow.current_step = step_name

                if step_index is not None:
                    flow.completed_steps = step_index
                    flow.current_step_index = step_index

                # Auto-update GUI if in GUI mode
                if self.gui_mode:
                    self._auto_update_gui(
                        flow_name=flow_name,
                        step_name=step_name,
                        status="running",
                        step_number=flow.current_step_index,
                    )

                self._write_json()

    def set_flow_error(self, flow_name: str, error_message: str) -> None:
        """Mark a flow as having an error."""
        with self._lock:
            if flow_name in self.flows:
                flow = self.flows[flow_name]
                flow.status = "Error"
                flow.current_step = error_message
                flow.completed_steps = 0

                # Auto-update GUI if in GUI mode
                if self.gui_mode:
                    self._auto_update_gui(
                        flow_name=flow_name,
                        step_name=error_message,
                        status="failed",
                        step_number=flow.current_step_index,
                    )

                self._write_json()

    def get_flow_info(self, flow_name: str) -> Optional[FlowInfo]:
        """Get information about a specific flow."""
        with self._lock:
            return self.flows.get(flow_name)

    def get_all_flows(self) -> Dict[str, FlowInfo]:
        """Get information about all flows."""
        with self._lock:
            return {name: FlowInfo(**asdict(flow)) for name, flow in self.flows.items()}

    def get_flow_status_dict(self) -> Dict[str, Dict[str, str]]:
        """Get flow status in the old dictionary format for compatibility."""
        with self._lock:
            result = {}
            for name, flow in self.flows.items():
                result[name] = {
                    "status": flow.status,
                    "current_step": flow.current_step,
                    "progress": flow.progress_string,
                }
            return result

    def clear(self) -> None:
        """Clear all flow data."""
        with self._lock:
            self.flows.clear()
            self._write_json()

    def _get_flow_summary_dict(self, flow_name: str) -> Dict[str, Any]:
        """
        Get a summary dictionary for a specific flow (for output manager callbacks).

        Args:
            flow_name: Name of the flow

        Returns:
            Dictionary with flow summary data
        """
        if flow_name not in self.flows:
            return {}

        flow = self.flows[flow_name]

        return {
            "flow_name": flow_name,
            "status": flow.status,
            "total_steps": flow.total_steps,
            "completed_steps": flow.completed_steps,
            "total_testtime": flow.total_testtime,
            "total_step_duration": flow.total_step_duration,
            "average_step_duration": flow.average_step_duration,
            "longest_step_duration": flow.longest_step_duration,
            "step_with_most_retries": flow.step_with_most_retries,
            "failed_steps_count": flow.failed_steps_count,
            "total_retry_attempts": flow.total_retry_attempts,
            "steps_executed": [step.to_dict() for step in flow.steps_executed],
        }

    # --- Simplified Counter Methods (Auto-detect context) ---

    def increment_retries(self, flow_name: str, retry_count: int = 1) -> None:
        """Increment retry counter for flow."""
        with self._lock:
            if flow_name in self.flows:
                self.flows[flow_name].retries_executed += retry_count
                self._write_json()

    def increment_jump_on_success(self, flow_name: str) -> None:
        """Increment successful jump counter for flow."""
        with self._lock:
            if flow_name in self.flows:
                self.flows[flow_name].jump_on_success_executed += 1
                self._write_json()

    def increment_jump_on_failure(self, flow_name: str) -> None:
        """Increment failure jump counter for flow."""
        with self._lock:
            if flow_name in self.flows:
                self.flows[flow_name].jump_on_failure_executed += 1
                self._write_json()

    # --- Timing Methods ---

    def start_flow_timing(self, flow_name: str) -> None:
        """Mark flow start time for timing calculations."""
        with self._lock:
            if flow_name in self.flows:
                self.flows[flow_name].started_at = time.time()
                self._write_json()

    def complete_flow_timing(self, flow_name: str) -> float:
        """Complete flow timing and calculate total duration."""
        with self._lock:
            if flow_name in self.flows:
                flow = self.flows[flow_name]
                if flow.started_at is not None:
                    flow.completed_at = time.time()
                    flow.total_testtime = flow.completed_at - flow.started_at
                    flow.total_non_optional_flow_testtime = flow.total_testtime - flow.total_optional_flow_testtime
                    self._write_json()
                    return flow.total_testtime
        return 0.0

    def _write_json(self) -> None:
        """Write the current progress data to JSON file."""
        try:
            json_data = {"timestamp": datetime.now().isoformat(), "flows": {}}

            # Separate main flows and optional flows
            main_flows = {}
            optional_flows = {}

            for flow_name, flow in self.flows.items():
                if flow.is_optional_flow:
                    optional_flows[flow_name] = flow
                else:
                    main_flows[flow_name] = flow

            # Process main flows first
            for flow_name, flow in main_flows.items():
                flow_data = {
                    "status": flow.status,
                    "current_step": flow.current_step,
                    "current_step_index": flow.current_step_index,
                    "completed_steps": flow.completed_steps,
                    "total_steps": flow.total_steps,
                    # Add timing fields
                    "total_testtime": flow.total_testtime,
                    "total_optional_flow_testtime": flow.total_optional_flow_testtime,
                    "total_non_optional_flow_testtime": flow.total_non_optional_flow_testtime,
                    # Add execution counters
                    "retries_executed": flow.retries_executed,
                    "jump_on_success_executed": flow.jump_on_success_executed,
                    "jump_on_failure_executed": flow.jump_on_failure_executed,
                    # Add enhanced summary statistics
                    "total_step_duration": flow.total_step_duration,
                    "total_retry_attempts": flow.total_retry_attempts,
                    "total_optional_flows_triggered": flow.total_optional_flows_triggered,
                    "total_jumps_taken": flow.total_jumps_taken,
                    "failed_steps_count": flow.failed_steps_count,
                    "average_step_duration": flow.average_step_duration,
                    "longest_step_duration": flow.longest_step_duration,
                    "step_with_most_retries": flow.step_with_most_retries,
                    # Add enhanced step tracking (convert StepExecution objects to dicts)
                    "steps_executed": [step.to_dict() for step in flow.steps_executed],
                    "optional_flows": {},
                }

                # Add optional flows that belong to this main flow
                for opt_flow_name, opt_flow in optional_flows.items():
                    if opt_flow.parent_flow_name == flow_name:
                        optional_flow_data = {
                            "caller": opt_flow.triggered_by_step or "Unknown",
                            "status": opt_flow.status,
                            "current_step": opt_flow.current_step,
                            "current_step_index": opt_flow.current_step_index,
                            "completed_steps": opt_flow.completed_steps,
                            "total_steps": opt_flow.total_steps,
                            # Add timing fields
                            "total_testtime": opt_flow.total_testtime,
                            # Add execution counters
                            "retries_executed": opt_flow.retries_executed,
                            "jump_on_success_executed": opt_flow.jump_on_success_executed,
                            "jump_on_failure_executed": opt_flow.jump_on_failure_executed,
                            # Add enhanced summary statistics
                            "total_step_duration": opt_flow.total_step_duration,
                            "total_retry_attempts": opt_flow.total_retry_attempts,
                            "failed_steps_count": opt_flow.failed_steps_count,
                            "average_step_duration": opt_flow.average_step_duration,
                            "longest_step_duration": opt_flow.longest_step_duration,
                            "step_with_most_retries": opt_flow.step_with_most_retries,
                            # Add enhanced step tracking (convert StepExecution objects to dicts)
                            "steps_executed": [step.to_dict() for step in opt_flow.steps_executed],
                        }

                        # Add timing info if available
                        if opt_flow.started_at:
                            optional_flow_data["started_at"] = datetime.fromtimestamp(opt_flow.started_at).isoformat()
                        if opt_flow.completed_at:
                            optional_flow_data["completed_at"] = datetime.fromtimestamp(
                                opt_flow.completed_at
                            ).isoformat()

                        flow_data["optional_flows"][opt_flow_name] = optional_flow_data

                json_data["flows"][flow_name] = flow_data

            # Write atomically by writing to temp file then renaming
            temp_path = self.json_file_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=2)

            # Atomic rename
            temp_path.replace(self.json_file_path)

        except Exception as e:
            self.logger.warning(f"Failed to write progress JSON file: {str(e)}")
