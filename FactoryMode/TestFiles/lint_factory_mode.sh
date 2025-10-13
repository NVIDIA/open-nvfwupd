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


# Factory Mode Linting Script
# This script runs linting tools on the FactoryMode folder using pyproject.toml configuration
# Run this script from the TestFiles directory

# Track results for summary
declare -A TOOL_RESULTS

# Get the script directory and change to FactoryMode root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."  # Go up to FactoryMode directory

echo "Running linting tools on FactoryMode directory..."
echo "Working directory: $(pwd)"
echo "Configuration file: pyproject.toml"
echo

# Check if pyproject.toml exists
if [ ! -f "pyproject.toml" ]; then
    echo "ERROR: pyproject.toml not found in FactoryMode directory"
    exit 1
fi

# Function to run a command with error handling
run_linter() {
    local tool_name="$1"
    local command="$2"
    
    echo "=================== Running $tool_name ==================="
    echo "Command: $command"
    echo
    
    if eval "$command"; then
        echo "✅ $tool_name completed successfully"
        TOOL_RESULTS["$tool_name"]="SUCCESS"
    else
        local exit_code=$?
        echo "❌ $tool_name failed with exit code $exit_code"
        TOOL_RESULTS["$tool_name"]="FAILED (exit code: $exit_code)"
    fi
    echo
}

# 1. Run black (code formatting)
run_linter "black" "python -m black --config=pyproject.toml ."

# 2. Run ruff (fast Python linter with import sorting) - check only
run_linter "ruff" "python -m ruff check --config=pyproject.toml --fix ."

# 3. Run pylint with coverage
run_linter "pylint" "python -m pylint --rcfile=pyproject.toml ."

echo "=================== Linting Summary ==================="
echo
echo "Tool Results:"

# Count successes and failures
success_count=0
failure_count=0

# Display results for each tool
for tool in "black" "ruff" "pylint"; do
    if [[ "${TOOL_RESULTS[$tool]}" == "SUCCESS" ]]; then
        echo "✅ $tool: ${TOOL_RESULTS[$tool]}"
        ((success_count++))
    else
        echo "❌ $tool: ${TOOL_RESULTS[$tool]}"
        ((failure_count++))
    fi
done

echo
echo "=================== Overall Summary ==================="
echo "Total tools run: $((success_count + failure_count))"
echo "Successful: $success_count"
echo "Failed: $failure_count"

if [ $failure_count -eq 0 ]; then
    echo "🎉 All linting tools completed successfully!"
    echo "FactoryMode code is now properly formatted and linted."
    exit 0
else
    echo "⚠️  Some linting tools failed. Please review the output above."
    exit 1
fi
