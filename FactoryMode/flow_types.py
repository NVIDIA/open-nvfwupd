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
Flow type definitions for the factory flow framework.

This module contains the core data structures used to define factory flows,
including device types, flow steps, and output modes.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class DeviceType(Enum):
    """Types of devices supported by the factory flow."""

    COMPUTE = "compute"
    SWITCH = "switch"
    POWER_SHELF = "power_shelf"


class OutputMode(Enum):
    """
    Output mode enumeration for factory flow orchestrator.

    Modes:
        NONE: No console/GUI output, only file logging
        GUI: Rich GUI with progress bars and live updates
        LOG: Stream full log file content to console in real-time
        JSON: Pretty-print flow_summary.json updates as stages complete
    """

    NONE = "none"
    GUI = "gui"
    LOG = "log"
    JSON = "json"


@dataclass
class FlowStep:
    """Represents a single step in the factory flow."""

    device_type: DeviceType
    device_id: str
    operation: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 3
    timeout_seconds: Optional[int] = None
    wait_after_seconds: int = 0
    wait_between_retries_seconds: int = 0
    name: Optional[str] = None
    execute_on_error: Optional[str] = None  # Name of error handler function
    execute_optional_flow: Optional[str] = None  # Name of optional flow to execute after this step if it fails
    jump_on_success: Optional[str] = None  # Tag to jump to on successful execution
    jump_on_failure: Optional[str] = None  # Tag to jump to on failure
    has_jumped_on_failure: bool = False  # Track if this step has already jumped on failure
    tag: Optional[str] = None  # Tag identifier for this step
    # Execution state tracking fields
    last_exception: Optional[Exception] = None  # Last exception raised during execution
    current_execution_id: Optional[str] = None  # Current execution ID for progress tracking
    current_flow_name: Optional[str] = None  # Current flow name for progress tracking


@dataclass
class ParallelFlowStep:
    """Represents a group of steps to be executed in parallel."""

    steps: List[FlowStep]
    name: Optional[str] = None
    max_workers: Optional[int] = None
    wait_after_seconds: int = 0


@dataclass
class IndependentFlow:
    """Represents a self-contained flow that can run independently."""

    steps: List[Union[FlowStep, ParallelFlowStep]]
    name: Optional[str] = None
    max_workers: Optional[int] = None
    wait_after_seconds: int = 0
