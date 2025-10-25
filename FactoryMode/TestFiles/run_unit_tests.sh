#!/bin/bash

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

#
# NVFWUPD Factory Mode Unit Test Runner (pytest-based)
# 
# This script executes unit tests for the NVFWUPD Factory Mode framework
# using pytest markers defined in pyproject.toml for test discovery and categorization.
#
# Usage:
#   ./run_unit_tests.sh [options]
#   
# Options:
#   --core           Run only core tests
#   --device         Run only device tests
#   --compute        Run only compute device tests
#   --switch         Run only switch device tests  
#   --all            Run all tests (default)
#   --coverage       Run with coverage report using pytest-cov
#   --verbose        Enable verbose output
#   --help           Show help message
#

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find NVFWUPD_DIR by looking for nvfwupd.py
find_nvfwupd_dir() {
    local current_dir="$SCRIPT_DIR"
    while [[ "$current_dir" != "/" ]]; do
        if [[ -f "$current_dir/nvfwupd.py" ]]; then
            echo "$current_dir"
            return 0
        fi
        current_dir="$(dirname "$current_dir")"
    done
    return 1
}

# Try to find nvfwupd.py, if not found, assume we're in the nvfwupd directory structure
NVFWUPD_DIR=$(find_nvfwupd_dir)
if [[ -z "$NVFWUPD_DIR" ]]; then
    # Fallback: assume we're in nvfwupd/FactoryMode/TestFiles and go up 2 levels
    NVFWUPD_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
    if [[ ! -f "$NVFWUPD_DIR/nvfwupd.py" ]]; then
        echo "ERROR: Could not find nvfwupd.py in any parent directory"
        echo "Searched in: $NVFWUPD_DIR"
        echo "Script directory: $SCRIPT_DIR"
        exit 1
    fi
fi

TEST_DIR="${SCRIPT_DIR}"

# Change to nvfwupd directory for all operations
cd "${NVFWUPD_DIR}"

# Default options
RUN_COVERAGE=false
VERBOSE=false
TEST_MARKERS=""  # Will be set based on test suite selection
LOG_FILE=""  # Default to no log file

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Function to print colored output
print_color() {
    local color=$1
    shift
    echo -e "${color}$*${NC}"
}

# Function to print section headers
print_header() {
    print_color "${BLUE}" "================================================================"
    print_color "${BLUE}" "$1"
    print_color "${BLUE}" "================================================================"
}

# Function to show help
show_help() {
    cat << EOF
NVFWUPD Factory Mode Unit Test Runner (pytest-based)

Usage: ./run_unit_tests.sh [options]

Test Suite Options:
  --core           Run only core orchestrator framework tests
  --device         Run only device-specific TrayFlowFunctions tests
  --compute        Run only compute device tests
  --switch         Run only switch device tests
  --all            Run all tests (default)

Other Options:
  --coverage       Run with code coverage report (uses pytest-cov)
  --verbose        Enable verbose output for all tests
  --logfile FILE   Save test output to specified file (default: no log)
  --help           Show this help message

Examples:
  ./run_unit_tests.sh                    # Run all tests
  ./run_unit_tests.sh --core             # Run only core tests
  ./run_unit_tests.sh --device --verbose # Run device tests with verbose output
  ./run_unit_tests.sh --compute          # Run only compute device tests
  ./run_unit_tests.sh --switch           # Run only switch device tests
  ./run_unit_tests.sh --coverage         # Run all tests with coverage
  ./run_unit_tests.sh --logfile test_results.log  # Run all tests and save output to log

Note: Test discovery is handled by pytest using markers defined in pyproject.toml
EOF
}

# Function to parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --core)
                TEST_MARKERS="-m core"
                shift
                ;;
            --device)
                TEST_MARKERS="-m device"
                shift
                ;;
            --compute)
                TEST_MARKERS="-m compute"
                shift
                ;;
            --switch)
                TEST_MARKERS="-m switch"
                shift
                ;;
            --all)
                TEST_MARKERS=""  # No marker = run all tests
                shift
                ;;
            --coverage)
                RUN_COVERAGE=true
                shift
                ;;
            --verbose)
                VERBOSE=true
                shift
                ;;
            --logfile)
                if [[ -z "$2" || "$2" == --* ]]; then
                    print_color "${RED}" "Error: --logfile requires a filename argument"
                    show_help
                    exit 1
                fi
                LOG_FILE="$2"
                shift 2
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                print_color "${RED}" "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Function to check prerequisites
check_prerequisites() {
    print_header "Checking Prerequisites"
    
    # Check if we're in the right directory
    if [[ ! -f "nvfwupd.py" ]]; then
        print_color "${RED}" "ERROR: nvfwupd.py not found - not in correct directory"
        print_color "${RED}" "Script must be run from the nvfwupd directory (same as nvfwupd.py)"
        exit 1
    fi
    
    # Check if Python3 is available
    if ! command -v python3 &> /dev/null; then
        print_color "${RED}" "ERROR: python3 not found in PATH"
        exit 1
    fi
    
    # Check if test directory exists
    if [[ ! -d "$TEST_DIR" ]]; then
        print_color "${RED}" "ERROR: Test directory not found: $TEST_DIR"
        exit 1
    fi
    
    # Check if pytest is available
    if ! python3 -c "import pytest" &> /dev/null; then
        print_color "${YELLOW}" "pytest not found. Installing..."
        pip3 install pytest || {
            print_color "${RED}" "ERROR: Failed to install pytest"
            exit 1
        }
    fi
    
    # Check if coverage is requested and available
    if [[ "$RUN_COVERAGE" == true ]]; then
        if ! python3 -c "import pytest_cov" &> /dev/null; then
            print_color "${YELLOW}" "pytest-cov not found. Installing..."
            pip3 install pytest-cov || {
                print_color "${RED}" "ERROR: Failed to install pytest-cov"
                exit 1
            }
        fi
    fi
    
    print_color "${GREEN}" "All prerequisites satisfied"
}

# Function to run tests using pytest
run_tests() {
    local test_description
    if [[ -n "$TEST_MARKERS" ]]; then
        test_description="Running tests with markers: $TEST_MARKERS"
    else
        test_description="Running all tests"
    fi
    
    print_header "$test_description"
    
    # Build pytest command
    local pytest_cmd="python3 -m pytest"
    # pytest will automatically find configuration in pyproject.toml
    
    # Add test directory
    pytest_cmd="$pytest_cmd FactoryMode/TestFiles/"
    
    # Add markers if specified
    if [[ -n "$TEST_MARKERS" ]]; then
        pytest_cmd="$pytest_cmd $TEST_MARKERS"
    fi
    
    # Add verbosity - always use -v to show test names, but control detail level
    if [[ "$VERBOSE" == true ]]; then
        pytest_cmd="$pytest_cmd -v --tb=short"
    else
        pytest_cmd="$pytest_cmd -v --tb=line --no-header"
    fi
    
    # Add coverage if requested
    if [[ "$RUN_COVERAGE" == true ]]; then
        pytest_cmd="$pytest_cmd --cov=FactoryMode --cov-report=term-missing --cov-config=FactoryMode/pyproject.toml"
    fi
    
    # Set environment
    export PYTHONPATH="$NVFWUPD_DIR"
    
    # Initialize log file if specified
    if [[ -n "$LOG_FILE" ]]; then
        echo "NVFWUPD Factory Mode Unit Test Runner - Test Log" > "$LOG_FILE"
        echo "================================================" >> "$LOG_FILE"
        echo "Test run started at: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
        echo "Test markers: ${TEST_MARKERS:-'(all tests)'}" >> "$LOG_FILE"
        echo "Verbose mode: $VERBOSE" >> "$LOG_FILE"
        echo "Coverage enabled: $RUN_COVERAGE" >> "$LOG_FILE"
        echo "Command: $pytest_cmd" >> "$LOG_FILE"
        echo "================================================" >> "$LOG_FILE"
        echo "" >> "$LOG_FILE"
        
        print_color "${BLUE}" "Logging output to: $LOG_FILE"
    fi
    
    print_color "${BLUE}" "Executing: $pytest_cmd"
    echo ""  # Add some spacing before test output
    
    # Run the command and capture result
    if [[ -n "$LOG_FILE" ]]; then
        # Redirect both stdout and stderr to log file while also showing on terminal
        eval "$pytest_cmd" 2>&1 | tee -a "$LOG_FILE"
        local exit_code=${PIPESTATUS[0]}
    else
        eval "$pytest_cmd"
        local exit_code=$?
    fi
    
    # Log completion
    if [[ -n "$LOG_FILE" ]]; then
        echo "" >> "$LOG_FILE"
        echo "Test run completed at: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
        echo "Exit code: $exit_code" >> "$LOG_FILE"
    fi
    
    return $exit_code
}

# Function to print final summary
print_summary() {
    print_header "Test Execution Summary"
    
    if [[ $? -eq 0 ]]; then
        print_color "${GREEN}" "SUCCESS: All tests passed successfully!"
        return 0
    else
        print_color "${RED}" "FAILURE: Some tests failed. Please review the output above."
        return 1
    fi
}

# Main execution function
main() {
    parse_arguments "$@"
    
    print_header "NVFWUPD Factory Mode Unit Test Runner"
    
    if [[ -n "$TEST_MARKERS" ]]; then
        print_color "${BLUE}" "Test markers: $TEST_MARKERS"
    else
        print_color "${BLUE}" "Running all tests (no markers specified)"
    fi
    
    print_color "${BLUE}" "Starting test execution..."
    
    check_prerequisites
    
    # Clear any existing coverage data if coverage is requested
    if [[ "$RUN_COVERAGE" == true ]]; then
        rm -f .coverage*
        print_color "${BLUE}" "Coverage tracking enabled"
    fi
    
    # Run tests and capture exit code
    run_tests
    local test_exit_code=$?
    
    # Print summary and exit with test result
    if [[ $test_exit_code -eq 0 ]]; then
        print_color "${GREEN}" "SUCCESS: All tests passed successfully!"
        exit 0
    else
        print_color "${RED}" "FAILURE: Some tests failed. Please review the output above."
        exit $test_exit_code
    fi
}

# Execute main function with all arguments
main "$@" 