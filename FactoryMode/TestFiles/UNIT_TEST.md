# NVFWUPD Factory Mode Unit Testing Guide

This guide provides comprehensive instructions for running and managing unit tests for the NVFWUPD Factory Mode framework.

## Overview

The NVFWUPD Factory Mode unit tests are built using **pytest** and organized into two main categories:

- **Core Tests**: Framework orchestration, configuration, and utilities
- **Device Tests**: Device-specific TrayFlowFunctions for compute and switch devices

All tests are located in the `FactoryMode/TestFiles/` directory and can be run using the provided `run_unit_tests.sh` script or directly with pytest.

---

## Quick Start

For users who want to get started immediately:

```bash
# 1. Install test dependencies
pip3 install -r FactoryMode/TestFiles/requirements-test.txt

# 2. Navigate to the project root (where nvfwupd.py is located)
cd /path/to/open-nvfwupd

# 3. Run all tests
./FactoryMode/TestFiles/run_unit_tests.sh
```

---

## Installation

### Prerequisites

- Python 3.7 or higher
- pip3 package manager
- Access to the nvfwupd repository

### Install Test Dependencies

Install all required testing packages from the requirements file:

```bash
pip3 install -r FactoryMode/TestFiles/requirements-test.txt
```

This will install:

- **pytest** (≥7.0.0) - Core test framework
- **pytest-cov** (≥4.0.0) - Code coverage reporting
- **pytest-html** (≥3.1.1) - HTML test reports
- **pytest-timeout** (≥2.1.0) - Test timeout management
- **pytest-mock** (≥3.10.0) - Advanced mocking utilities
- **pytest-xdist** (≥3.0.0) - Parallel test execution
- **faker** (≥15.0.0) - Test data generation
- **responses** (≥0.22.0) - HTTP API mocking

### Verify Installation

Check that pytest is correctly installed:

```bash
python3 -m pytest --version
```

---

## Running Tests

### Using the Test Runner Script (Recommended)

The `run_unit_tests.sh` script provides a convenient wrapper around pytest with preset configurations.

#### Basic Usage

```bash
# Run all tests
./FactoryMode/TestFiles/run_unit_tests.sh

# Run with verbose output
./FactoryMode/TestFiles/run_unit_tests.sh --verbose

# Full test suite
./FactoryMode/TestFiles/run_unit_tests.sh --all --coverage
```

### Using Pytest Directly

If you prefer to use pytest directly, ensure you're in the project root directory:

```bash
# Navigate to project root (where nvfwupd.py is located)
cd /path/to/open-nvfwupd

# Set PYTHONPATH
export PYTHONPATH=$(pwd)

# Run all tests
python3 -m pytest FactoryMode/TestFiles/

# Run specific test directory
python3 -m pytest FactoryMode/TestFiles/core/

# Run specific test file
python3 -m pytest FactoryMode/TestFiles/core/test_execution_engine.py

# Run specific test function
python3 -m pytest FactoryMode/TestFiles/core/test_execution_engine.py::test_function_name

# Run tests matching a pattern
python3 -m pytest -k "test_yaml" FactoryMode/TestFiles/
```

---

## Test Organization

The test suite is organized into a clear directory structure:

```
FactoryMode/TestFiles/
├── core/                           # Core framework tests
│   ├── test_base_connection_manager.py
│   ├── test_configuration_management.py
│   ├── test_error_handlers.py
│   ├── test_execution_engine.py
│   ├── test_flow_progress_tracker.py
│   ├── test_implementation_features.py
│   ├── test_jump_configs.py
│   ├── test_logging_utils.py
│   ├── test_utils.py
│   └── test_yaml_processing.py
│
├── device/                         # Device-specific tests
│   ├── test_compute_flow_functions.py
│   ├── test_error_handlers_integration.py
│   ├── test_sol_logging.py
│   └── test_switch_flow_functions.py
│
├── test_error_handlers.py          # Top-level error handler tests
├── test_mocks.py                   # Shared test mocks and fixtures
├── requirements-test.txt           # Test dependencies
└── run_unit_tests.sh               # Test runner script
```

### Test Categories

#### Core Tests (`core/` directory)

Test the fundamental orchestration framework and utilities:

- **Configuration Management**: YAML parsing, validation, and processing
- **Execution Engine**: Flow execution, step handling, and orchestration
- **Connection Management**: SSH/BMC connection handling
- **Progress Tracking**: Flow progress and state management
- **Error Handling**: Error recovery and reporting mechanisms
- **Utilities**: Helper functions and utility modules

#### Device Tests (`device/` directory)

Test device-specific TrayFlowFunctions implementations:

- **Compute Devices**: Flow functions for GPU compute nodes
- **Switch Devices**: Flow functions for network switches
- **SOL Logging**: Serial-over-LAN functionality
- **Integration**: End-to-end device integration tests

---

## Coverage Reports

### Generating Coverage Reports

Using the test runner script:

```bash
./FactoryMode/TestFiles/run_unit_tests.sh --coverage
```

Using pytest directly:

```bash
python3 -m pytest FactoryMode/TestFiles/ \
    --cov=FactoryMode \
    --cov-report=term-missing \
    --cov-config=FactoryMode/pyproject.toml
```

## Troubleshooting

### Common Issues

#### Issue: "ModuleNotFoundError: No module named 'pytest'"

**Solution**: Install test dependencies:

```bash
pip3 install -r FactoryMode/TestFiles/requirements-test.txt
```

#### Issue: "ModuleNotFoundError: No module named 'FactoryMode'"

**Solution**: Ensure you're running tests from the project root and PYTHONPATH is set:

```bash
cd /path/to/open-nvfwupd
export PYTHONPATH=$(pwd)
python3 -m pytest FactoryMode/TestFiles/
```

Or use the test runner script which handles this automatically:

```bash
./FactoryMode/TestFiles/run_unit_tests.sh
```

#### Issue: "ERROR: nvfwupd.py not found"

**Solution**: The test runner script must be executed from or be able to find the project root containing `nvfwupd.py`:

```bash
cd /path/to/open-nvfwupd
./FactoryMode/TestFiles/run_unit_tests.sh
```

#### Issue: Tests fail with import errors

**Solution**: Verify that all required dependencies are installed:

```bash
# Reinstall all dependencies
pip3 install --upgrade -r FactoryMode/TestFiles/requirements-test.txt

# Check installed packages
pip3 list | grep pytest
```

#### Issue: Permission denied when running run_unit_tests.sh

**Solution**: Make the script executable:

```bash
chmod +x FactoryMode/TestFiles/run_unit_tests.sh
```

---

## Best Practices

### Running Tests Before Commits

Always run tests before committing changes:

```bash
# Quick sanity check
./FactoryMode/TestFiles/run_unit_tests.sh --core

# Full test suite
./FactoryMode/TestFiles/run_unit_tests.sh --all --coverage
```

### Test-Driven Development

When adding new features:

1. Write tests first in the appropriate directory (`core/` or `device/`)
2. Run the specific test to confirm it fails
3. Implement the feature
4. Run the test again to confirm it passes
5. Run the full suite to ensure no regressions


## Questions or Issues?

If you encounter any issues not covered in this guide:

1. Check the main Factory Mode README: `FactoryMode/README.md`
2. Review the test files for examples of proper test structure
3. Ensure all prerequisites and dependencies are installed
4. Verify you're running from the correct directory (project root)

---

