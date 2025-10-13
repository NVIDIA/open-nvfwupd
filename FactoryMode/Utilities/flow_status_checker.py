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
NVFWUPD Flow Status Checker

A utility script to check the status of NVFWUPD factory mode operations
by parsing the flow_progress.json file for status and all .log files
in the directory for error details from any flow type.

Usage:
    python flow_status_checker.py <folder_path>

Examples:
    python flow_status_checker.py /path/to/nvfwupd_logs
    python flow_status_checker.py ./logs

Exit Codes:
    0: Flow completed successfully
    1: Flow failed, file not found, or unexpected status
"""

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Optional


class FlowStatusChecker:
    """Handles checking NVFWUPD flow status from log files."""

    def __init__(self, verbose: bool = False):
        """
        Initialize the flow status checker.

        Args:
            verbose: Enable verbose output
        """
        self.verbose = verbose
        self.json_file_name = "flow_progress.json"

    def log(self, message: str, level: str = "INFO") -> None:
        """
        Log a message with level prefix.

        Args:
            message: Message to log
            level: Log level (INFO, ERROR, WARNING)
        """
        if self.verbose or level in ["ERROR", "WARNING"]:
            print(f"[{level}] {message}")

    def find_files(self, folder_path: str) -> tuple:
        """
        Find the required files in the specified folder.

        Args:
            folder_path: Path to the folder containing flow files

        Returns:
            Tuple of (json_file_path, list_of_log_file_paths)

        Raises:
            FileNotFoundError: If folder or required files don't exist
        """
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"Path is not a directory: {folder_path}")

        json_file_path = os.path.join(folder_path, self.json_file_name)

        if not os.path.exists(json_file_path):
            raise FileNotFoundError(f"JSON progress file not found: {json_file_path}")

        # Find all .log files in the directory
        log_files = []
        for filename in os.listdir(folder_path):
            if filename.endswith(".log"):
                log_file_path = os.path.join(folder_path, filename)
                if os.path.isfile(log_file_path):
                    log_files.append(log_file_path)

        if not log_files:
            raise FileNotFoundError(f"No log files found in directory: {folder_path}")

        self.log(f"Found JSON file: {json_file_path}")
        self.log(f"Found {len(log_files)} log file(s): {[os.path.basename(f) for f in log_files]}")
        return json_file_path, log_files

    def load_flow_progress(self, json_file_path: str) -> Dict[str, Any]:
        """
        Load and parse the flow progress JSON file.

        Args:
            json_file_path: Path to the flow_progress.json file

        Returns:
            Dictionary representation of the JSON file

        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If JSON parsing fails
        """
        try:
            with open(json_file_path, encoding="utf-8") as file:
                data = json.load(file)
                self.log(f"Successfully loaded flow progress from: {json_file_path}")
                return data
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Error parsing JSON file {json_file_path}: {e}") from e

    def extract_flow_status(self, flow_data: Dict[str, Any]) -> tuple:
        """
        Extract status information from flow progress data.

        Args:
            flow_data: Flow progress data dictionary

        Returns:
            Tuple of (status, flow_name, additional_info)

        Raises:
            ValueError: If flows data structure is invalid
        """
        flows = flow_data.get("flows", {})
        if not flows:
            raise ValueError("No flows found in progress data")

        # Get the first flow (there should typically be only one)
        flow_name = next(iter(flows.keys()))
        flow_info = flows[flow_name]

        status = flow_info.get("status", "Unknown")
        current_step = flow_info.get("current_step", "N/A")
        completed_steps = flow_info.get("completed_steps", 0)
        total_steps = flow_info.get("total_steps", 0)

        additional_info = {
            "current_step": current_step,
            "completed_steps": completed_steps,
            "total_steps": total_steps,
            "progress_percent": (round((completed_steps / total_steps * 100), 1) if total_steps > 0 else 0),
        }

        self.log(f"Flow '{flow_name}' status: {status}")
        self.log(f"Progress: {completed_steps}/{total_steps} steps ({additional_info['progress_percent']}%)")
        if current_step != "N/A":
            self.log(f"Current step: {current_step}")

        return status, flow_name, additional_info

    def parse_log_line(self, line: str, log_file_path: str = None) -> Optional[Dict[str, str]]:
        """
        Parse a single log line to extract timestamp, level, and message.

        Args:
            line: Log line to parse
            log_file_path: Optional path to log file for context

        Returns:
            Dictionary with parsed components or None if parsing fails
        """
        # Pattern: YYYY-MM-DD HH:MM:SS,mmm - MODULE_NAME - LEVEL - MESSAGE
        # Support any module name (compute_factory_flow, switch_factory_flow, etc.)
        pattern = r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - ([^-]+) - (\w+) - (.+)$"
        match = re.match(pattern, line.strip())

        if match:
            return {
                "timestamp": match.group(1),
                "module": match.group(2).strip(),
                "level": match.group(3),
                "message": match.group(4),
                "source_file": os.path.basename(log_file_path) if log_file_path else "unknown",
            }
        return None

    def extract_log_errors(self, log_file_paths: list) -> Dict[str, Any]:
        """
        Extract error messages from all log files.

        Args:
            log_file_paths: List of paths to log files

        Returns:
            Dictionary containing error information from all logs
        """
        all_error_messages = []
        last_error = None
        total_lines = 0
        processed_files = []

        for log_file_path in log_file_paths:
            try:
                with open(log_file_path, encoding="utf-8") as file:
                    lines = file.readlines()
            except Exception as e:
                self.log(f"Warning: Error reading log file {log_file_path}: {e}", "WARNING")
                continue

            if not lines:
                self.log(f"Warning: Log file {log_file_path} is empty", "WARNING")
                continue

            total_lines += len(lines)
            file_error_count = 0

            # Parse all lines and collect error messages
            for line_num, line in enumerate(lines, 1):
                parsed = self.parse_log_line(line, log_file_path)
                if parsed:
                    level = parsed["level"]

                    # Collect error messages
                    if level == "ERROR":
                        error_entry = {
                            "line_num": line_num,
                            "timestamp": parsed["timestamp"],
                            "message": parsed["message"],
                            "module": parsed["module"],
                            "source_file": parsed["source_file"],
                        }
                        all_error_messages.append(error_entry)
                        last_error = parsed["message"]
                        file_error_count += 1
                        self.log(f"Found ERROR in {parsed['source_file']} line {line_num}: {parsed['message']}")

            processed_files.append(
                {
                    "file": os.path.basename(log_file_path),
                    "lines": len(lines),
                    "errors": file_error_count,
                }
            )

        self.log(f"Processed {len(processed_files)} log files with {total_lines} total lines")
        for file_info in processed_files:
            self.log(f"  {file_info['file']}: {file_info['lines']} lines, {file_info['errors']} errors")

        return {
            "total_lines": total_lines,
            "error_count": len(all_error_messages),
            "last_error": last_error,
            "error_messages": all_error_messages,
            "processed_files": processed_files,
        }

    def evaluate_status(
        self,
        status: str,
        flow_name: str,
        additional_info: Dict[str, Any],
        log_errors: Dict[str, Any],
    ) -> int:
        """
        Evaluate the flow status and return appropriate exit code.

        Args:
            status: Flow status from JSON
            flow_name: Name of the flow from JSON
            additional_info: Additional flow information from JSON
            log_errors: Error information extracted from log file

        Returns:
            Exit code (0 for success, 1 for failure)
        """
        print(f"NVFWUPD Flow '{flow_name}' Status: {status}")

        if status == "Completed":
            print("SUCCESS: NVFWUPD flow completed successfully")
            print(f"Completed all {additional_info['total_steps']} steps")
            return 0
        elif status == "Failed":
            print("FAILURE: NVFWUPD flow failed")
            print(f"Failed at step: {additional_info['current_step']}")
            print(f"Progress: {additional_info['completed_steps']}/{additional_info['total_steps']} steps")

            # Output the last error from log file in the specified format
            if log_errors["last_error"]:
                print("{{CORE_ERROR_CODE:001}}")
                print(f"{{{{CORE_ERROR_MSG: {log_errors['last_error']}}}}}")

            return 1
        elif status == "Running":
            print("WARNING: NVFWUPD flow was still running (possibly interrupted)")
            print(f"Last known step: {additional_info['current_step']}")
            print(f"Progress: {additional_info['completed_steps']}/{additional_info['total_steps']} steps")

            # If there are errors in the log while running, show them
            if log_errors["last_error"]:
                print("{{CORE_ERROR_CODE:001}}")
                print(f"{{{{CORE_ERROR_MSG: {log_errors['last_error']}}}}}")

            return 1
        else:
            print(f"UNKNOWN: Unexpected status '{status}'")
            print(f"Current step: {additional_info['current_step']}")

            # If there are errors in the log, show them
            if log_errors["last_error"]:
                print("{{CORE_ERROR_CODE:001}}")
                print(f"{{{{CORE_ERROR_MSG: {log_errors['last_error']}}}}}")

            return 1

    def check_flow_status(self, folder_path: str) -> int:
        """
        Check the flow status from JSON and log files in the specified folder.

        Args:
            folder_path: Path to the folder containing flow files

        Returns:
            Exit code (0 for success, 1 for failure)
        """
        try:
            # Find JSON and all log files
            json_file_path, log_file_paths = self.find_files(folder_path)

            # Load and parse the JSON progress file
            flow_data = self.load_flow_progress(json_file_path)

            # Extract status information from JSON
            status, flow_name, additional_info = self.extract_flow_status(flow_data)

            # Extract error information from all log files
            log_errors = self.extract_log_errors(log_file_paths)

            # Evaluate and return exit code
            return self.evaluate_status(status, flow_name, additional_info, log_errors)

        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            return 1
        except (json.JSONDecodeError, ValueError) as e:
            print(f"ERROR: {e}")
            return 1
        except Exception as e:
            print(f"ERROR: Unexpected error occurred: {e}")
            if self.verbose:
                import traceback

                traceback.print_exc()
            return 1


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Check NVFWUPD factory mode flow status from log files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "folder_path",
        help="Path to the folder containing flow_progress.json and factory flow log files",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    # Create checker and execute
    checker = FlowStatusChecker(verbose=args.verbose)
    exit_code = checker.check_flow_status(args.folder_path)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
