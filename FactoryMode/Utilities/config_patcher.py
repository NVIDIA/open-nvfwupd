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
Configuration File Patcher

A utility script to patch YAML configuration files with the ability to use
a baseline source file when the output doesn't exist. Supports both YAML patch
files and command-line patching.

Note: If --source points to the same file as output_file, the patch is applied in-place and no copy is performed.

Usage:
    # Using YAML patch file
    python config_patcher.py --patch-file <patch_config> <output_file> [--source <baseline_config>]

    # Using command line patches
    python config_patcher.py <output_file> --set <key=value> [--set <key=value>...] [--source <baseline_config>]

Examples:
    # Patch with YAML file
    python config_patcher.py --patch-file patch.yaml output_config.yaml
    python config_patcher.py --patch-file patch.yaml output_config.yaml --source baseline.yaml

    # Patch with command line
    python config_patcher.py output_config.yaml --set "variables.hmc_final_version=GB200Nvl-25.06-1"
    python config_patcher.py output_config.yaml --set "variables.hmc_final_version=GB200Nvl-25.06-1" --set "connection.compute.bmc.ip=10.114.161.158"
    python config_patcher.py output_config.yaml --source baseline.yaml --set "variables.new_feature_enabled=true"
"""

import argparse
import copy
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class ConfigPatcher:
    """Handles patching of YAML configuration files."""

    def __init__(self):
        self.yaml_loader = yaml.SafeLoader
        self.yaml_dumper = yaml.SafeDumper

    def load_yaml(self, file_path: str) -> Dict[str, Any]:
        """
        Load YAML file and return as dictionary.

        Args:
            file_path: Path to the YAML file

        Returns:
            Dictionary representation of the YAML file

        Raises:
            FileNotFoundError: If file doesn't exist
            yaml.YAMLError: If YAML parsing fails
        """
        try:
            with open(file_path, encoding="utf-8") as file:
                return yaml.load(file, Loader=self.yaml_loader)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {file_path}") from None
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML file {file_path}: {e}") from e

    def save_yaml(self, data: Dict[str, Any], file_path: str) -> None:
        """
        Save dictionary to YAML file.

        Args:
            data: Dictionary to save
            file_path: Path to save the YAML file

        Raises:
            IOError: If file cannot be written
        """
        try:
            # Create directory if it doesn't exist
            output_dir = Path(file_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as file:
                yaml.dump(
                    data,
                    file,
                    Dumper=self.yaml_dumper,
                    default_flow_style=False,
                    indent=2,
                    sort_keys=False,
                )
        except OSError as e:
            raise OSError(f"Error writing to file {file_path}: {e}") from e

    def paths_refer_to_same_file(self, path_a: str, path_b: str) -> bool:
        """Return True if the two paths refer to the same file.

        Uses os.path.samefile when possible, with a robust fallback to
        case-normalized absolute path comparison for platforms that do not
        support samefile or when either path may not exist yet.
        """
        try:
            return os.path.samefile(path_a, path_b)
        except Exception:
            return os.path.normcase(os.path.abspath(path_a)) == os.path.normcase(os.path.abspath(path_b))

    def deep_merge(self, base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively merge patch dictionary into base dictionary.

        Args:
            base: Base dictionary to merge into (will not be modified)
            patch: Patch dictionary with updates

        Returns:
            Merged dictionary (new copy)
        """
        # Use deepcopy to ensure we don't modify the original base dictionary
        result = copy.deepcopy(base)

        for key, value in patch.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursively merge nested dictionaries
                result[key] = self.deep_merge(result[key], value)
            else:
                # For non-dict values or new keys, directly assign
                result[key] = value

        return result

    def set_nested_value(self, data: Dict[str, Any], key_path: str, value: Any) -> None:
        """
        Set a nested value in a dictionary using dot notation.

        Args:
            data: Dictionary to modify
            key_path: Dot-separated path to the key (e.g., "variables.hmc_final_version")
            value: Value to set
        """
        keys = key_path.split(".")
        current = data

        # Navigate to the parent of the target key
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        # Set the final value
        final_key = keys[-1]
        current[final_key] = value

    def parse_set_argument(self, set_arg: str) -> tuple:
        """
        Parse a --set argument in the format key=value.

        Args:
            set_arg: String in format "key=value"

        Returns:
            Tuple of (key_path, value)

        Raises:
            ValueError: If format is invalid
        """
        if "=" not in set_arg:
            raise ValueError(f"Invalid --set argument format: {set_arg}. Expected 'key=value'")

        key_path, value_str = set_arg.split("=", 1)

        # Try to convert value to appropriate type
        value = self.convert_value_type(value_str)

        return key_path.strip(), value

    def convert_value_type(self, value_str: str) -> Any:
        """
        Convert string value to appropriate Python type.

        Args:
            value_str: String value to convert

        Returns:
            Converted value with appropriate type
        """
        value_str = value_str.strip()

        # Boolean values
        if value_str.lower() in ("true", "yes", "on", "1"):
            return True
        elif value_str.lower() in ("false", "no", "off", "0"):
            return False

        # Integer values
        try:
            if value_str.startswith("0x"):
                return int(value_str, 16)
            elif value_str.isdigit() or (value_str.startswith("-") and value_str[1:].isdigit()):
                return int(value_str)
        except ValueError:
            pass

        # Float values
        try:
            return float(value_str)
        except ValueError:
            pass

        # String values (remove quotes if present)
        if (value_str.startswith('"') and value_str.endswith('"')) or (
            value_str.startswith("'") and value_str.endswith("'")
        ):
            return value_str[1:-1]

        return value_str

    def create_patch_from_set_args(self, set_args: List[str]) -> Dict[str, Any]:
        """
        Create a patch dictionary from --set arguments.

        Args:
            set_args: List of --set arguments in format "key=value"

        Returns:
            Patch dictionary

        Raises:
            ValueError: If any --set argument has invalid format
        """
        patch = {}

        for set_arg in set_args:
            key_path, value = self.parse_set_argument(set_arg)
            self.set_nested_value(patch, key_path, value)

        return patch

    def patch_config(
        self,
        output_file: str,
        patch_data: Dict[str, Any],
        source_config: Optional[str] = None,
    ) -> None:
        """
        Patch configuration file with updates.

        Args:
            output_file: Path to output configuration file
            patch_data: Dictionary with patch data
            source_config: Optional path to baseline configuration file

        Raises:
            FileNotFoundError: If required files don't exist
            yaml.YAMLError: If YAML parsing fails
            IOError: If file cannot be written
        """
        # Step 1: Copy source file to preserve comments and formatting (always copy when source is provided)
        if source_config and os.path.exists(source_config):
            # If source and output are the same file, perform in-place update (skip copy)
            if self.paths_refer_to_same_file(source_config, output_file):
                print(f"Source and output refer to the same file; performing in-place update: {output_file}")
            else:
                print(f"Copying source file to preserve formatting: {source_config} -> {output_file}")
                # Create output directory if it doesn't exist
                output_dir = Path(output_file).parent
                output_dir.mkdir(parents=True, exist_ok=True)
                # Copy the file to preserve all comments, formatting, and structure (overwrite if exists)
                shutil.copy2(source_config, output_file)

        # Step 2: Load the configuration (either existing output or the copied source)
        if os.path.exists(output_file):
            print(f"Loading configuration from: {output_file}")
            base_data = self.load_yaml(output_file)
        else:
            print("No existing output file or source config, starting with empty base")
            base_data = {}

        # Step 3: Merge configurations
        print("Merging configurations...")
        merged_data = self.deep_merge(base_data, patch_data)

        # Step 4: Save merged configuration back to output file
        print(f"Saving merged configuration to: {output_file}")
        self.save_yaml(merged_data, output_file)

        print("Configuration patching completed successfully!")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Patch YAML configuration files with updates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Output file argument
    parser.add_argument("output_file", help="Path to the output configuration file (YAML)")

    # Patch method group
    patch_group = parser.add_mutually_exclusive_group(required=True)
    patch_group.add_argument("--patch-file", "-f", help="Path to the patch configuration file (YAML)")
    patch_group.add_argument(
        "--set",
        "-s",
        action="append",
        help="Set a configuration value (format: key=value). Can be used multiple times.",
    )

    # Optional source file
    parser.add_argument(
        "--source",
        "-b",
        help="Path to baseline configuration file (optional, used if output file doesn't exist)",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    # Validate input files
    if args.patch_file and not os.path.exists(args.patch_file):
        print(f"Error: Patch configuration file not found: {args.patch_file}")
        sys.exit(1)

    if args.source and not os.path.exists(args.source):
        print(f"Error: Source configuration file not found: {args.source}")
        sys.exit(1)

    # Create patcher and execute
    try:
        patcher = ConfigPatcher()

        if args.patch_file:
            # Load patch from YAML file
            print(f"Loading patch configuration from: {args.patch_file}")
            patch_data = patcher.load_yaml(args.patch_file)
        else:
            # Create patch from --set arguments
            print(f"Creating patch from {len(args.set)} --set arguments")
            patch_data = patcher.create_patch_from_set_args(args.set)

        patcher.patch_config(args.output_file, patch_data, args.source)

    except (OSError, FileNotFoundError, yaml.YAMLError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
