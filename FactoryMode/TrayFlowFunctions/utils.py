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
Utility module for Redfish operations and general helper functions.

This module provides the Utils class which implements methods to send GET, POST, PATCH,
and DELETE requests to Redfish endpoints. These methods handle the success criteria and
return the response data or reason for failure. It is implemented using the requests library.
"""

import json
import logging
import os
import re
import subprocess

import requests

from .shared_utils import JobMonitorMixin

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
# logger = logging.getLogger(__name__)


class Utils(JobMonitorMixin):
    """
    Utility class for interacting with Redfish endpoints.
    """

    def __init__(
        self,
        *,
        dut_ip: str,
        dut_username: str,
        dut_password: str,
        dut_service_port: int = 443,
        dut_service_type: str = "https",
        logger: logging.Logger = None,
    ):
        """
        Initialize RedfishUtils with connection parameters.

        Args:
            dut_ip (str): IP address of the device under test
            dut_username (str): Username for authentication
            dut_password (str): Password for authentication
            dut_service_port (int): Port number for the service (default 443)
            dut_service_type (str): Type of service (default "redfish")
        """
        self.dut_ip = dut_ip
        self.dut_username = dut_username
        self.dut_password = dut_password
        self.dut_service_port = dut_service_port
        self.dut_service_type = dut_service_type
        self.logger = logger or logging.getLogger(__name__)

    def ping_dut(self):
        """
        Ping the DUT to check if it is reachable.
        """
        command = ["ping", "-c", "1", self.dut_ip]
        try:
            subprocess.check_output(command, universal_newlines=True)
            return 0  # check_output only returns on success
        except subprocess.CalledProcessError:
            return 1

    @staticmethod
    def compare_versions(current_version, expected_version, operator="=="):
        """
        Compare two version strings using the given operator.
        """
        # split the version string at anyof . and - and _ and convert to upper case and compare
        # upper case is used to avoid case sensitivity
        # if the version string is a mix of alpha and numeric with hexadecimal, uppercase allows for appropriateascii comparison
        current_version = [x.strip() for x in re.split(r"[.\-_]", current_version.upper())]
        expected_version = [x.strip() for x in re.split(r"[.\-_]", expected_version.upper())]

        if len(current_version) != len(expected_version):
            if operator == "!=":
                return True  # Different lengths means not equal
            return False  # For other operators, can't compare different lengths

        # Pad elements with leading zeros to match lengths
        for i, _ in enumerate(current_version):
            if len(current_version[i]) != len(expected_version[i]):
                # Pad the shorter one with leading zeros
                if len(current_version[i]) < len(expected_version[i]):
                    current_version[i] = current_version[i].zfill(len(expected_version[i]))
                else:
                    expected_version[i] = expected_version[i].zfill(len(current_version[i]))
        result = False
        if "=" in operator:
            result = current_version == expected_version
            if operator == "!=":
                return not result
        if not result and ">" in operator:
            result = current_version > expected_version
        if not result and "<" in operator:
            result = current_version < expected_version
        return result

    def get_request(self, url_path, timeout=900):
        """
        Send GET request to given URL. Return True and response if status code is 200-202.
        Return False and error message if status code is not 200-202.
        """
        try:
            url = f"{self.dut_service_type}://{self.dut_ip}"
            if self.dut_service_port:
                url += f":{self.dut_service_port}"
            url += url_path

            self.logger.info(f"BMC Redfish GET Request: {url}")
            self.logger.info(f"Target: BMC ({self.dut_ip}) Direct Connection")

            response = requests.get(
                url,
                auth=(self.dut_username, self.dut_password),
                verify=False,
                timeout=timeout,
            )

            if response.status_code in range(200, 205):
                ret_data = response.text
                if ret_data != "":
                    ret_data = response.json()
                self.logger.info(f"BMC Redfish GET Response (Status {response.status_code}): {response.text}")
                return True, ret_data
            self.logger.info(f"BMC Redfish GET Response (Status {response.status_code}): {response.text}")
            return False, response.text
        except requests.exceptions.Timeout as e:
            self.logger.error(f"BMC Redfish GET Timeout: {e}")
            return False, f"Timeout Error {e}"
        except Exception as e:
            self.logger.error(f"BMC Redfish GET Exception: {e}")
            return False, str(e)

    def patch_request(self, url_path, data, timeout=900):
        """
        Send PATCH request to given URL. Return True and response if status code is 200-202.
        Return False and error message if status code is not 200-202.
        """
        try:
            url = f"{self.dut_service_type}://{self.dut_ip}"
            if self.dut_service_port:
                url += f":{self.dut_service_port}"
            url += url_path

            self.logger.info(f"BMC Redfish PATCH Request: {url}")
            self.logger.info(f"Target: BMC ({self.dut_ip}) Direct Connection")
            self.logger.info(f"PATCH Data: {json.dumps(data, indent=2)}")

            response = requests.patch(
                url,
                auth=(self.dut_username, self.dut_password),
                verify=False,
                json=data,
                timeout=timeout,
            )

            if response.status_code in (200, 201, 204, 400):
                # 2xx empty response is success even if resp body is empty
                resp_data = {}
                if response.text and response.text.strip() != "":
                    resp_data = json.loads(response.text)
                    if response.status_code == 400:
                        err_code = resp_data["error"]["code"]
                        if "PatchValueAlreadyExists" not in err_code:
                            self.logger.info(
                                f"BMC Redfish PATCH Response (Status {response.status_code}): {response.text}"
                            )
                            return False, resp_data
                self.logger.info(f"BMC Redfish PATCH Response (Status {response.status_code}): {response.text}")
                return True, resp_data
            self.logger.info(f"BMC Redfish PATCH Response (Status {response.status_code}): {response.text}")
            return False, response.text
        except Exception as e:
            self.logger.error(f"BMC Redfish PATCH Exception: {e}")
            return False, str(e)

    def post_request(self, url_path, json_data=None, timeout=900):
        """
        Send POST request to given URL. Return True and response if status code is 200-202.
        Return False and error message if status code is not 200-202.
        """
        try:
            url = f"{self.dut_service_type}://{self.dut_ip}"
            if self.dut_service_port:
                url += f":{self.dut_service_port}"
            url += url_path

            self.logger.info(f"BMC Redfish POST Request: {url}")
            self.logger.info(f"Target: BMC ({self.dut_ip}) Direct Connection")
            if json_data is not None:
                self.logger.info(f"POST Data: {json.dumps(json_data, indent=2)}")

            # If json_data is None, don't include it in the request
            if json_data is not None:
                response = requests.post(
                    url,
                    auth=(self.dut_username, self.dut_password),
                    verify=False,
                    json=json_data,
                    timeout=timeout,
                )
            else:
                response = requests.post(
                    url,
                    auth=(self.dut_username, self.dut_password),
                    verify=False,
                    timeout=timeout,
                )

            if response.status_code in (200, 201, 202):
                # Handle empty response
                if response.text.strip():
                    self.logger.info(f"BMC Redfish POST Response (Status {response.status_code}): {response.text}")
                    return True, response.json()
                self.logger.info(f"BMC Redfish POST Response (Status {response.status_code}): Empty response")
                return True, {}
            self.logger.info(f"BMC Redfish POST Response (Status {response.status_code}): {response.text}")
            return False, response.text
        except Exception as e:
            self.logger.error(f"BMC Redfish POST Exception: {e}")
            return False, str(e)

    def post_upload_request(
        self,
        *,
        url_path,
        file_path,
        update_method="MultipartUpdate",
        upd_params=None,
        timeout=900,
    ):
        """
        Send POST request to given URL.
        """
        try:
            url = f"{self.dut_service_type}://{self.dut_ip}"
            if self.dut_service_port:
                url += f":{self.dut_service_port}"
            url += url_path

            self.logger.info(f"BMC Redfish UPLOAD Request: {url}")
            self.logger.info(f"Target: BMC ({self.dut_ip}) Direct Connection")
            self.logger.info(f"Upload Method: {update_method}, File: {file_path}")
            if upd_params:
                self.logger.info(f"Upload Parameters: {upd_params}")

            response = None
            if update_method == "HttpPushUpdate":
                http_header = {"Content-Type": "application/octet-stream"}
                with open(file_path, "rb") as handle:
                    data = handle.read()
                response = requests.post(url, headers=http_header, data=data, verify=False, timeout=timeout)
            elif update_method == "MultipartUpdate":
                file_list = {}
                with open(file_path, "rb") as pkg_file_fd:
                    file_list["UpdateFile"] = (
                        os.path.basename(file_path),
                        pkg_file_fd,
                        "application/octet-stream",
                    )

                    file_list["UpdateParameters"] = (
                        None,
                        upd_params,
                        "application/json",
                    )
                    response = requests.post(
                        url,
                        auth=(self.dut_username, self.dut_password),
                        files=file_list,
                        verify=False,
                        timeout=timeout,
                    )

            if response.status_code in (200, 201, 202):
                if response.text == "":
                    self.logger.info(f"BMC Redfish UPLOAD Response (Status {response.status_code}): Empty response")
                    return True, response.text
                resp_data = response.json()
                self.logger.info(f"BMC Redfish UPLOAD Response (Status {response.status_code}): {response.text}")
                return True, resp_data
            self.logger.info(f"BMC Redfish UPLOAD Response (Status {response.status_code}): {response.text}")
            return False, response.text
        except Exception as e:
            self.logger.error(f"BMC Redfish UPLOAD Exception: {e}")
            return False, str(e)

