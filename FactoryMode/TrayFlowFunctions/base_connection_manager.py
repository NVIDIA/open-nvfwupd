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
Base connection management module for all device types.

This module provides the BaseConnectionManager class which handles
BMC and SSH connections in a consistent way across compute, switch,
and power shelf devices.
"""

import os
from typing import Any, Dict, List, Optional, Union

import paramiko
import requests


class BaseConnectionManager:
    """
    Base class for managing connections to BMC and OS.

    This class provides common connection management functionality
    that is shared across all device types (compute, switch, power_shelf).
    """

    def __init__(self, config: Dict[str, Any], device_type: str):
        """
        Initialize the base connection manager.

        Args:
            config: Full configuration dictionary containing connection details
            device_type: Type of device ('compute', 'switch', or 'power_shelf')
        """
        self.device_type = device_type
        self.bmc_config = config.get("connection", {}).get(device_type, {}).get("bmc", {})
        self.os_config = config.get("connection", {}).get(device_type, {}).get("os", {})
        self.bmc_session: Optional[requests.Session] = None
        self.ssh_client: Optional[paramiko.SSHClient] = None

    def get_bmc_url(self, endpoint: str = "") -> str:
        """
        Get BMC URL for the specified endpoint.

        Args:
            endpoint: API endpoint path (optional)

        Returns:
            Complete URL including protocol, IP, port, and endpoint
        """
        protocol = self.bmc_config.get("protocol", "https")
        ip = self.bmc_config.get("ip", "")
        port = self.bmc_config.get("port", 443)
        return f"{protocol}://{ip}:{port}/{endpoint}"

    def get_bmc_session(self) -> requests.Session:
        """
        Get or create BMC session.

        Returns:
            requests.Session configured for BMC communication
        """
        if self.bmc_session is None:
            self.bmc_session = requests.Session()
            self.bmc_session.verify = False
            self.bmc_session.auth = (
                self.bmc_config.get("username", ""),
                self.bmc_config.get("password", ""),
            )
        return self.bmc_session

    def get_ssh_client(self) -> paramiko.SSHClient:
        """
        Get or create SSH client.

        Returns:
            paramiko.SSHClient configured for OS communication

        Raises:
            paramiko.SSHException: If connection fails
        """
        if self.ssh_client is None:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(
                hostname=self.os_config.get("ip", ""),
                port=self.os_config.get("port", 22),
                username=self.os_config.get("username", ""),
                password=self.os_config.get("password", ""),
            )
            # Set keepalive for switch devices to prevent disconnection during long operations
            if self.device_type == "switch":
                transport = self.ssh_client.get_transport()
                if transport:
                    transport.set_keepalive(15)  # Send keepalive every 15 seconds
        return self.ssh_client

    def scp_files_target(
        self,
        *,
        files: Union[str, List[str]],
        target_config: Dict[str, Any],
        remote_base_path: str = "",
        remote_files: Optional[Union[str, List[str]]] = None,
        set_executable: bool = False,
        logger=None,
    ) -> bool:
        """
        SCP files to a target using SSH/SFTP.

        Args:
            files (Union[str, List[str]]): Single file path or list of file paths to transfer
            target_config (Dict[str, Any]): Target connection config with keys: ip, username, password, port (optional)
            remote_base_path (str): Base path on remote target (default: empty for user home)
            remote_files (Optional[Union[str, List[str]]]): Custom remote file paths. If provided, must match files list length
            set_executable (bool): Whether to set executable permissions on transferred files
            logger: Logger instance for logging (optional)

        Returns:
            bool: True if all transfers were successful, False otherwise
        """

        # Normalize files to list
        file_list = [files] if isinstance(files, str) else files

        # Normalize remote_files to list if provided
        remote_file_list = None
        if remote_files is not None:
            remote_file_list = [remote_files] if isinstance(remote_files, str) else remote_files
            if len(remote_file_list) != len(file_list):
                if logger:
                    logger.error(
                        f"remote_files length ({len(remote_file_list)}) must match files length ({len(file_list)})"
                    )
                return False

        # Validate required config
        required_keys = ["ip", "username", "password"]
        missing_keys = [key for key in required_keys if not target_config.get(key)]
        if missing_keys:
            if logger:
                logger.error(f"Missing required target config keys: {missing_keys}")
            return False

        # Verify all files exist
        for file_path in file_list:
            if not os.path.exists(file_path):
                if logger:
                    logger.error(f"File not found: {file_path}")
                return False

        ssh_client = None
        sftp_client = None

        try:
            # Create SSH client
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect to target
            if logger:
                logger.info(f"Connecting to {target_config['ip']}")
            ssh_client.connect(
                hostname=target_config["ip"],
                port=target_config.get("port", 22),
                username=target_config["username"],
                password=target_config["password"],
            )

            # Create SFTP client
            sftp_client = ssh_client.open_sftp()

            # Transfer each file
            for i, file_path in enumerate(file_list):
                # Determine remote path
                if remote_file_list:
                    # Use custom remote path
                    remote_path = remote_file_list[i]
                else:
                    # Build remote path using base path and filename
                    filename = os.path.basename(file_path)
                    if remote_base_path:
                        remote_path = f"{remote_base_path.rstrip('/')}/{filename}"
                    else:
                        # Default to user home directory
                        remote_path = f"/home/{target_config['username']}/{filename}"

                # Transfer the file
                if logger:
                    logger.info(f"Transferring {file_path} to {remote_path}")
                sftp_client.put(file_path, remote_path)

                # Set executable permissions if requested
                if set_executable:
                    ssh_client.exec_command(f"chmod +x {remote_path}")
                    if logger:
                        logger.debug(f"Set executable permissions on {remote_path}")

            if logger:
                logger.info(f"Successfully transferred {len(file_list)} file(s)")
            return True

        except Exception as e:
            if logger:
                logger.error(f"Failed to transfer files: {str(e)}")
            return False

        finally:
            # Clean up connections
            if sftp_client:
                try:
                    sftp_client.close()
                except Exception as e:
                    if logger:
                        logger.warning(f"Error closing SFTP connection: {str(e)}")
            if ssh_client:
                try:
                    ssh_client.close()
                except Exception as e:
                    if logger:
                        logger.warning(f"Error closing SSH connection: {str(e)}")

    def close(self):
        """
        Close all connections and clean up resources.

        This method gracefully closes both BMC session and SSH client
        connections if they exist.
        """
        if self.bmc_session:
            try:
                self.bmc_session.close()
            except Exception:
                # Ignore errors during close
                pass
            finally:
                self.bmc_session = None

        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                # Ignore errors during close
                pass
            finally:
                self.ssh_client = None

    def scp_tool_to_os(self, tool_file_path: str, os_config: dict, logger=None) -> bool:
        """
        SCP a tool file to the OS home directory using configured credentials.
        Common implementation for both switch and compute factory flows.

        Args:
            tool_file_path (str): Path to the tool file to transfer
            os_config (dict): OS configuration dictionary
            logger: Logger instance for logging messages

        Returns:
            bool: True if successful, False otherwise
        """
        if not os.path.exists(tool_file_path):
            if logger:
                logger.error(f"Tool file not found: {tool_file_path}")
            return False

        if not os_config:
            if logger:
                logger.error("OS configuration not provided or empty")
            return False

        # Get scp_target from config, default to empty string (home directory)
        scp_target = os_config.get("scp_target", "")

        if logger:
            tool_basename = os.path.basename(tool_file_path)
            if scp_target:
                logger.info(f"Transferring {tool_file_path} -> {scp_target}/{tool_basename}")
            else:
                logger.info(f"Transferring {tool_file_path} -> ~/{tool_basename}")

        # Use the shared scp_files_target method from BaseConnectionManager
        return self.scp_files_target(
            files=tool_file_path,
            target_config=os_config,
            remote_base_path=scp_target,  # Use configured scp_target or default to user home
            set_executable=True,  # Set executable permissions for tools
            logger=logger,
        )
