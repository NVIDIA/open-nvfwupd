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
HMC Redfish Utils
This module provides redfish utilities for HMC communication via BMC SSH proxy.
The HMC IP is only accessible from the BMC shell, so we proxy all redfish calls through BMC.
"""

import json
import logging
import socket
from typing import Any, Dict, Optional, Tuple

import paramiko

from FactoryMode.output_manager import setup_logging

from .shared_utils import JobMonitorMixin


class HMCRedfishUtils(JobMonitorMixin):
    """Redfish utilities for HMC via BMC SSH proxy - same API as Utils class."""

    def __init__(
        self,
        bmc_connection: Dict[str, str],
        hmc_ip: str = "172.31.13.251",
        logger: logging.Logger = None,
    ):
        """
        Initialize HMC Redfish Utils.

        Args:
            bmc_connection (Dict[str, str]): BMC connection details (ip, username, password)
            hmc_ip (str): HMC IP address (only accessible from BMC)
            logger (logging.Logger): Logger instance
        """
        self.bmc_connection = bmc_connection
        self.hmc_ip = hmc_ip
        self.logger = logger or setup_logging("hmc_redfish_utils")

        self.logger.info(
            f"HMC Redfish Utils initialized for HMC IP: {hmc_ip} via BMC: {bmc_connection.get('ip', 'unknown')}"
        )

    def _execute_bmc_command(self, command: str, timeout: Optional[int] = None) -> Tuple[bool, str]:
        """
        Execute a command on BMC via SSH.

        Args:
            command (str): Command to execute on BMC
            timeout (Optional[int]): SSH command timeout

        Returns:
            Tuple[bool, str]: (success, output/error)
        """
        try:
            # Create SSH client
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                # Connect to BMC with timeouts
                ssh_client.connect(
                    hostname=self.bmc_connection["ip"],
                    port=22,  # BMC SSH port
                    username=self.bmc_connection["username"],
                    password=self.bmc_connection["password"],
                    timeout=timeout if timeout else 30,  # Connection timeout
                    banner_timeout=timeout if timeout else 30,  # Banner timeout
                )

                # Execute command
                _, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)

                # Get output
                stdout_output = stdout.read().decode().strip()
                stderr_output = stderr.read().decode().strip()
                exit_status = stdout.channel.recv_exit_status()

                if exit_status == 0:
                    return True, stdout_output
                error_msg = stderr_output if stderr_output else stdout_output
                # Provide more specific error categorization
                if "connection timed out" in error_msg.lower():
                    return False, f"Connection timeout: {error_msg}"
                if "connection refused" in error_msg.lower():
                    return False, f"Connection refused: {error_msg}"
                if "authentication" in error_msg.lower():
                    return False, f"Authentication error: {error_msg}"
                if "404" in error_msg or "not found" in error_msg.lower():
                    return False, f"Endpoint not found: {error_msg}"
                return (
                    False,
                    f"Command failed (exit {exit_status}): {error_msg}",
                )

            finally:
                ssh_client.close()

        except paramiko.AuthenticationException:
            return False, "Authentication failed - check BMC credentials"
        except paramiko.SSHException as e:
            return False, f"SSH error: {str(e)}"
        except socket.timeout:
            return False, "SSH connection timeout"
        except Exception as e:
            return False, f"SSH connection error: {str(e)}"

    def _parse_curl_response(self, curl_output: str) -> Tuple[bool, Any]:
        """
        Parse curl response to match Utils class return format.

        Args:
            curl_output (str): Raw curl output

        Returns:
            Tuple[bool, Any]: (success, response_data) same as Utils class
        """
        if not curl_output:
            return True, {}

        try:
            # Try to parse as JSON
            response_data = json.loads(curl_output)

            # Check for specific error message pattern indicating unsupported action
            if isinstance(response_data, dict):
                response_str = json.dumps(response_data)
                if "is not supported by the resource" in response_str:
                    self.logger.error("HMC API Error: Action not supported by resource")
                    return False, response_data

            # If no error pattern found, treat as success
            return True, response_data

        except json.JSONDecodeError:
            # If not JSON, return as string (matches Utils behavior for errors)
            return False, curl_output

    def get_request(self, url_path: str, timeout: int = 900) -> Tuple[bool, Any]:
        """
        Send GET request to HMC via BMC SSH - same API as Utils.get_request().

        Args:
            url_path (str): URL path for the request
            timeout (int): Request timeout in seconds

        Returns:
            Tuple[bool, Any]: Success status and response data (same as Utils)
        """
        curl_cmd = f"curl -s -X GET --connect-timeout {timeout} --max-time {timeout} http://{self.hmc_ip}{url_path}"

        self.logger.info(f"HMC Redfish GET Command: {curl_cmd}")
        self.logger.info(f"Target: HMC ({self.hmc_ip}) via BMC SSH Proxy")
        self.logger.info(f"Request timeout: {timeout}s")

        success, output = self._execute_bmc_command(curl_cmd, timeout=timeout)

        if not success:
            self.logger.error(f"Failed to execute curl GET: {output}")
            return False, output

        result = self._parse_curl_response(output)
        self.logger.info(f"HMC Redfish GET Response: {output}")
        return result

    def post_request(self, url_path: str, json_data: Dict[str, Any] = None, timeout: int = 900) -> Tuple[bool, Any]:
        """
        Send POST request to HMC via BMC SSH - same API as Utils.post_request().

        Args:
            url_path (str): URL path for the request
            json_data (Dict[str, Any]): JSON data for the request
            timeout (int): Request timeout in seconds

        Returns:
            Tuple[bool, Any]: Success status and response data (same as Utils)
        """
        curl_cmd = f"curl -s -X POST --connect-timeout {timeout} --max-time {timeout} http://{self.hmc_ip}{url_path}"

        if json_data is not None:
            # Escape quotes in JSON and add to curl command
            json_str = json.dumps(json_data).replace('"', '\\"')
            curl_cmd += f' -H "Content-Type: application/json" -d "{json_str}"'

        self.logger.info(f"HMC Redfish POST Command: {curl_cmd}")
        self.logger.info(f"Target: HMC ({self.hmc_ip}) via BMC SSH Proxy")
        if json_data is not None:
            self.logger.info(f"POST Data: {json.dumps(json_data, indent=2)}")

        success, output = self._execute_bmc_command(curl_cmd, timeout=timeout)

        if not success:
            self.logger.error(f"Failed to execute curl POST: {output}")
            return False, output

        result = self._parse_curl_response(output)
        self.logger.info(f"HMC Redfish POST Response: {output}")
        return result

    def patch_request(self, url_path: str, data: Dict[str, Any], timeout: int = 900) -> Tuple[bool, Any]:
        """
        Send PATCH request to HMC via BMC SSH - same API as Utils.patch_request().

        Args:
            url_path (str): URL path for the request
            data (Dict[str, Any]): Data for the request
            timeout (int): Request timeout in seconds

        Returns:
            Tuple[bool, Any]: Success status and response data (same as Utils)
        """
        # Escape quotes in JSON and add to curl command
        json_str = json.dumps(data).replace('"', '\\"')
        curl_cmd = f'curl -s -X PATCH --connect-timeout {timeout} --max-time {timeout} http://{self.hmc_ip}{url_path} -H "Content-Type: application/json" -d "{json_str}"'

        self.logger.info(f"HMC Redfish PATCH Command: {curl_cmd}")
        self.logger.info(f"Target: HMC ({self.hmc_ip}) via BMC SSH Proxy")
        self.logger.info(f"PATCH Data: {json.dumps(data, indent=2)}")

        success, output = self._execute_bmc_command(curl_cmd, timeout=timeout)

        if not success:
            self.logger.error(f"Failed to execute curl PATCH: {output}")
            return False, output

        result = self._parse_curl_response(output)
        self.logger.info(f"HMC Redfish PATCH Response: {output}")
        return result

    def post_upload_request(
        self,
        *,
        url_path: str,
        file_path: str,
        update_method: str = "MultipartUpdate",
        upd_params: Optional[str] = None,
        timeout: int = 900,
    ) -> Tuple[bool, Any]:
        """
        Send POST upload request to HMC via BMC SSH - same API as Utils.post_upload_request().

        Args:
            url_path (str): URL path for the request
            file_path (str): Path to the file (should be accessible from BMC)
            update_method (str): Update method type
            upd_params (Optional[str]): Update parameters
            timeout (int): Request timeout in seconds

        Returns:
            Tuple[bool, Any]: Success status and response data (same as Utils)
        """
        if update_method == "HttpPushUpdate":
            # Simple binary upload
            curl_cmd = f'curl -s -X POST --connect-timeout {timeout} --max-time {timeout} -H "Content-Type: application/octet-stream" -T {file_path} http://{self.hmc_ip}{url_path}'
        elif update_method == "MultipartUpdate":
            # Multipart upload with parameters
            curl_cmd = (
                f"curl -s -X POST --connect-timeout {timeout} --max-time {timeout} http://{self.hmc_ip}{url_path}"
            )
            curl_cmd += f' -F "UpdateFile=@{file_path};type=application/octet-stream"'
            if upd_params:
                curl_cmd += f' -F "UpdateParameters={upd_params};type=application/json"'
        else:
            return False, f"Unsupported update method: {update_method}"

        self.logger.info(f"HMC Redfish UPLOAD Command: {curl_cmd}")
        self.logger.info(f"Target: HMC ({self.hmc_ip}) via BMC SSH Proxy")
        self.logger.info(f"Upload Method: {update_method}, File: {file_path}")
        if upd_params:
            self.logger.info(f"Upload Parameters: {upd_params}")

        success, output = self._execute_bmc_command(curl_cmd, timeout)

        if not success:
            self.logger.error(f"Failed to execute curl upload: {output}")
            return False, output

        result = self._parse_curl_response(output)
        self.logger.info(f"HMC Redfish UPLOAD Response: {output}")
        return result

    def ping_dut(self) -> int:
        """
        Test HMC connectivity via BMC SSH - same API as Utils.ping_dut().

        Returns:
            int: 0 if successful, 1 if failed (same as Utils)
        """
        try:
            # Test basic HMC redfish connectivity
            status, response = self.get_request("/redfish/v1/", timeout=30)
            if status:
                self.logger.info("HMC redfish connectivity test successful")
                return 0
            self.logger.error(f"HMC redfish connectivity test failed: {response}")
            return 1

        except Exception as e:
            self.logger.error(f"HMC connectivity test error: {str(e)}")
            return 1

    def close(self):
        """Close method for compatibility with Utils API - no-op for HMC proxy."""
