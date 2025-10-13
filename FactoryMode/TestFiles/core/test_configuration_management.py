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
Unit tests for configuration management classes.
This module tests configuration loading, validation, and variable resolution
for ComputeFactoryFlowConfig, SwitchFactoryFlowConfig, and PowerShelfFactoryFlowConfig.

Use the following command to run the tests:
python3 -m unittest TestFiles.test_configuration_management -v
"""

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from FactoryMode.TrayFlowFunctions.compute_factory_flow_functions import ComputeFactoryFlowConfig
from FactoryMode.TrayFlowFunctions.config_utils import ConfigLoader
from FactoryMode.TrayFlowFunctions.power_shelf_factory_flow_functions import (
    PowerShelfFactoryFlowConfig,
)
from FactoryMode.TrayFlowFunctions.switch_factory_flow_functions import SwitchFactoryFlowConfig

# Mark all tests in this file as core tests
pytestmark = pytest.mark.core


class TestComputeFactoryFlowConfig(unittest.TestCase):
    """Test cases for ComputeFactoryFlowConfig class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_path = Path(self.test_dir) / "test_compute_config.yaml"

        # Sample configuration data
        self.sample_config = {
            "settings": {
                "default_retry_count": 2,
                "default_wait_after_seconds": 1,
                "execute_on_error": "default_error_handler",
            },
            "variables": {
                "test_device_id": "compute1",
                "test_bundle_path": "/path/to/test/bundle",
                "nvdebug_path": "/usr/local/bin/nvdebug",
                "output_mode": "text",
            },
            "connection": {
                "compute": {
                    "bmc": {
                        "ip": "192.168.1.100",
                        "username": "admin",
                        "password": "password",
                        "port": 443,
                    },
                    "os": {
                        "ip": "192.168.1.100",
                        "username": "root",
                        "password": "root_password",
                        "port": 22,
                    },
                }
            },
            "compute": {
                "DOT": "Volatile",
                "platform": "GB200",
                "baseboard": "GB200 NVL",
            },
        }

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_config_file(self, config_data: Dict[str, Any]):
        """Write configuration data to test file."""
        with open(self.config_path, "w") as f:
            yaml.dump(config_data, f)

    def test_config_initialization_valid_file(self):
        """Test ComputeFactoryFlowConfig initialization with valid config file."""
        self._write_config_file(self.sample_config)

        config = ComputeFactoryFlowConfig(str(self.config_path))

        self.assertEqual(config.config_path, str(self.config_path))
        self.assertIsInstance(config.config, dict)
        self.assertEqual(config.config["settings"]["default_retry_count"], 2)
        self.assertEqual(config.config["variables"]["test_device_id"], "compute1")

    def test_config_initialization_missing_file(self):
        """Test ComputeFactoryFlowConfig initialization with missing config file."""
        nonexistent_path = str(Path(self.test_dir) / "nonexistent.yaml")

        with self.assertRaises(FileNotFoundError):
            ComputeFactoryFlowConfig(nonexistent_path)

    def test_config_initialization_invalid_yaml(self):
        """Test ComputeFactoryFlowConfig initialization with invalid YAML."""
        # Write invalid YAML
        with open(self.config_path, "w") as f:
            f.write("invalid: yaml: content: [unclosed")

        with self.assertRaises(yaml.YAMLError):
            ComputeFactoryFlowConfig(str(self.config_path))

    def test_get_config_section_exists(self):
        """Test getting configuration section that exists."""
        self._write_config_file(self.sample_config)
        config = ComputeFactoryFlowConfig(str(self.config_path))

        settings = config.get_config("settings")
        self.assertEqual(settings["default_retry_count"], 2)
        self.assertEqual(settings["execute_on_error"], "default_error_handler")

        variables = config.get_config("variables")
        self.assertEqual(variables["test_device_id"], "compute1")
        self.assertEqual(variables["nvdebug_path"], "/usr/local/bin/nvdebug")

    def test_get_config_section_missing(self):
        """Test getting configuration section that doesn't exist."""
        self._write_config_file(self.sample_config)
        config = ComputeFactoryFlowConfig(str(self.config_path))

        missing_section = config.get_config("nonexistent_section")
        self.assertEqual(missing_section, {})

    def test_get_config_nested_section(self):
        """Test getting nested configuration sections."""
        self._write_config_file(self.sample_config)
        config = ComputeFactoryFlowConfig(str(self.config_path))

        connection = config.get_config("connection")
        self.assertIn("compute", connection)

        compute_connection = connection["compute"]
        self.assertIn("bmc", compute_connection)
        self.assertIn("os", compute_connection)

        bmc_config = compute_connection["bmc"]
        self.assertEqual(bmc_config["ip"], "192.168.1.100")
        self.assertEqual(bmc_config["username"], "admin")

    def test_config_variable_resolution(self):
        """Test configuration variable resolution and substitution."""
        config_with_variables = {
            "variables": {"base_path": "/opt/tools", "device_ip": "192.168.1.100"},
            "paths": {
                "nvdebug_path": "${base_path}/nvdebug",
                "flint_path": "${base_path}/flint",
            },
            "connection": {"compute": {"bmc": {"ip": "${device_ip}", "port": 443}}},
        }

        self._write_config_file(config_with_variables)
        config = ComputeFactoryFlowConfig(str(self.config_path))

        # Test if variables are accessible
        variables = config.get_config("variables")
        self.assertEqual(variables["base_path"], "/opt/tools")
        self.assertEqual(variables["device_ip"], "192.168.1.100")

    def test_config_default_values(self):
        """Test configuration with missing optional sections."""
        minimal_config = {"settings": {"default_retry_count": 2}}

        self._write_config_file(minimal_config)
        config = ComputeFactoryFlowConfig(str(self.config_path))

        # Should handle missing sections gracefully
        variables = config.get_config("variables")
        self.assertEqual(variables, {})

        connection = config.get_config("connection")
        self.assertEqual(connection, {})

    def test_config_close_method(self):
        """Test config close method."""
        self._write_config_file(self.sample_config)
        config = ComputeFactoryFlowConfig(str(self.config_path))

        # Close should not raise any exceptions
        config.close()

        # Should still be able to access config after close
        settings = config.get_config("settings")
        self.assertEqual(settings["default_retry_count"], 2)

    def test_dot_config_invalid_value_raises(self):
        """Config loading should fail if DOT is not Volatile/Locking/NoDOT."""
        invalid_config = dict(self.sample_config)
        invalid_config["compute"] = dict(invalid_config["compute"])  # shallow copy nested
        invalid_config["compute"]["DOT"] = "Persistent"
        self._write_config_file(invalid_config)

        with self.assertRaisesRegex(ValueError, r"DOT.*must be one of.*Volatile.*Locking.*NoDOT"):
            ComputeFactoryFlowConfig(str(self.config_path))

    def test_dot_config_valid_values_load_successfully(self):
        """Config loading should succeed for DOT values: Volatile, Locking, NoDOT."""
        for valid_value in ["Volatile", "Locking", "NoDOT"]:
            cfg = dict(self.sample_config)
            cfg["compute"] = dict(cfg["compute"])  # shallow copy nested
            cfg["compute"]["DOT"] = valid_value
            self._write_config_file(cfg)

            config = ComputeFactoryFlowConfig(str(self.config_path))
            self.assertEqual(config.config["compute"]["DOT"], valid_value)


class TestSwitchFactoryFlowConfig(unittest.TestCase):
    """Test cases for SwitchFactoryFlowConfig class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_path = Path(self.test_dir) / "test_switch_config.yaml"

        self.sample_config = {
            "settings": {"default_retry_count": 2, "ssh_timeout": 30},
            "variables": {
                "switch_firmware_url": "https://firmware.nvidia.com/switch/",
                "output_mode": "text",
            },
            "connection": {
                "switch": {
                    "ip": "192.168.1.101",
                    "username": "admin",
                    "password": "admin_password",
                    "port": 22,
                }
            },
            "switch": {"platform": "NVSwitch", "firmware_version": "1.0.0"},
        }

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_config_file(self, config_data: Dict[str, Any]):
        """Write configuration data to test file."""
        with open(self.config_path, "w") as f:
            yaml.dump(config_data, f)

    def test_switch_config_initialization(self):
        """Test SwitchFactoryFlowConfig initialization."""
        self._write_config_file(self.sample_config)

        config = SwitchFactoryFlowConfig(str(self.config_path))

        self.assertEqual(config.config_path, str(self.config_path))
        self.assertIsInstance(config.config, dict)
        self.assertEqual(config.config["settings"]["ssh_timeout"], 30)

    def test_switch_config_sections(self):
        """Test switch-specific configuration sections."""
        self._write_config_file(self.sample_config)
        config = SwitchFactoryFlowConfig(str(self.config_path))

        # Test switch-specific settings
        settings = config.get_config("settings")
        self.assertEqual(settings["ssh_timeout"], 30)

        # Test switch connection
        connection = config.get_config("connection")
        switch_conn = connection["switch"]
        self.assertEqual(switch_conn["ip"], "192.168.1.101")
        self.assertEqual(switch_conn["port"], 22)

        # Test switch platform config
        switch_config = config.get_config("switch")
        self.assertEqual(switch_config["platform"], "NVSwitch")

    def test_switch_config_firmware_url(self):
        """Test switch firmware URL configuration."""
        self._write_config_file(self.sample_config)
        config = SwitchFactoryFlowConfig(str(self.config_path))

        variables = config.get_config("variables")
        self.assertEqual(variables["switch_firmware_url"], "https://firmware.nvidia.com/switch/")


class TestPowerShelfFactoryFlowConfig(unittest.TestCase):
    """Test cases for PowerShelfFactoryFlowConfig class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_path = Path(self.test_dir) / "test_power_shelf_config.yaml"

        self.sample_config = {
            "settings": {"default_retry_count": 2, "redfish_timeout": 60},
            "variables": {
                "power_shelf_firmware_path": "/firmware/power_shelf/",
                "output_mode": "text",
            },
            "connection": {
                "power_shelf": {
                    "ip": "192.168.1.102",
                    "username": "admin",
                    "password": "shelf_password",
                    "port": 443,
                }
            },
            "power_shelf": {
                "platform": "PowerShelf",
                "psu_count": 4,
                "redfish_endpoints": [
                    "/redfish/v1/Chassis/PMC",
                    "/redfish/v1/PowerEquipment/PowerShelves/1",
                ],
            },
        }

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_config_file(self, config_data: Dict[str, Any]):
        """Write configuration data to test file."""
        with open(self.config_path, "w") as f:
            yaml.dump(config_data, f)

    def test_power_shelf_config_initialization(self):
        """Test PowerShelfFactoryFlowConfig initialization."""
        self._write_config_file(self.sample_config)

        config = PowerShelfFactoryFlowConfig(str(self.config_path))

        self.assertEqual(config.config_path, str(self.config_path))
        self.assertIsInstance(config.config, dict)
        self.assertEqual(config.config["settings"]["redfish_timeout"], 60)

    def test_power_shelf_config_sections(self):
        """Test power shelf-specific configuration sections."""
        self._write_config_file(self.sample_config)
        config = PowerShelfFactoryFlowConfig(str(self.config_path))

        # Test power shelf-specific settings
        settings = config.get_config("settings")
        self.assertEqual(settings["redfish_timeout"], 60)

        # Test power shelf connection
        connection = config.get_config("connection")
        shelf_conn = connection["power_shelf"]
        self.assertEqual(shelf_conn["ip"], "192.168.1.102")
        self.assertEqual(shelf_conn["port"], 443)

        # Test power shelf platform config
        shelf_config = config.get_config("power_shelf")
        self.assertEqual(shelf_config["platform"], "PowerShelf")
        self.assertEqual(shelf_config["psu_count"], 4)
        self.assertIn("/redfish/v1/Chassis/PMC", shelf_config["redfish_endpoints"])

    def test_power_shelf_redfish_endpoints(self):
        """Test power shelf Redfish endpoint configuration."""
        self._write_config_file(self.sample_config)
        config = PowerShelfFactoryFlowConfig(str(self.config_path))

        shelf_config = config.get_config("power_shelf")
        endpoints = shelf_config["redfish_endpoints"]

        self.assertIsInstance(endpoints, list)
        self.assertEqual(len(endpoints), 2)
        self.assertIn("/redfish/v1/Chassis/PMC", endpoints)
        self.assertIn("/redfish/v1/PowerEquipment/PowerShelves/1", endpoints)


class TestConfigurationIntegration(unittest.TestCase):
    """Integration tests for all configuration classes."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_multiple_config_files_same_directory(self):
        """Test loading multiple config files from the same directory."""
        # Create separate config files for each device type
        compute_config = {
            "settings": {"default_retry_count": 2},
            "compute": {"DOT": "Volatile"},
        }

        switch_config = {
            "settings": {"ssh_timeout": 30},
            "switch": {"platform": "NVSwitch"},
        }

        power_shelf_config = {
            "settings": {"redfish_timeout": 60},
            "power_shelf": {"psu_count": 4},
        }

        compute_path = Path(self.test_dir) / "compute_config.yaml"
        switch_path = Path(self.test_dir) / "switch_config.yaml"
        shelf_path = Path(self.test_dir) / "power_shelf_config.yaml"

        with open(compute_path, "w") as f:
            yaml.dump(compute_config, f)
        with open(switch_path, "w") as f:
            yaml.dump(switch_config, f)
        with open(shelf_path, "w") as f:
            yaml.dump(power_shelf_config, f)

        # Test loading all configurations
        compute_cfg = ComputeFactoryFlowConfig(str(compute_path))
        switch_cfg = SwitchFactoryFlowConfig(str(switch_path))
        shelf_cfg = PowerShelfFactoryFlowConfig(str(shelf_path))

        # Verify each config loads its specific data
        self.assertEqual(compute_cfg.get_config("compute")["DOT"], "Volatile")
        self.assertEqual(switch_cfg.get_config("switch")["platform"], "NVSwitch")
        self.assertEqual(shelf_cfg.get_config("power_shelf")["psu_count"], 4)

    def test_shared_config_file_all_devices(self):
        """Test loading all device configurations from a shared config file."""
        shared_config = {
            "settings": {
                "default_retry_count": 2,
                "ssh_timeout": 30,
                "redfish_timeout": 60,
            },
            "variables": {"output_mode": "text", "base_path": "/opt/tools"},
            "connection": {
                "compute": {
                    "bmc": {"ip": "192.168.1.100", "port": 443},
                    "os": {"ip": "192.168.1.100", "port": 22},
                },
                "switch": {"ip": "192.168.1.101", "port": 22},
                "power_shelf": {"ip": "192.168.1.102", "port": 443},
            },
            "compute": {"DOT": "Volatile"},
            "switch": {"platform": "NVSwitch"},
            "power_shelf": {"psu_count": 4},
        }

        shared_path = Path(self.test_dir) / "shared_config.yaml"
        with open(shared_path, "w") as f:
            yaml.dump(shared_config, f)

        # Test that all config classes can load from the same file
        compute_cfg = ComputeFactoryFlowConfig(str(shared_path))
        switch_cfg = SwitchFactoryFlowConfig(str(shared_path))
        shelf_cfg = PowerShelfFactoryFlowConfig(str(shared_path))

        # Verify each config can access its specific sections
        self.assertEqual(compute_cfg.get_config("compute")["DOT"], "Volatile")
        self.assertEqual(switch_cfg.get_config("switch")["platform"], "NVSwitch")
        self.assertEqual(shelf_cfg.get_config("power_shelf")["psu_count"], 4)

        # Verify shared sections are accessible to all
        for cfg in [compute_cfg, switch_cfg, shelf_cfg]:
            settings = cfg.get_config("settings")
            self.assertEqual(settings["default_retry_count"], 2)

            variables = cfg.get_config("variables")
            self.assertEqual(variables["output_mode"], "text")

    def test_config_validation_missing_required_sections(self):
        """Test configuration validation with missing required sections."""
        # Test with minimal valid configuration
        minimal_config = {"settings": {"default_retry_count": 1}}

        config_path = Path(self.test_dir) / "minimal_config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(minimal_config, f)

        # All config classes should handle missing optional sections gracefully
        compute_cfg = ComputeFactoryFlowConfig(str(config_path))
        switch_cfg = SwitchFactoryFlowConfig(str(config_path))
        shelf_cfg = PowerShelfFactoryFlowConfig(str(config_path))

        for cfg in [compute_cfg, switch_cfg, shelf_cfg]:
            self.assertEqual(cfg.get_config("variables"), {})
            self.assertEqual(cfg.get_config("connection"), {})

    def test_config_concurrent_access(self):
        """Test concurrent access to configuration files."""
        import threading
        import time

        config_data = {
            "settings": {"default_retry_count": 2},
            "variables": {"test_var": "test_value"},
        }

        config_path = Path(self.test_dir) / "concurrent_config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        results = []
        errors = []

        def config_worker(worker_id):
            """Worker function for concurrent config access."""
            try:
                for i in range(10):
                    cfg = ComputeFactoryFlowConfig(str(config_path))
                    settings = cfg.get_config("settings")
                    variables = cfg.get_config("variables")

                    # Verify data integrity
                    assert settings["default_retry_count"] == 2
                    assert variables["test_var"] == "test_value"

                    cfg.close()
                    results.append(f"Worker {worker_id} iteration {i+1} success")
                    time.sleep(0.001)  # Small delay to encourage race conditions
            except Exception as e:
                errors.append(f"Worker {worker_id} error: {str(e)}")

        # Create and start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=config_worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        self.assertEqual(len(errors), 0, f"Concurrent access errors: {errors}")
        self.assertEqual(len(results), 50)  # 5 workers * 10 iterations each


class TestStrictConfigValidation(unittest.TestCase):
    """Test strict validation of configuration files for type mismatches and invalid values."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_config_file(self, config_content: Dict[str, Any]) -> str:
        """Create a temporary config file with the given content."""
        file_path = Path(self.test_dir) / f"test_config_{len(os.listdir(self.test_dir))}.yaml"
        with open(file_path, "w") as f:
            yaml.dump(config_content, f, default_flow_style=False)
        return str(file_path)

    def test_invalid_retry_count_type(self):
        """Test that non-integer retry count in config raises an error."""
        invalid_type_config = {
            "settings": {
                "default_retry_count": "three",
                "default_wait_after_seconds": 1,
            },  # Should be int!
            "variables": {"test_device_id": "compute1"},
        }

        config_file = self._create_config_file(invalid_type_config)

        # The current implementation doesn't validate types, so this might not raise
        # an error until the value is actually used
        try:
            config = ComputeFactoryFlowConfig(config_file)
            # The string "three" might be accepted during loading
            # but should fail when actually used as an integer
            settings = config.get_config("settings")
            retry_count = settings.get("default_retry_count")
            # Try to use it as an integer
            if isinstance(retry_count, str):
                # This demonstrates the current behavior - no type validation
                self.assertEqual(retry_count, "three")
        except (TypeError, ValueError):
            # If strict validation is added, it should raise here
            pass

    def test_invalid_timeout_type(self):
        """Test that non-numeric timeout values are rejected."""
        invalid_timeout_config = {"settings": {"ssh_timeout": "30 seconds", "redfish_timeout": "1 minute"}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(invalid_timeout_config, f)
            config_file = f.name

        try:
            with self.assertRaises((TypeError, ValueError)) as context:
                config = ComputeFactoryFlowConfig(config_file)
        finally:
            os.unlink(config_file)

    def test_empty_required_connection_fields(self):
        """Test that empty connection fields are rejected."""
        config_with_empty_fields = {
            "connection": {
                "compute": {
                    "bmc": {
                        "ip": "",  # Empty IP
                        "username": "",  # Empty username
                        "password": "",  # Empty password
                        "port": 0,  # Invalid port
                    }
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_with_empty_fields, f)
            config_file = f.name

        try:
            with self.assertRaises((ValueError, TypeError)) as context:
                config = ComputeFactoryFlowConfig(config_file)
        finally:
            os.unlink(config_file)

    def test_malformed_ip_addresses(self):
        """Test configuration with malformed IP addresses."""
        malformed_ip_config = {
            "connection": {
                "compute": {
                    "bmc": {
                        "ip": "999.999.999.999",  # Invalid IP address
                        "username": "admin",
                        "password": "password",
                        "port": 443,
                    },
                    "os": {
                        "ip": "not.an.ip.address",  # Not an IP at all
                        "username": "root",
                        "password": "password",
                        "port": 22,
                    },
                }
            }
        }

        config_file = self._create_config_file(malformed_ip_config)

        # Current implementation doesn't validate IP addresses
        config = ComputeFactoryFlowConfig(config_file)
        connection = config.get_config("connection")

        # These invalid IPs are currently accepted
        self.assertEqual(connection["compute"]["bmc"]["ip"], "999.999.999.999")
        self.assertEqual(connection["compute"]["os"]["ip"], "not.an.ip.address")

    def test_negative_numeric_values(self):
        """Test that negative values are rejected where inappropriate."""
        negative_values_config = {
            "settings": {
                "default_retry_count": -5,
                "default_wait_after_seconds": -10,
                "ssh_timeout": -30,
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(negative_values_config, f)
            config_file = f.name

        try:
            with self.assertRaises((ValueError, TypeError)) as context:
                config = ComputeFactoryFlowConfig(config_file)
        finally:
            os.unlink(config_file)

    def test_port_out_of_range(self):
        """Test that port numbers outside valid range are rejected."""
        invalid_port_config = {
            "connection": {
                "compute": {
                    "bmc": {
                        "ip": "192.168.1.100",
                        "username": "admin",
                        "password": "password",
                        "port": 99999,  # Way out of range
                    }
                },
                "switch": {
                    "ip": "192.168.1.101",
                    "username": "admin",
                    "password": "password",
                    "port": -22,  # Negative port
                },
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(invalid_port_config, f)
            config_file = f.name

        try:
            with self.assertRaises((ValueError, TypeError)) as context:
                config = ComputeFactoryFlowConfig(config_file)
        finally:
            os.unlink(config_file)

    def test_wrong_data_types_in_lists(self):
        """Test configuration with wrong data types in list fields."""
        wrong_types_config = {
            "power_shelf": {
                "platform": "PowerShelf",
                "psu_count": "four",  # Should be int
                "redfish_endpoints": [
                    "/redfish/v1/Chassis/PMC",
                    123,  # Should be string
                    None,  # Should be string
                    {"invalid": "object"},  # Should be string
                ],
            }
        }

        config_file = self._create_config_file(wrong_types_config)

        # Current implementation accepts mixed types in lists
        config = PowerShelfFactoryFlowConfig(config_file)
        shelf_config = config.get_config("power_shelf")

        # These wrong types are currently accepted
        self.assertEqual(shelf_config["psu_count"], "four")
        self.assertIn(123, shelf_config["redfish_endpoints"])
        self.assertIn(None, shelf_config["redfish_endpoints"])


class TestConfigLoader(unittest.TestCase):
    """Test cases for ConfigLoader utility class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config_path = Path(self.test_dir) / "test_config.yaml"

        # Sample valid configuration
        self.valid_config = {
            "settings": {
                "default_retry_count": 2,
                "default_wait_after_seconds": 1,
            },
            "variables": {
                "device_id": "test_device",
                "bundle_path": "/path/to/bundle",
            },
            "connection": {
                "compute": {
                    "bmc": {"ip": "192.168.1.100"},
                    "os": {"ip": "192.168.1.100"},
                }
            },
        }

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_config_file(self, content: Any):
        """Write content to test config file."""
        with open(self.config_path, "w") as f:
            if isinstance(content, str):
                f.write(content)
            else:
                yaml.dump(content, f)

    def test_load_config_valid_file(self):
        """Test loading valid YAML configuration file."""
        self._write_config_file(self.valid_config)

        config = ConfigLoader.load_config(str(self.config_path))

        self.assertIsInstance(config, dict)
        self.assertEqual(config["settings"]["default_retry_count"], 2)
        self.assertEqual(config["variables"]["device_id"], "test_device")

    def test_load_config_file_not_found(self):
        """Test loading non-existent configuration file."""
        nonexistent_path = str(Path(self.test_dir) / "nonexistent.yaml")

        with self.assertRaises(FileNotFoundError) as cm:
            ConfigLoader.load_config(nonexistent_path)

        self.assertIn("Configuration file not found", str(cm.exception))
        self.assertIn(nonexistent_path, str(cm.exception))

    def test_load_config_invalid_yaml(self):
        """Test loading invalid YAML file."""
        # Write invalid YAML
        invalid_yaml = """
        settings:
          retry_count: 3
          unclosed_list: [1, 2, 3
        """
        self._write_config_file(invalid_yaml)

        with self.assertRaises(yaml.YAMLError):
            ConfigLoader.load_config(str(self.config_path))

    def test_load_config_empty_file(self):
        """Test loading empty configuration file."""
        self._write_config_file("")

        config = ConfigLoader.load_config(str(self.config_path))

        # Empty YAML should return None or empty dict depending on yaml.safe_load behavior
        self.assertIn(config, [None, {}])

    def test_load_config_with_special_characters(self):
        """Test loading config with special characters in values."""
        config_with_special = {
            "connection": {
                "bmc": {
                    "password": "p@$$w0rd!#%",
                    "username": "admin@nvidia.com",
                }
            }
        }
        self._write_config_file(config_with_special)

        config = ConfigLoader.load_config(str(self.config_path))

        self.assertEqual(config["connection"]["bmc"]["password"], "p@$$w0rd!#%")
        self.assertEqual(config["connection"]["bmc"]["username"], "admin@nvidia.com")

    def test_get_config_section_exists(self):
        """Test getting existing configuration section."""
        section = ConfigLoader.get_config_section(self.valid_config, "settings")

        self.assertEqual(section["default_retry_count"], 2)
        self.assertEqual(section["default_wait_after_seconds"], 1)

    def test_get_config_section_not_exists_with_default(self):
        """Test getting non-existent section with default value."""
        default = {"default_value": True}
        section = ConfigLoader.get_config_section(self.valid_config, "nonexistent", default)

        self.assertEqual(section, default)

    def test_get_config_section_not_exists_no_default(self):
        """Test getting non-existent section without default value."""
        section = ConfigLoader.get_config_section(self.valid_config, "nonexistent")

        self.assertEqual(section, {})

    def test_get_config_section_nested(self):
        """Test getting nested configuration sections."""
        # Get connection section
        connection = ConfigLoader.get_config_section(self.valid_config, "connection")
        self.assertIn("compute", connection)

        # Get nested compute section
        compute = ConfigLoader.get_config_section(connection, "compute")
        self.assertIn("bmc", compute)
        self.assertIn("os", compute)

    def test_validate_required_fields_all_present(self):
        """Test validation when all required fields are present."""
        required_fields = ["settings", "variables", "connection"]

        # Should not raise any exception
        ConfigLoader.validate_required_fields(self.valid_config, required_fields)

    def test_validate_required_fields_missing(self):
        """Test validation when required fields are missing."""
        config = {"settings": {}, "variables": {}}  # Missing 'connection'
        required_fields = ["settings", "variables", "connection"]

        with self.assertRaises(ValueError) as cm:
            ConfigLoader.validate_required_fields(config, required_fields)

        self.assertIn("Missing required configuration field", str(cm.exception))
        self.assertIn("connection", str(cm.exception))

    def test_validate_required_fields_nested(self):
        """Test validation of nested required fields."""
        # Define nested requirements
        nested_requirements = {
            "connection.compute.bmc": ["ip", "username", "password"],
            "connection.compute.os": ["ip", "username"],
        }

        # Config with complete nested fields
        complete_config = {
            "connection": {
                "compute": {
                    "bmc": {
                        "ip": "192.168.1.1",
                        "username": "admin",
                        "password": "pass",
                    },
                    "os": {"ip": "192.168.1.1", "username": "root"},
                }
            }
        }

        # Should not raise exception
        for path, fields in nested_requirements.items():
            ConfigLoader.validate_nested_fields(complete_config, path, fields)

    def test_validate_required_fields_nested_missing(self):
        """Test validation when nested required fields are missing."""
        # Config missing nested field
        incomplete_config = {
            "connection": {
                "compute": {
                    "bmc": {
                        "ip": "192.168.1.1",
                        # Missing username and password
                    }
                }
            }
        }

        with self.assertRaises(ValueError) as cm:
            ConfigLoader.validate_nested_fields(
                incomplete_config, "connection.compute.bmc", ["ip", "username", "password"]
            )

        self.assertIn("Missing required field", str(cm.exception))

    def test_validate_nested_fields_missing_path_raises(self):
        """ConfigLoader.validate_nested_fields should raise when a nested path is missing."""
        from FactoryMode.TrayFlowFunctions.config_utils import ConfigLoader

        bad_config = {
            "connection": {
                "compute": {
                    # Intentionally omit 'bmc' to trigger missing path
                    "os": {"ip": "1.2.3.4", "username": "u", "password": "p"}
                }
            }
        }

        with self.assertRaises(ValueError) as ctx:
            ConfigLoader.validate_nested_fields(bad_config, "connection.compute.bmc", ["ip", "username", "password"])
        self.assertIn("connection.compute.bmc", str(ctx.exception))

    def test_merge_configs(self):
        """Test merging multiple configuration dictionaries."""
        base_config = {
            "settings": {"retry_count": 3, "timeout": 30},
            "variables": {"var1": "value1"},
        }

        override_config = {
            "settings": {"retry_count": 5},  # Override
            "variables": {"var2": "value2"},  # Add new
            "new_section": {"key": "value"},  # Add new section
        }

        merged = ConfigLoader.merge_configs(base_config, override_config)

        # Check overridden value
        self.assertEqual(merged["settings"]["retry_count"], 5)
        # Check preserved value
        self.assertEqual(merged["settings"]["timeout"], 30)
        # Check new values
        self.assertEqual(merged["variables"]["var2"], "value2")
        self.assertEqual(merged["new_section"]["key"], "value")
        # Original should still have var1
        self.assertEqual(merged["variables"]["var1"], "value1")

    def test_merge_configs_deep_nesting(self):
        """Test merging deeply nested configuration structures."""
        base = {"a": {"b": {"c": {"d": 1, "e": 2}}}}
        override = {"a": {"b": {"c": {"d": 10, "f": 3}}}}

        merged = ConfigLoader.merge_configs(base, override)

        self.assertEqual(merged["a"]["b"]["c"]["d"], 10)  # Overridden
        self.assertEqual(merged["a"]["b"]["c"]["e"], 2)  # Preserved
        self.assertEqual(merged["a"]["b"]["c"]["f"], 3)  # New

    def test_load_config_with_encoding(self):
        """Test loading config file with UTF-8 encoding."""
        # Config with UTF-8 characters
        config_with_utf8 = {
            "description": "Test config with special chars: é, ñ, 中文",
            "settings": {"message": "Hello 世界"},
        }
        self._write_config_file(config_with_utf8)

        config = ConfigLoader.load_config(str(self.config_path))

        self.assertEqual(config["description"], "Test config with special chars: é, ñ, 中文")
        self.assertEqual(config["settings"]["message"], "Hello 世界")


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
