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

# pylint: disable=too-many-lines

"""
Interface to access DUT server
"""
import errno
import ipaddress
import json
import os
import re
import sys
import socket
import time
import requests
import urllib3
from typing import List

from nvfwupd.logger import Logger
from nvfwupd.utils import Util

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class DUTAccess:
    """
    Implements DUT endpoint access interface. End point access
    comprises of DUT IP address, DUT login/password credential
    or TLS certicates. DUT login/password is handled by BMCLoginAccess,
    GB200NVSwitchAccess, BMCPortForwardAccess class;
    ...
    Attributes
    ----------
    m_model : str
        System model
    m_partnumber : str
        System part number
    m_serialnumber : str
        System serial number

    Methods
    -------
    get_dut_access(global_args, logger=Logger("nvfwupd_log.txt"), json_dict=None) :
        Create a target access instance to reach a system based on input details
    def dispatch_request(method="GET",
                         url="",
                         input_data=None,
                         param_data=None,
                         time_out=900,
                         suppress_err=False,
                         json_prints=None) :
        Send a request to a Redfish URI
    """

    # pylint: disable=too-few-public-methods, too-many-branches, too-many-statements
    dut_logger = None

    @staticmethod
    def get_dut_access(global_args, logger=Logger("nvfwupd_log.txt"), json_dict=None):
        """
        Create DUT access instance based on global args input argument.
        Global args contains DUT IP + credentials or configfile embedded
        with DUT access endpoint (DUT IP + credentials).
        Parameters:
            global_args Argument containing IP and credentials or a config
            file containing the IP and credentials
            logger An initialized logger class
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            Connection Status of True or False, initialized DUT Access Class,
            and the passed in servertype if available
            Status of False, and None for access class and servertype if there is an error
        """
        # pylint: disable=too-many-statements, too-many-locals
        target_str = ""
        arg_dict = {}
        DUTAccess.dut_logger = logger
        if Util.is_sanitize:
            log_config = global_args.target
            if global_args.target is None:
                # global_args is none in case of config file
                log_config = Util.default_log_config()

            if json_dict is None:
                Util.sanitize_config = Util.get_log_sanitize_config(log_config, False)
            else:
                Util.sanitize_config = Util.get_log_sanitize_config(log_config, True)

        if not global_args.target is None:
            target_str = " ".join(global_args.target)
            if Util.is_sanitize:
                target_str = Util.sanitize_log(target_str)
            for each in global_args.target:
                tokens = Util.get_tokens(each, "=")
                if len(tokens) < 2:
                    if not json_dict:
                        print(len(tokens))
                    Util.bail_nvfwupd(
                        1,
                        f"Error: invalid target arguments:{target_str},token length: {len(tokens)}",
                        Util.BailAction.DO_NOTHING,
                        print_json=json_dict,
                    )
                    return False, None, None

                arg_dict[tokens[0]] = tokens[1]
        dut_access = None
        server_type = arg_dict.get("servertype")
        if server_type == "gb200switch":
            dut_access = GB200NVSwitchAccess(arg_dict)
            dut_access.is_valid()
            reachable, _ = dut_access.is_reachable(json_dict)
        else:
            access_classes = ["BMCPortForwardAccess", "BMCLoginAccess"]
            for access_name in access_classes:
                if access_name == "BMCPortForwardAccess" and not arg_dict.get("port"):
                    continue
                dut_access = globals()[access_name](arg_dict)
                valid, msg = dut_access.is_valid()

                if not valid:
                    Util.bail_nvfwupd(
                        1,
                        f"Error: {msg}",
                        Util.BailAction.DO_NOTHING,
                        print_json=json_dict,
                    )
                    dut_access = None
                    continue

                reachable, _ = dut_access.is_reachable(json_dict)
                if reachable is False:
                    dut_access = None
                    continue

                if len(arg_dict) < dut_access.get_arg_count():
                    Util.bail_nvfwupd(
                        1,
                        f"Error: invalid target arguments: {target_str}",
                        Util.BailAction.DO_NOTHING,
                        print_json=json_dict,
                    )
                    dut_access = None
                    continue
                break

        if dut_access is None:
            Util.bail_nvfwupd(
                1,
                f"Error: Failed to connect to target: {target_str}",
                Util.BailAction.DO_NOTHING,
                print_json=json_dict,
            )
            return False, None, None

        status = True

        status = dut_access.get_system_info(json_dict)

        if not status:
            Util.bail_nvfwupd(
                1,
                f"Error: Failed to connect to target: {target_str}",
                Util.BailAction.DO_NOTHING,
                print_json=json_dict,
            )
        return status, dut_access, arg_dict.get("servertype")

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def dispatch_request(
        self,
        method="GET",
        url="",
        input_data=None,
        param_data=None,
        time_out=900,
        suppress_err=False,
        json_prints=None,
    ):
        """
        Dispatch request to DUT server
        """

    def __init__(self):
        """
        DUTAccess Parent Class Constructor
        """
        self.m_model = ""
        self.m_partnumber = ""
        self.m_serialnumber = ""


# pylint: disable=too-many-instance-attributes
class GB200NVSwitchAccess(DUTAccess):
    """
    NVUE REST API access class - supports NVUE
    ...
    Attributes
    ----------
    m_model : str
        System model
    m_partnumber : str
        System part number
    m_serialnumber : str
        System serial number
    m_ip : str
        System IP Address
    m_user : str
        System username
    m_password : str
        System password
    m_port : str
        System port number

    Methods
    -------
    is_valid() :
        Checks if an IP address is valid
    is_reachable(json_dict=None) :
        Checks if a system is reachable
    dispatch_rest_request_get(url, time_out=900, print_json=None) :
        Sends a GET request to the NVUE REST server at the provided url
    dispatch_rest_request_post(url, json_data, time_out=900, print_json=None) :
        Sends a POST request to the NVUE REST server at the provided url
    get_job_status(job_id, time_out=900, json_dict=None) :
        Acquires the task status of provided job_id from the NVUE REST server
    get_system_info(json_dict=None) :
        Acquires system details from NVUE REST server
    get_arg_count() :
        Get the number of expected arguments for the target access
    get_firmware_inventory(json_dict=None) :
        Acquire firmware inventory from the NVUE REST server
    get_system_rebooted_status(reboot_eta=4) :
        Check if the NVUE service is up after a reboot

    """

    def __init__(self, access_args_dict):
        """
        NVUE access constructor gh200 nvswitch IP, user and password credential
        Parameter:
            access_args_dict Target access arguments containing system IP,
            username, password and optionally port
        """
        super().__init__()
        self.m_ip = access_args_dict.get("ip", "")
        self.m_user = access_args_dict.get("user", "")
        self.m_password = access_args_dict.get("password", "")
        self.m_port = access_args_dict.get("port", "")
        # ipv6 requires brackets for most operations
        if ":" in self.m_ip:
            self.m_ip = "[" + self.m_ip + "]"

        self.transport_addr = f"https://{self.m_ip}"
        if self.m_port and self.m_port != "":
            self.transport_addr = f"https://{self.m_ip}:{self.m_port}"

    def is_valid(self):
        """
        Checks if IP address is valid
        Returns:
            True and an empty string if the IP address passed is valid or
            False and an empty string if it is not valid
        """
        try:
            test_ip = re.sub(r"\[|\]", "", self.m_ip)
            ipaddress.ip_address(test_ip)
        except ValueError:
            return False, f"invalid IP address: {self.m_ip}"

        return True, ""

    def is_reachable(self, json_dict=None):
        """
        Send rest request to check if system is reachable and REST service is up
        Parameter:
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True and a response dictionary if the system is reachable or
            False and None if the system is not reachable
        """
        platform_url = f"https://{self.m_ip}/nvue_v1/platform"
        status = False
        response = None

        try:
            response = requests.get(
                platform_url,
                auth=(self.m_user, self.m_password),
                verify=False,
                timeout=900,
            )
        except requests.exceptions.ConnectionError:
            if json_dict:
                json_dict["Error"].append(
                    "Connection Error, Failed to connect with the system."
                )
                json_dict["Error Code"] = 1
            else:
                print("Connection Error: Failed to connect with the system.")
            return status, response
        resp_dict = {}
        if response.status_code == 200:
            try:
                resp_dict = json.loads(response.text)
                status = True
            except json.JSONDecodeError as err:
                DUTAccess.dut_logger.verbose_log(f"{response.text}, {err}", True)
        else:
            DUTAccess.dut_logger.verbose_log(
                f"{platform_url}, {response.status_code}, {response.reason}", True
            )

            try:
                resp_dict = json.loads(response.text)
                if not json_dict:
                    print(json.dumps(resp_dict, sort_keys=False, indent=4))
            except json.JSONDecodeError:
                if json_dict:
                    json_dict["Error Code"] = 1
                else:
                    print(response.text)
        return status, resp_dict

    def dispatch_rest_request_get(self, url, time_out=900, print_json=None):
        """
        Send a GET request to the NVUE REST server with given commands
        Parameters:
            url A target REST URL
            time_out The request timeout in seconds
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True and a response dictionary if the system is reachable
            and a response was acquired or
            False and None if the system is not reachable
        """
        transport_url = f"{self.transport_addr}{url}"
        status = False
        response = None
        try:
            response = requests.get(
                transport_url,
                auth=(self.m_user, self.m_password),
                verify=False,
                timeout=time_out,
            )
        except requests.exceptions.ConnectionError:
            if print_json:
                print_json["Error"].append(
                    "Connection Error: Failed to connect with the system."
                )
                print_json["Error Code"] = 1
            else:
                print("Connection Error: Failed to connect with the system.")
            return status, response
        resp_dict = {}
        DUTAccess.dut_logger.verbose_log(f"url = {transport_url}", True)
        DUTAccess.dut_logger.verbose_log(
            f"response.status_code = {response.status_code}", True
        )
        DUTAccess.dut_logger.verbose_log(f"response.text = {response.text}", True)
        if response.status_code == 200:
            try:
                resp_dict = json.loads(response.text)
                status = True
            except json.JSONDecodeError as err:
                DUTAccess.dut_logger.verbose_log(f"{response.text}, {err}", True)
        else:
            DUTAccess.dut_logger.verbose_log(
                f"{transport_url}, {response.status_code}, {response.reason}", True
            )
            try:
                resp_dict = json.loads(response.text)
                # for json mode, append this to the output
                if print_json:
                    # for json mode, the response is appended to the output later
                    pass
                else:
                    print(json.dumps(resp_dict, sort_keys=False, indent=4))
            except json.JSONDecodeError:
                if print_json:
                    print_json["Error Code"] = 1
                else:
                    print(response.text)
        return status, resp_dict

    def dispatch_rest_request_post(self, url, json_data, time_out=900, print_json=None):
        """
        Send a POST request to the NVUE REST server with given commands
        Parameters:
            url The REST URL to post to
            json_data JSON formatted data to post to the URL
            time_out The timeout in seconds for the post request
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True, a response dictionary and response text if the post
            was successful or
            False, an empty dictionary and None if the post fails
        """
        transport_url = f"{self.transport_addr}{url}"
        status = False
        resp_dict = {}
        resp_data = None
        json_header = {"Content-Type": "application/json"}
        response = requests.post(
            transport_url,
            auth=(self.m_user, self.m_password),
            verify=False,
            timeout=900,
        )
        response = requests.post(
            transport_url,
            headers=json_header,
            auth=(self.m_user, self.m_password),
            json=json_data,
            verify=False,
            timeout=time_out,
        )
        DUTAccess.dut_logger.verbose_log(f"POST request: {response.request.headers}")
        DUTAccess.dut_logger.verbose_log(f"POST response: {response.headers}")
        resp_data = response.text
        try:
            resp_dict = json.loads(response.text)
        except json.JSONDecodeError:
            resp_data = response.text
        if response.status_code in range(200, 300):
            status = True
        else:
            DUTAccess.dut_logger.verbose_log(f"resp_dict = {resp_dict}", True)
            DUTAccess.dut_logger.verbose_log(
                "POST: Error sending request: " + f"{response}"
            )
            Util.bail_nvfwupd(
                1,
                f"Error sending POST request: \
                {response.reason, response.status_code}",
                Util.BailAction.DO_NOTHING,
                print_json,
            )
        return status, resp_dict, resp_data

    # pylint: disable=unused-argument
    def get_job_status(self, job_id, time_out=900, json_dict=None):
        """
        Send a request to the NVOS REST server to check status of job_id
        Parameters:
            job_id The job id of an ongoing task
            time_out Unused
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True or False status of the GET rest request and a response dictionary
        """
        task_url = f"/nvue_v1/action/{job_id}"
        status, resp_dict = self.dispatch_rest_request_get(
            task_url, print_json=json_dict
        )
        return status, resp_dict

    def get_system_info(self, json_dict=None):
        """
        Send rest request to get system model name and serial number
        Parameters:
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True if the system is reachable and a valid response is received
            False if the system is not reachable or an invalid response was received
        """
        status, _ = self.is_reachable(json_dict)
        resp_dict = {}
        if status:
            task_url = "/nvue_v1/platform"
            status, resp_dict = self.dispatch_rest_request_get(
                task_url, print_json=json_dict
            )
            self.m_model = resp_dict.get("product-name", "N/A")
            self.m_partnumber = resp_dict.get("part-number", "N/A")
            self.m_serialnumber = resp_dict.get("serial-number", "N/A")
        DUTAccess.dut_logger.verbose_log(
            f"System info /nvue_v1/platform = {resp_dict}", True
        )
        return status

    def get_arg_count(self):
        """
        Return the number of expected arguments for this Target access.
        The number of arguments expected for this instance
        is 3: IP, user and password
        """
        return 3

    def get_firmware_inventory(self, json_dict=None):
        """
        Get firmware inventory from NVOS REST server. Returns inventory list
        as dict of different components and their FW versions
        Parameters:
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True, an error code of 0 (unused) and a dictionary of firmware inventory or
            False, an error code of 0 (unused) and an empty dictionary if there is an error
        """
        # pylint: disable=too-many-locals, too-many-nested-blocks, too-many-branches
        err_code = 0
        inv_dict = {}
        inv_url = "/nvue_v1/platform/firmware"
        status, resp_dict = self.dispatch_rest_request_get(
            inv_url, print_json=json_dict
        )
        DUTAccess.dut_logger.verbose_log(f"inventory resp = {resp_dict}", True)
        if status:
            for ap_name, ap_data in resp_dict.items():
                inv_dict[ap_name] = {"Version": ap_data.get("actual-firmware", "N/A")}
        return status, err_code, inv_dict

    def get_system_rebooted_status(self, reboot_eta=4):
        """
        Query for inventory to check if nvue service is up or not
        Parameters:
            reboot_eta Expected time for system to reboot in minutes
        Returns:
            True if the system is up and NVUE is responsive or
            False if NVUE is unresponsive and the timeout is exceeded
        """
        # pylint: disable=too-many-locals, too-many-nested-blocks, too-many-branches
        system_rebooted = False
        transport_url = f"{self.transport_addr}/nvue_v1/platform/firmware"
        status = False
        # reboot_eta is expected in minutes
        polling_timeout = reboot_eta * 60
        while True:
            try:
                response = requests.get(
                    transport_url,
                    auth=(self.m_user, self.m_password),
                    verify=False,
                    timeout=30,
                )
                DUTAccess.dut_logger.verbose_log(f"url = {transport_url}", True)
                DUTAccess.dut_logger.verbose_log(
                    f"response.status_code = {response.status_code}", True
                )
                DUTAccess.dut_logger.verbose_log(
                    f"response.text = {response.text}", True
                )
                # Need timed re-try even if system has not rebooted yet
                # but break if system does not reboot for 4min
                if not system_rebooted:
                    time.sleep(30)
                    polling_timeout = polling_timeout - 30
                    if polling_timeout <= 0:
                        break
                else:
                    # system rebooted and responded before 4min
                    status = True
                    break
            except requests.exceptions.Timeout:
                system_rebooted = True
                polling_timeout = polling_timeout - 30
                if polling_timeout <= 0:
                    break
        return status


class BMCLoginAccess(DUTAccess):
    """
    BMC access with BMC IP, user and password credential
    ...
    Attributes
    ----------
    m_model : str
        System model
    m_partnumber : str
        System part number
    m_serialnumber : str
        System serial number
    m_ip : str
        System IP Address
    m_user : str
        System username
    m_password : str
        System password
    transport_addr : str
        Transport type combined with system IP for initial URIs
    transport_type : str
        HTTP or HTTPS for communication

    Methods
    -------
    is_valid() :
        Checks if an IP address is valid
    is_reachable(json_dict=None) :
        Checks if a system is reachable
    update_transport_type(transport_type) :
        Updates transport type to either HTTP or HTTPS
    get_arg_count() :
        Acquire expected argument count for the target access instance
    get_resource_members(base_uri, json_dict=None) :
        Acquires Redfish Inventory members from a collection
    get_chassis_members() :
        Acquires a list of Chassis members
    get_firmware_inventory(json_dict=None) :
        Acquires firmware inventory from the Redfish server
    dispatch_file_upload(url, input_data, time_out=900,
                             json_output=None, parallel_update=False) :
        Upload a file for HTTP push update
    dispatch_request(method="GET",
                         url="",
                         input_data=None,
                         param_data=None,
                         time_out=900,
                         suppress_err=False,
                         json_prints=None) :
        Send a request to the Redfish server at the provided URI
    get_system_info(json_dict=None) :
        Acquire system details from Redfish
    multipart_file_upload(url="",
                              pkg_file=None,
                              upd_params_file=None,
                              time_out=900,
                              updparams_json=None,
                              json_prints=None,
                              parallel_update=False) :
        Upload a file for multipart firmware updates
    """

    # pylint: disable=too-many-instance-attributes
    def __init__(self, access_args_dict):
        """
        BMC access constructor with BMC IP, user and passowrd credential
        An exception will be raised if access_args_dict does not contain
        the expected ip, user, and password key
        Parameter:
            access_args_dict Dictionary containing system IP, username and
            password
        """
        super().__init__()
        self.m_ip = access_args_dict.get("ip", "")
        # ipv6 requires brackets for most operations
        if ":" in self.m_ip:
            self.m_ip = "[" + self.m_ip + "]"

        self.m_user = access_args_dict.get("user", "")
        self.m_password = access_args_dict.get("password", "")
        self.transport_addr = ""
        self.transport_type = "https"

    def is_valid(self):
        """
        Checks if IP address is valid
        Returns:
            True and an empty string if the IP address passed is valid or
            False and an empty string if it is not valid
        """
        try:
            test_ip = re.sub(r"\[|\]", "", self.m_ip)
            ipaddress.ip_address(test_ip)
        except ValueError:
            return False, f"invalid IP address: {self.m_ip}"
        self.transport_addr = f"{self.transport_type}://{self.m_ip}"
        return True, ""

    def is_reachable(self, json_dict=None):
        """
        Send redfish GET Chassis URI to ping the bmc ip
        Parameters:
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True and a response dictionary if the system is reachable or
            False and None if the system is not reachable
        """
        status, msg = self.dispatch_request(
            "GET", "/redfish/v1/Chassis", suppress_err=True, json_prints=json_dict
        )
        if status is False:
            self.update_transport_type("http")
            status, msg = self.dispatch_request(
                "GET", "/redfish/v1/Chassis", suppress_err=True, json_prints=json_dict
            )
            if status is False:
                msg = "Failed to connect to the system"
        return status, msg

    def update_transport_type(self, transport_type):
        """
        Initialize http transport type and address
        Parameters:
            transport_type String of either http or https
        """
        self.transport_type = transport_type
        self.transport_addr = f"{self.transport_type}://{self.m_ip}"

    def get_arg_count(self):
        """
        Return the number of expected arguments for this BMC access
        instance. The number of arugments expected for this instance
        is 3: BMC IP, user and password
        """
        return 3

    def get_resource_members(self, base_uri, json_dict=None):
        """
        Acquire Redfish Inventory Members
        Parameters:
            base_uri A base Redfish URI for getting a collection
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            A list of Redfish Inventory Members or
            an empty list if there is an error
        """

        resource_type_members = []
        status, response = self.dispatch_request("GET", base_uri, json_prints=json_dict)

        if status is True:
            try:
                members = response.get("Members", [])
                for member in members:
                    new_member = member.get("@odata.id")
                    resource_type_members.append(new_member)
            except Exception as _:
                resource_type_members = []

        return resource_type_members

    def get_chassis_members(self):
        """
        Get list of Chassis members
        Returns:
            A list of Redfish Inventory Members from the Chassis URI or
            an empty list if there is an error
        """
        chassis_list = self.get_resource_members(base_uri="/redfish/v1/Chassis")

        return chassis_list

    def get_firmware_inventory(self, json_dict=None):
        """
        Get firmware inventory from BMC redfish server. Returns inventory list
        as odata and inventory dictionary key value pairs.
        Parameter:
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True, zero and an inventory list as odata and inventory dictionary key value pairs
            or False, an inventory error of one and an empty dictionary if there is an error
        """
        # pylint: disable=too-many-branches
        inv_dict = {}
        inv_error = 0
        try:
            fw_inv_uri = "/redfish/v1/UpdateService/FirmwareInventory"
            fw_inv_list = self.get_resource_members(fw_inv_uri, json_dict)

            if fw_inv_list is None or len(fw_inv_list) == 0:
                if not json_dict:
                    DUTAccess.dut_logger.debug_print(
                        "Firmware Inventory returned by target is empty"
                    )
                return False, 1, None
            # Get firmware inventory for this firmware device
            for inv_url in fw_inv_list:
                status, fd_dict = self.dispatch_request(
                    "GET", inv_url, suppress_err=True, json_prints=json_dict
                )
                if status:
                    inv_dict[inv_url] = fd_dict
                else:
                    inv_error = 1
                    if not json_dict:
                        DUTAccess.dut_logger.debug_print(f"error fetching {inv_url}")
        except KeyError:
            if not json_dict:
                DUTAccess.dut_logger.debug_print(f"Missing key: {sys.exc_info()[1]}")

        # if some URIs were successfully fetched, then overall status for firmware inventory is True
        if len(inv_dict) != 0:
            status = True

        return status, inv_error, inv_dict

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def dispatch_file_upload(
        self, url, input_data, time_out=900, json_output=None, parallel_update=False
    ):
        """
        Perform file upload for http push update
        Parameters:
            url A Redfish URL to upload to
            input_data The file used for the firmware update
            time_out Timeout of the request in seconds
            json_output Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        Returns:
            True and a dictionary containing the upload response or
            False and a dictionary containing an error message if the upload fails
        """
        status = False
        file_data = ""
        try:
            with open(input_data, "rb") as upload_file:
                file_data = upload_file.read()
        except IOError as e_io_error:
            Util.bail_nvfwupd_threadsafe(
                1,
                f"Failed to open or read given file {input_data} error: ({e_io_error})",
                print_json=json_output,
                parallel_update=parallel_update,
            )
            return status, {"error": "Failed to read given file"}
        headers = {"Content-Type": "application/octet-stream"}
        headers["Expect"] = "100-continue"
        try:
            response = requests.post(
                self.transport_addr + url,
                auth=(self.m_user, self.m_password),
                headers=headers,
                data=file_data,
                verify=False,
                timeout=time_out,
            )
        except requests.exceptions.ConnectionError as err:
            DUTAccess.dut_logger.verbose_log(f"Request failed, response: {str(err)}")
            return status, {"error": "Request failed", "details": str(err)}
        if response.status_code == 405:
            Util.bail_nvfwupd_threadsafe(
                1,
                "Platform not supported.",
                print_json=json_output,
                parallel_update=parallel_update,
            )
            return status, {"error": "Platform not supported"}
        response_dict = json.loads(response.text)
        if response.status_code in (200, 202):
            status = True
        else:
            DUTAccess.dut_logger.verbose_log(
                f"POST: Error in dispatch file upload, response: {response}"
            )
        return status, response_dict

    # pylint: disable=too-many-arguments, too-many-return-statements
    # pylint: disable=too-many-positional-arguments
    def dispatch_request(
        self,
        method="GET",
        url="",
        input_data=None,
        param_data=None,
        time_out=900,
        suppress_err=False,
        json_prints=None,
    ):
        """
        Dispatch redfish api to BMC server at given url
        Parameters:
            method GET, PATCH, or POST
            url The Redfish URL to apply the method to
            input_data An update file used for POST requests
            param_data Update or patch parameters
            time_out Timeout in seconds for the request
            suppress_err Boolean value to suppress certain errors
            json_prints Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True and a JSON dictionary of the response or
            False and an empty dictionary if there is an error
        """
        # pylint: disable=too-many-locals, too-many-branches, too-many-statements, too-many-nested-blocks
        status = False
        my_dict = {}
        json_header = {
            "Content-Type": "application/json",
        }

        http_header = {"Content-Type": "application/octet-stream"}

        try:
            # pylint: disable=too-many-nested-blocks
            if method == "GET":
                response = requests.get(
                    self.transport_addr + url,
                    auth=(self.m_user, self.m_password),
                    headers=json_header,
                    verify=False,
                    timeout=120,
                )
                if response.status_code == 200:
                    try:
                        my_dict = json.loads(response.text)
                    except json.JSONDecodeError as err:
                        DUTAccess.dut_logger.verbose_log(
                            f"{response.text}, {err}", True
                        )
                        return False, my_dict
                    status = True
                else:
                    DUTAccess.dut_logger.verbose_log(
                        f"{url}, {response.status_code}, {response.reason}", True
                    )
                    if not suppress_err:
                        try:
                            my_dict = json.loads(response.text)
                            if not json_prints:
                                print(json.dumps(my_dict, sort_keys=False, indent=4))
                        except json.JSONDecodeError:
                            if json_prints:
                                json_prints["Error Code"] = 1
                            else:
                                print(response.text)
                            return False, my_dict
            elif method == "PATCH":
                # input data for patch is a dictionary
                json_header["If-Match"] = "*"
                while True:
                    try:
                        response = requests.patch(
                            self.transport_addr + url,
                            headers=json_header,
                            auth=(self.m_user, self.m_password),
                            data=param_data,
                            verify=False,
                            timeout=time_out,
                        )
                        if (400 <= response.status_code <= 499) or (
                            500 <= response.status_code <= 599
                        ):
                            DUTAccess.dut_logger.verbose_log(
                                f"PATCH request: {response.request.headers}"
                            )
                            DUTAccess.dut_logger.verbose_log(
                                f"PATCH response: {response.headers}"
                            )
                        if response.status_code in (200, 201, 204, 400):
                            # 2xx empty response is success even if resp body is empty
                            my_dict = {}
                            status = True
                            if response.text and response.text.strip() != "":
                                my_dict = json.loads(response.text)
                                if response.status_code == 400:
                                    err_code = my_dict["error"]["code"]
                                    if "PatchValueAlreadyExists" not in err_code:
                                        status = False
                            break
                        elif response.status_code == 412:
                            json_header = {"Content-Type": "application/json"}
                        else:
                            break
                    except requests.exceptions.RequestException as excpt:
                        DUTAccess.dut_logger.verbose_log(
                            f"PATCH: Error sending HTTPs request: {excpt}"
                        )
                        Util.bail_nvfwupd(
                            1,
                            f"PATCH: Error sending HTTPs request: {excpt.response}",
                            Util.BailAction.DO_NOTHING,
                            print_json=json_prints,
                        )
                        return False, my_dict
            elif method == "POST":
                # If param_data is specified then no need of auth
                if not param_data:
                    auth_header = {}
                    resp = requests.post(
                        self.transport_addr + "/login",
                        headers=json_header,
                        json={"data": [self.m_user, self.m_password]},
                        verify=False,
                        timeout=30,
                    )
                    DUTAccess.dut_logger.verbose_log(
                        f"POST request: {resp.request.headers}"
                    )
                    DUTAccess.dut_logger.verbose_log(f"POST response: {resp.headers}")
                    if resp.status_code == 200:
                        cookie = resp.headers["Set-Cookie"]
                        match = re.search(r"SESSION=(\w+);", cookie)
                        if match:
                            auth_header["X-Auth-Token"] = match.group(1)
                            http_header.update(auth_header)
                            if not json_prints:
                                print(http_header)
                    else:
                        DUTAccess.dut_logger.verbose_log(
                            f"POST: Error Unable to get valid token: {resp}"
                        )
                        Util.bail_nvfwupd(
                            1,
                            "Unable to get valid token for POST message",
                            Util.BailAction.DO_NOTHING,
                            print_json=json_prints,
                        )
                        return False, my_dict
                    # Read pldm inputfile
                    with open(input_data, "rb") as handle:
                        data = handle.read()
                    response = requests.post(
                        self.transport_addr + url,
                        headers=http_header,
                        data=data,
                        verify=False,
                        timeout=time_out,
                    )
                    data.close()
                else:
                    # check if param data is a dict or a file
                    if isinstance(param_data, dict):
                        response = requests.post(
                            self.transport_addr + url,
                            headers=json_header,
                            auth=(self.m_user, self.m_password),
                            json=param_data,
                            verify=False,
                            timeout=time_out,
                        )
                        DUTAccess.dut_logger.verbose_log(
                            f"POST request: {response.request.headers}"
                        )
                        DUTAccess.dut_logger.verbose_log(
                            f"POST response: {response.headers}"
                        )
                        try:
                            my_dict = json.loads(response.text)
                        except json.JSONDecodeError:
                            my_dict = response.text
                    else:
                        file_list = {}
                        # pylint: disable=consider-using-with
                        file_list["UpdateFile"] = (
                            os.path.basename(input_data),
                            open(input_data, "rb"),
                        )

                        file_list["UpdateParameters"] = (
                            os.path.basename(param_data),
                            open(param_data, "rb"),
                            "application/json",
                        )

                        response = requests.post(
                            self.transport_addr + url,
                            auth=(self.m_user, self.m_password),
                            files=file_list,
                            verify=False,
                            timeout=time_out,
                        )
                        DUTAccess.dut_logger.verbose_log(
                            f"POST request: {response.request.headers}"
                        )
                        DUTAccess.dut_logger.verbose_log(
                            f"POST response: {response.headers}"
                        )
                        my_dict = json.loads(response.text)
                    if response.status_code in (200, 202):
                        status = True
                    else:
                        if not json_prints:
                            print(json.dumps(my_dict, indent=2))
                        DUTAccess.dut_logger.verbose_log(
                            "POST: Error sending request: " + f"{response}"
                        )
                        Util.bail_nvfwupd(
                            1,
                            f"Error sending POST request: \
                            {response.reason, response.status_code}",
                            Util.BailAction.DO_NOTHING,
                            print_json=json_prints,
                        )
                        return False, my_dict
        except requests.exceptions.RequestException as excpt:
            DUTAccess.dut_logger.verbose_log(
                f"Error: Error sending HTTPs request: {excpt}"
            )
            if not suppress_err:
                Util.bail_nvfwupd(
                    1,
                    f"Error: Error sending HTTPs request: {excpt.response}",
                    Util.BailAction.DO_NOTHING,
                    print_json=json_prints,
                )
            return False, my_dict
        return status, my_dict

    def get_system_info(self, json_dict=None):
        """
        Query system info via Redish System API
        Parameters:
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True if system info is successfully acquired or
            False if the info could not be acquired
        """
        # pylint: disable=too-many-branches, too-many-nested-blocks
        status, chassis_dict = self.dispatch_request(
            "GET", "/redfish/v1/Chassis/DGX", suppress_err=True, json_prints=json_dict
        )
        curr_platform = None
        if status is True:
            curr_platform = chassis_dict.get("Model", "N/A")
        else:
            chassis_status, chassis_dict = self.dispatch_request(
                "GET", "/redfish/v1/Chassis/", suppress_err=True, json_prints=json_dict
            )

            if chassis_status is False:
                Util.bail_nvfwupd(
                    1, f"Unable to access BMC: {self.m_ip}", print_json=json_dict
                )

            chassis_list = [
                member["@odata.id"].split("/")[-1] for member in chassis_dict["Members"]
            ]

            platform_dict = {
                "HGX_BMC_0": "NVIDIA HGX H100",
                "Bluefield_BMC": "Bluefield_BMC",
            }

            for chassis in chassis_list:
                if chassis in platform_dict:
                    status, chassis_dict = self.dispatch_request(
                        "GET",
                        f"/redfish/v1/Chassis/{chassis}",
                        suppress_err=True,
                        json_prints=json_dict,
                    )
                    if status is True:
                        curr_platform = chassis_dict.get("Model")
                        if curr_platform is not None and curr_platform.startswith("$"):
                            curr_platform = platform_dict[chassis]
                        break

            if curr_platform is None:
                status, chassis_dict = self.dispatch_request(
                    "GET",
                    "/redfish/v1/Chassis/BMC_0",
                    suppress_err=True,
                    json_prints=json_dict,
                )
                if status is True:
                    curr_platform = chassis_dict.get("Model")
                    if curr_platform is not None:
                        for platform, model_name in platform_dict.items():
                            platform_name = platform.partition("_Management_Board")[0]
                            if platform_name in curr_platform:
                                curr_platform = model_name
                                break

        self.m_model = chassis_dict.get("Model", "N/A")
        self.m_partnumber = chassis_dict.get("PartNumber", "N/A")
        self.m_serialnumber = chassis_dict.get("SerialNumber", "N/A")

        if status and curr_platform is not None:
            self.m_model = curr_platform
            status = True
        else:
            if not json_dict:
                DUTAccess.dut_logger.debug_print(
                    "Could not find Chassis URI containing BMC Model data"
                )

        if not json_dict:
            DUTAccess.dut_logger.debug_print(
                f"System info in Chassis - Model:{self.m_model} Partno:{self.m_partnumber} "
                f"Serialno:{self.m_serialnumber}"
            )

        return status

    # pylint: disable=too-many-positional-arguments
    def multipart_file_upload(
        self,
        url="",
        pkg_file=None,
        upd_params_file=None,
        time_out=900,
        updparams_json=None,
        json_prints=None,
        parallel_update=False,
    ):
        """
        Method to perform FW update with multipart upload
        Parameters:
            url The Redfish URL for updating
            pkg_file The path of the update file for the upload
            upd_params_file Optional File containing update parameters
            time_out Timeout in seconds for the request
            updparams_json Update parameters in JSON format
            json_prints Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        Returns:
            True and a JSON response dictionary of the upload response or
            False and None if there is an upload failure
        """
        status = False
        response_dict = None
        file_list = {}
        pkg_file_fd = open(pkg_file, "rb")
        params_file_fd = None
        file_list["UpdateFile"] = (
            os.path.basename(pkg_file),
            pkg_file_fd,
            "application/octet-stream",
        )

        if upd_params_file is not None:
            params_file_fd = open(upd_params_file, "rb")
            file_list["UpdateParameters"] = (
                os.path.basename(upd_params_file),
                params_file_fd,
                "application/json",
            )
        elif updparams_json is not None:
            file_list["UpdateParameters"] = (None, updparams_json, "application/json")
        try:
            response = requests.post(
                self.transport_addr + url,
                auth=(self.m_user, self.m_password),
                files=file_list,
                verify=False,
                timeout=time_out,
            )
            pkg_file_fd.close()
            if params_file_fd is not None:
                params_file_fd.close()

            DUTAccess.dut_logger.verbose_log(
                f"Request sent: {response.request.headers}"
            )
            DUTAccess.dut_logger.verbose_log(f"Response rcvd: {response.headers}")
            try:
                response_dict = json.loads(response.text)
            except json.decoder.JSONDecodeError:
                Util.bail_nvfwupd_threadsafe(
                    1,
                    f"Could not decode update response body: \
                    response text: {response.text} status: {response.status_code}",
                    print_json=json_prints,
                    parallel_update=parallel_update,
                )
                return status, response_dict
            if response.status_code in (200, 202):
                status = True
            else:
                DUTAccess.dut_logger.verbose_log(
                    "POST: Error in multipart file upload, "
                    + f"response: {response.text}"
                )
                if not json_prints:
                    print(json.dumps(response_dict, indent=2))

                Util.bail_nvfwupd_threadsafe(
                    1,
                    f"Error sending POST request: \
                    {response.reason, response.status_code}",
                    print_json=json_prints,
                    parallel_update=parallel_update,
                )
                return status, response_dict
        except requests.exceptions.RequestException as excpt:
            DUTAccess.dut_logger.verbose_log(
                "POST: Error in multipart file upload, " f"error: {excpt}"
            )
            pkg_file_fd.close()
            if params_file_fd is not None:
                params_file_fd.close()
            Util.bail_nvfwupd_threadsafe(
                1,
                f"Error: Error sending HTTPs request: {excpt.response}",
                print_json=json_prints,
                parallel_update=parallel_update,
            )
        return status, response_dict


class BMCPortForwardAccess(BMCLoginAccess):
    """
    BMC access with loopback IP and port number
    ...
    Attributes
    ----------
    m_model : str
        System model
    m_partnumber : str
        System part number
    m_serialnumber : str
        System serial number
    m_ip : str
        System IP Address
    m_user : str
        System username
    m_password : str
        System password
    transport_addr : str
        Transport type combined with system IP for initial URIs
    transport_type : str
        HTTP or HTTPS for communication
    m_port : str
        System port number

    Methods
    -------
    is_valid() :
        Determines if the system IP and port are valid
    get_arg_count() :
        Acquire the expected number of arguments for the instance
    update_transport_type(transport_type) :
        Change the transport type to HTTP or HTTPS
    """

    def __init__(self, access_args_dict):
        """
        BMC access constructor with BMC IP and port number
        An exception will be raised if access_args_dict does not contain
        the expected ip and port number
        Parameter:
            access_args_dict Dictionary containing system IP, username,
            password and port
        """
        super().__init__(access_args_dict)
        self.m_port = access_args_dict.get("port", "")

    def is_valid(self):
        """
        Checks if access instance is valid
        Returns:
            True, and an emptry string if the ip address and port are both valid or
            True, and a Port valid message if the port is valid, but in use or
            False, and an error message if the IP or port is not valid
        """
        try:
            test_ip = re.sub(r"\[|\]", "", self.m_ip)
            ipaddress.ip_address(test_ip)
        except ValueError:
            return False, f"invalid IP address: {self.m_ip}"
        # check if the port is in use
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as soc_stream:
            try:
                soc_stream.connect_ex(("localhost", int(self.m_port)))
            except socket.error as err:
                if err.errno == errno.EADDRINUSE:
                    self.update_transport_type("https")
                    return True, f"Port valid: {self.m_port}"
                return False, f"Socket error for : {self.m_ip, self.m_port}"
        self.update_transport_type("https")
        return True, ""

    def get_arg_count(self):
        """
        Return the number of expected arguments for this BMC access
        instance. The number of arugments expected for this instance
        is 2: BMC IP, port forwarding address
        """
        return 2

    def update_transport_type(self, transport_type):
        """
        Updates the transport type used internally.
        Parameter:
            transport_type http or https string
        """

        self.transport_type = transport_type
        self.transport_addr = f"{self.transport_type}://{self.m_ip}:{self.m_port}"
