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
Unit tests for BaseConnectionManager class.
Tests the common connection management functionality that will be shared
across compute, switch, and power shelf device implementations.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from FactoryMode.TrayFlowFunctions.base_connection_manager import BaseConnectionManager

# Mark all tests in this file as core tests
pytestmark = pytest.mark.core


class TestBaseConnectionManager(unittest.TestCase):
    """Test cases for BaseConnectionManager class."""

    def setUp(self):
        """Set up test fixtures."""
        # Sample configuration for different device types
        self.compute_config = {
            "connection": {
                "compute": {
                    "bmc": {
                        "protocol": "https",
                        "ip": "192.168.1.100",
                        "port": 443,
                        "username": "admin",
                        "password": "password",
                    },
                    "os": {
                        "ip": "192.168.1.100",
                        "port": 22,
                        "username": "root",
                        "password": "root_password",
                    },
                }
            }
        }

        self.switch_config = {
            "connection": {
                "switch": {
                    "bmc": {
                        "protocol": "https",
                        "ip": "192.168.1.200",
                        "port": 443,
                        "username": "admin",
                        "password": "switch_password",
                    },
                    "os": {
                        "ip": "192.168.1.200",
                        "port": 22,
                        "username": "cumulus",
                        "password": "cumulus_password",
                    },
                }
            }
        }

        self.power_shelf_config = {
            "connection": {
                "power_shelf": {
                    "bmc": {
                        "protocol": "https",
                        "ip": "192.168.1.300",
                        "port": 443,
                        "username": "admin",
                        "password": "shelf_password",
                    },
                }
            }
        }

    def test_initialization_compute_device(self):
        """Test BaseConnectionManager initialization with compute device config."""
        conn_mgr = BaseConnectionManager(self.compute_config, "compute")

        self.assertEqual(conn_mgr.device_type, "compute")
        self.assertEqual(conn_mgr.bmc_config["ip"], "192.168.1.100")
        self.assertEqual(conn_mgr.os_config["username"], "root")
        self.assertIsNone(conn_mgr.bmc_session)
        self.assertIsNone(conn_mgr.ssh_client)

    def test_initialization_switch_device(self):
        """Test BaseConnectionManager initialization with switch device config."""
        conn_mgr = BaseConnectionManager(self.switch_config, "switch")

        self.assertEqual(conn_mgr.device_type, "switch")
        self.assertEqual(conn_mgr.bmc_config["ip"], "192.168.1.200")
        self.assertEqual(conn_mgr.os_config["username"], "cumulus")

    def test_initialization_power_shelf_device(self):
        """Test BaseConnectionManager initialization with power shelf config."""
        conn_mgr = BaseConnectionManager(self.power_shelf_config, "power_shelf")

        self.assertEqual(conn_mgr.device_type, "power_shelf")
        self.assertEqual(conn_mgr.bmc_config["ip"], "192.168.1.300")
        # Power shelf doesn't have OS config
        self.assertEqual(conn_mgr.os_config, {})

    def test_get_bmc_url_with_endpoint(self):
        """Test get_bmc_url with endpoint specified."""
        conn_mgr = BaseConnectionManager(self.compute_config, "compute")
        url = conn_mgr.get_bmc_url("redfish/v1/Systems")

        self.assertEqual(url, "https://192.168.1.100:443/redfish/v1/Systems")

    def test_get_bmc_url_without_endpoint(self):
        """Test get_bmc_url without endpoint."""
        conn_mgr = BaseConnectionManager(self.compute_config, "compute")
        url = conn_mgr.get_bmc_url()

        self.assertEqual(url, "https://192.168.1.100:443/")

    def test_get_bmc_url_default_values(self):
        """Test get_bmc_url with missing config values uses defaults."""
        minimal_config = {"connection": {"compute": {"bmc": {"ip": "10.0.0.1"}}}}
        conn_mgr = BaseConnectionManager(minimal_config, "compute")
        url = conn_mgr.get_bmc_url("test")

        # Should use default protocol (https) and port (443)
        self.assertEqual(url, "https://10.0.0.1:443/test")

    @patch("requests.Session")
    def test_get_bmc_session_creates_new(self, mock_session_class):
        """Test get_bmc_session creates new session when none exists."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        conn_mgr = BaseConnectionManager(self.compute_config, "compute")
        session = conn_mgr.get_bmc_session()

        # Verify session was created
        mock_session_class.assert_called_once()
        self.assertEqual(session, mock_session)
        self.assertFalse(mock_session.verify)
        self.assertEqual(mock_session.auth, ("admin", "password"))

    @patch("requests.Session")
    def test_get_bmc_session_returns_existing(self, mock_session_class):
        """Test get_bmc_session returns existing session."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        conn_mgr = BaseConnectionManager(self.compute_config, "compute")

        # Get session twice
        session1 = conn_mgr.get_bmc_session()
        session2 = conn_mgr.get_bmc_session()

        # Should only create one session
        mock_session_class.assert_called_once()
        self.assertIs(session1, session2)

    @patch("paramiko.SSHClient")
    def test_get_ssh_client_creates_new(self, mock_ssh_class):
        """Test get_ssh_client creates new SSH client when none exists."""
        mock_ssh = MagicMock()
        mock_ssh_class.return_value = mock_ssh

        conn_mgr = BaseConnectionManager(self.compute_config, "compute")
        client = conn_mgr.get_ssh_client()

        # Verify SSH client was created and configured
        mock_ssh_class.assert_called_once()
        mock_ssh.set_missing_host_key_policy.assert_called_once()
        mock_ssh.connect.assert_called_once_with(
            hostname="192.168.1.100",
            port=22,
            username="root",
            password="root_password",
        )
        self.assertEqual(client, mock_ssh)

    @patch("paramiko.SSHClient")
    def test_get_ssh_client_returns_existing(self, mock_ssh_class):
        """Test get_ssh_client returns existing client."""
        mock_ssh = MagicMock()
        mock_ssh_class.return_value = mock_ssh

        conn_mgr = BaseConnectionManager(self.compute_config, "compute")

        # Get client twice
        client1 = conn_mgr.get_ssh_client()
        client2 = conn_mgr.get_ssh_client()

        # Should only create one client
        mock_ssh_class.assert_called_once()
        self.assertIs(client1, client2)

    @patch("paramiko.SSHClient")
    def test_get_ssh_client_with_default_port(self, mock_ssh_class):
        """Test get_ssh_client uses default port when not specified."""
        mock_ssh = MagicMock()
        mock_ssh_class.return_value = mock_ssh

        # Config without port specified
        config = {
            "connection": {
                "compute": {
                    "os": {
                        "ip": "10.0.0.1",
                        "username": "user",
                        "password": "pass",
                    }
                }
            }
        }

        conn_mgr = BaseConnectionManager(config, "compute")
        conn_mgr.get_ssh_client()

        # Should use default port 22
        mock_ssh.connect.assert_called_once_with(
            hostname="10.0.0.1",
            port=22,
            username="user",
            password="pass",
        )

    def test_close_with_active_connections(self):
        """Test close method closes all active connections."""
        conn_mgr = BaseConnectionManager(self.compute_config, "compute")

        # Mock active connections
        mock_session = MagicMock()
        mock_ssh = MagicMock()
        conn_mgr.bmc_session = mock_session
        conn_mgr.ssh_client = mock_ssh

        conn_mgr.close()

        # Verify connections were closed
        mock_session.close.assert_called_once()
        mock_ssh.close.assert_called_once()
        self.assertIsNone(conn_mgr.bmc_session)
        self.assertIsNone(conn_mgr.ssh_client)

    def test_close_with_no_connections(self):
        """Test close method handles case with no active connections."""
        conn_mgr = BaseConnectionManager(self.compute_config, "compute")

        # No active connections
        self.assertIsNone(conn_mgr.bmc_session)
        self.assertIsNone(conn_mgr.ssh_client)

        # Should not raise any exceptions
        conn_mgr.close()

    def test_close_handles_close_errors(self):
        """Test close method handles errors during connection closing."""
        conn_mgr = BaseConnectionManager(self.compute_config, "compute")

        # Mock connections that raise errors on close
        mock_session = MagicMock()
        mock_session.close.side_effect = Exception("Session close error")
        mock_ssh = MagicMock()
        mock_ssh.close.side_effect = Exception("SSH close error")

        conn_mgr.bmc_session = mock_session
        conn_mgr.ssh_client = mock_ssh

        # Should handle errors gracefully
        conn_mgr.close()

        # Connections should still be set to None
        self.assertIsNone(conn_mgr.bmc_session)
        self.assertIsNone(conn_mgr.ssh_client)

    @patch("paramiko.SSHClient")
    def test_ssh_keepalive_for_switch_device(self, mock_ssh_class):
        """Test SSH keepalive is set for switch devices."""
        mock_ssh = MagicMock()
        mock_transport = MagicMock()
        mock_ssh.get_transport.return_value = mock_transport
        mock_ssh_class.return_value = mock_ssh

        conn_mgr = BaseConnectionManager(self.switch_config, "switch")
        conn_mgr.get_ssh_client()

        # Verify keepalive was set to 15 seconds
        mock_transport.set_keepalive.assert_called_once_with(15)

    @patch("paramiko.SSHClient")
    def test_ssh_no_keepalive_for_compute_device(self, mock_ssh_class):
        """Test SSH keepalive is not set for compute devices."""
        mock_ssh = MagicMock()
        mock_transport = MagicMock()
        mock_ssh.get_transport.return_value = mock_transport
        mock_ssh_class.return_value = mock_ssh

        conn_mgr = BaseConnectionManager(self.compute_config, "compute")
        conn_mgr.get_ssh_client()

        # Verify keepalive was not set for compute devices
        mock_transport.set_keepalive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
