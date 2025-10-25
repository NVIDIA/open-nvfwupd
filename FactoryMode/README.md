> SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
>
> SPDX-License-Identifier: Apache-2.0

# NVIDIA Factory Update Flow Framework

A robust, unified framework for managing firmware updates across NVIDIA factory devices, featuring advanced flow control, parallel execution, and comprehensive progress tracking.

## Table of Contents
- [Overview](#overview)
- [Installation](#installation)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Core Components](#core-components)
- [Configuration Files](#configuration-files)
- [Flow Files](#flow-files)
- [Output Modes](#output-modes)
- [Progress Tracking](#progress-tracking)
- [Error Handling](#error-handling)
- [Usage Examples](#usage-examples)
- [Performance](#performance)
- [Contributing](#contributing)

## Overview

The Nvfwupd Flow Framework provides a standardized, scalable way to manage firmware updates and device operations across multiple device types in factory environments. Built on a unified execution engine, it supports complex workflow orchestration with enterprise-grade reliability.

## Installation

1. Clone the repository:
```bash
git clone https://github.com/NVIDIA/open-nvfwupd.git
cd open-nvfwupd
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

Required dependencies:
- Python >= 3.8
- PyYAML >= 5.4.1
- requests >= 2.31.0
- paramiko >= 3.5.1
- urllib3 >= 1.26.15
- rich >= 14.0.0
- ipmitool >= 1.8.12
- scp >= 0.14.5
- tabulate >= 0.9.0

## Factory Mode Usage and setup

It is required to setup some configurations before launching the nvfwupd tool in Factory Update mode. This has been explained step by step in the [Nvfwupd Factory Mode Quick Start Guide](Nvfwupd%20Factory%20Mode%20Quick%20Start%20Guide.md)

## Factory Mode Features

Factory Mode is built on a unified execution engine that processes all device types and operations through a single, consistent workflow framework:

- **Unified Execution Engine**: Single orchestration layer handles compute nodes and network switches through the same core execution path, with automatic step wrapping and routing
- **Declarative YAML Workflows**: Define complex multi-step operations with variable expansion, conditional jumps, and hierarchical flow structures without writing code
- **Advanced Error Recovery**: Multi-level error handling system including step-level retry logic, optional recovery flows, and flow-level error handlers for comprehensive failure management
- **Parallel Execution Support**: Execute multiple operations concurrently with thread-safe progress tracking and automatic batching of consecutive independent flows
- **Real-Time Progress Tracking**: Complete execution monitoring with StepExecution objects capturing timing, retries, jumps, errors, and optional flow triggers, exported to structured JSON
- **Multiple Output Modes**: Choose between GUI (rich progress bars), JSON (step-by-step status), LOG (real-time streaming), or NONE (file logging only) based on operational needs
- **Automatic Debug Collection**: Integrated nvdebug execution on failures captures comprehensive diagnostic information including system state, logs, and hardware status
- **Dynamic Flow Control**: Conditional branching with `jump_on_success` and `jump_on_failure`, loop prevention, and tag-based navigation for complex workflow logic

### Command Line Execution

```bash
# Execute factory flow with specific config and flow files
python nvfwupd.py factory_mode -c GB300_factory_flow_config.yaml -f GB300_compute_flow.yaml

# Execute with custom logging directory
python nvfwupd.py factory_mode -c config.yaml -f flow.yaml -l /custom/log/directory

# Execute with different output mode (overrides config setting)
# Use `none` mode for automation, `gui` for interactive use
python nvfwupd.py factory_mode -c config.yaml -f flow.yaml --output-mode all
```
## Output Modes

The framework supports four output modes that control console output and logging behavior:

| Mode | Description |
|------|-------------|
| `none` | No console output, file logging only |
| `gui` | Rich library GUI with progress bars and live updates |
| `log` | Streams logger output (from all flows) to console in real-time with Rich formatting |
| `json` | Prints each step completion as it happens with success/failure status and duration |

**Important Notes:**
- **File Logging**: All modes write detailed logs to files (e.g., `compute_factory_flow.log`, `switch_factory_flow.log`)
- **LOG Mode**: Uses `RichHandler` to stream `logger.info()`, `logger.error()`, etc. calls to console with colored output, timestamps, and wide formatting (200 chars width)
- **JSON Mode**: Prints step-by-step progress as steps complete, NOT when the entire flow finishes. Each step shows: `[SUCCESS/FAILED] - step_name (duration)`
- **Console Output**: LOG and GUI modes show Rich panels at start/end. JSON and NONE modes suppress panels.

## Progress Tracking

### Real-Time Metrics

The framework automatically tracks:
- **Execution Timing**: Wall clock duration per step and flow
- **Retry Statistics**: Attempt counts and retry durations
- **Jump Operations**: Success/failure jumps with targets
- **Error Collection**: Complete error message history
- **Optional Flow Triggers**: Recovery flow execution and results

### JSON Output Format

Complete execution history is saved to `flow_progress.json` with hierarchical structure:

```json
{
  "timestamp": "2025-01-29T18:45:22.123456",
  "flows": {
    "GB300 Compute Flow": {
      "status": "Completed",
      "current_step": "All Steps Done",
      "completed_steps": 25,
      "total_steps": 25,
      "total_testtime": 1847.5,
      "total_step_duration": 1623.2,
      "total_optional_flow_testtime": 145.8,
      "retries_executed": 7,
      "jump_on_success_executed": 2,
      "jump_on_failure_executed": 1,
      "failed_steps_count": 0,
      "average_step_duration": 64.9,
      "longest_step_duration": 382.1,
      "step_with_most_retries": "check_hmc_ready",
      "steps_executed": [
        {
          "step_name": "check_bmc_version",
          "step_operation": "check_versions",
          "device_type": "compute",
          "device_id": "compute1",
          "duration": 2.333,
          "retry_attempts": 0,
          "final_result": true,
          "status": "completed",
          "execution_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
          "parameters": {
            "expected_versions": {"FW_BMC_0": "1.2.3"},
            "base_uri": "/redfish/v1/UpdateService/FirmwareInventory/"
          },
          "error_messages": [],
          "jump_taken": null,
          "optional_flows_triggered": []
        }
      ],
      "optional_flows": {
        "bmc_recovery_flow": {
          "caller": "check_bmc_version",
          "status": "Completed",
          "total_testtime": 145.8,
          "steps_executed": [
            {
              "step_name": "Reset BMC",
              "step_operation": "reboot_bmc",
              "device_type": "compute",
              "device_id": "compute1",
              "duration": 67.4,
              "final_result": true,
              "status": "completed"
            }
          ]
        }
      }
    }
  }
}
```
## Architecture and Design

Refer to `FactoryMode/ReferenceMaterials/DesignDetails.md` 

## Contributing

### Documentation Standards

1. **Docstrings**: Use Google-style docstrings with comprehensive examples
2. **Type Hints**: Include full type annotations for all public APIs
3. **Testing**: Maintain 100% test coverage for core functionality
4. **Architecture**: Follow unified execution engine patterns

### Development Workflow

1. Fork the repository
2. Create a feature branch
3. Add comprehensive tests (see `TestFiles/UNIT_TEST.md`)
4. Update docstrings and README as needed
5. Submit Pull Request with test coverage report

## Support

For technical support and questions:
- Review the comprehensive docstrings in the source code
- Check the test files for usage examples
- Refer to the TestFiles/UNIT_TEST.md for testing strategies