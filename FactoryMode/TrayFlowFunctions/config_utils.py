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
Shared configuration utilities module.

This module provides the ConfigLoader class which handles
YAML configuration loading, validation, and manipulation
in a consistent way across all device types.
"""

import copy
import os
from typing import Any, Dict, List, Optional

import yaml


class ConfigLoader:
    """
    Utility class for loading and managing YAML configurations.

    This class provides static methods for common configuration
    operations like loading, validation, and merging.
    """

    @staticmethod
    def load_config(config_path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to the YAML configuration file

        Returns:
            Dict containing the loaded configuration

        Raises:
            FileNotFoundError: If the configuration file doesn't exist
            yaml.YAMLError: If the YAML file is invalid
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Handle empty files
        if config is None:
            config = {}

        return config

    @staticmethod
    def get_config_section(
        config: Dict[str, Any], section: str, default: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get a configuration section with optional default.

        Args:
            config: The configuration dictionary
            section: The section name to retrieve
            default: Default value if section doesn't exist

        Returns:
            The configuration section or default value
        """
        return config.get(section, default if default is not None else {})

    @staticmethod
    def validate_required_fields(config: Dict[str, Any], required_fields: List[str]) -> None:
        """
        Validate that all required top-level fields are present.

        Args:
            config: The configuration dictionary to validate
            required_fields: List of required field names

        Raises:
            ValueError: If any required field is missing
        """
        missing_fields = [field for field in required_fields if field not in config]

        if missing_fields:
            raise ValueError(f"Missing required configuration field(s): {', '.join(missing_fields)}")

    @staticmethod
    def validate_nested_fields(config: Dict[str, Any], path: str, required_fields: List[str]) -> None:
        """
        Validate that required fields exist in a nested configuration path.

        Args:
            config: The configuration dictionary to validate
            path: Dot-separated path to the nested section (e.g., "connection.compute.bmc")
            required_fields: List of required field names at that path

        Raises:
            ValueError: If the path doesn't exist or required fields are missing
        """
        # Navigate to the nested section
        current = config
        path_parts = path.split(".")

        for i, part in enumerate(path_parts):
            if not isinstance(current, dict) or part not in current:
                raise ValueError(f"Configuration path '{'.'.join(path_parts[:i+1])}' not found")
            current = current[part]

        # Validate required fields at this level
        missing_fields = [field for field in required_fields if field not in current]

        if missing_fields:
            raise ValueError(f"Missing required field(s) at '{path}': {', '.join(missing_fields)}")

    @staticmethod
    def merge_configs(base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two configuration dictionaries.

        The override_config values take precedence over base_config values.
        This performs a deep merge, meaning nested dictionaries are merged
        rather than replaced.

        Args:
            base_config: The base configuration
            override_config: The configuration with override values

        Returns:
            A new dictionary with merged configuration
        """

        def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
            """Recursively merge two dictionaries."""
            result = copy.deepcopy(base)

            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    # Recursively merge nested dictionaries
                    result[key] = deep_merge(result[key], value)
                else:
                    # Override the value
                    result[key] = copy.deepcopy(value)

            return result

        return deep_merge(base_config, override_config)
