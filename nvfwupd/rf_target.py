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
"""Abstract Class that defines update related RF APIs that
specific platform classes must implement"""
from abc import ABC, abstractmethod
import sys
import time
import json
import re
import os
from datetime import datetime
from tabulate import tabulate  # pylint: disable=import-error
from nvfwupd.utils import Util
from nvfwupd.logger import Logger


# pylint: disable=too-many-public-methods
class RFTarget(ABC):
    """
    Base class to implement FW update related methods using Redfish APIs
    ...
    Attributes
    ----------
    target_access : DUTAccess
        Initialized DUT Access Class Instance
    fungible_components : list
        String list of fungible component types
    update_completion_msg : str
        Message to be displayed upon update completion
    progress_table_header_printed : bool
        True if the progress table was printed for table updates
    config_dict : dict
        Dictionary containing config.yaml target information

    Methods
    -------
    dispatch_request_with_retry(method=None, task_service_uri=None,
                                    input_data=None, json_prints=None,
                                    max_retries=3, interval=5) :
        Send a Redfish request to the target URI up to the maximum
        number of retries
    update_component(cmd_args, update_uri, update_file, time_out,
                         json_dict=None, parallel_update=False) :
        Update a firmware component or target system
    is_fungible_component(component_name) :
        Determines if a component is fungible for a given system
    get_component_version(pldm_version_dict, ap_name) :
        Get a component version from a pldm dictionary
    get_identifier_from_chassis(ap_inv_uri) :
        Get a component identifier from the chassis uri
    get_version_sku(identifier, pldm_version_dict, ap_name) :
        Get a component package version based on device sku
    validate_json(param_list) :
        Check if input is valid JSON
    version_newer(pkg_version, sys_version) :
        Determines if package or system firmware version is newer
    query_job_status(task_id, print_json=None) :
        Acquire task dictionary without printing
    print_job_status(task_id, my_dict, status, print_json=None) :
        Print previously acquired task status response
    process_job_status(task_id, print_json=None) :
        Acquire, parse, and print task status
    get_timestamp(str_time) :
        Format timestamps for task id response strings
    check_for_failure(task_dict) :
        Parse task status for failures
    print_task_completion(task_dict) :
        Print out task completiong with overall time taken
    get_update_uri(_) :
        Acquire Redfish update URI
    get_task_service_uri(task_id) :
        Acquire the task service URI from Redfish for task monitoring
    update_component_multipart(param_list, update_uri,
                                update_file, time_out, param_json,
                                json_dict=None, parallel_update=False) :
        Update a component or system using a multipart file upload
    update_component_pushuri(param_list, update_uri, update_file, time_out,
                                 json_dict=None, parallel_update=False) :
        Update a component or system using HTTP Push URI file upload
    start_update_monitor(recipe_list, pkg_parser, cmd_args, time_out,
                             parallel_update, json_dict=None) :
        Begin a firmware update and monitor the task
    start_update_monitor_table(task_dict, final_result, seen_result) :
        Print update progress in a table format
    """

    SERVER_TYPE_CLASS_DICT = {
        "dgx": "DGX_RFTarget",
        "hgx": "BaseRFTarget",
        "hgxb100": "HGXB100RFTarget",
        "gb200": "GB200RFTarget",
        "gb300": "GB200RFTarget",
        "mgx-nvl": "MGXNVLRFTarget",
        "gb200switch": "GB200SwitchTarget",
    }

    TARGET_CLASS_DICT = {
        "hgx": "BaseRFTarget",
        "dgx": "DGX_RFTarget",
        "gb200 nvl": "GB200RFTarget",
        "gb300 nvl": "GB200RFTarget",
    }

    TARGET_TYPE_CONFIG_DICT = {"ami": "DGX_RFTarget", "openbmc": "BaseRFTarget"}

    TASK_FAILURE_STATES = (
        "cancelled",
        "cancelling",
        "exception",
        "interrupted",
        "killed",
        "stopping",
        "suspended",
    )

    TASK_PENDING_STATES = ("new", "pending", "running", "service", "starting")

    def __init__(self):
        """
        Redfish Target Class Constructor
        """
        self.target_access = None
        self.fungible_components = []
        self.update_completion_msg = ""
        self.progress_table_header_printed = False
        self.config_dict = None

    def dispatch_request_with_retry(
        self,
        method=None,
        task_service_uri=None,
        input_data=None,
        json_prints=None,
        max_retries=3,
        interval=5,
    ):
        """
        Dispatch request and retries up to max_retries times if status is False
        Parameters:
            method GET, PATCH, or POST
            task_service_uri Redfish URI to apply the method to
            input_data Data to send to the URI for PATCH/POST
            json_prints Optional JSON Dictionary used for JSON Mode and Prints
            max_retries Maximum number of retries
            interval Wait time interval in seconds
        Returns:
            True and a task dictionary or
            False and an empty dictionary if there is an error
        """
        status = False
        task_dict = {}
        for attempt in range(max_retries):
            status, task_dict = self.target_access.dispatch_request(
                method=method,
                url=task_service_uri,
                input_data=input_data,
                json_prints=json_prints,
            )
            if status:
                return status, task_dict
            if attempt < max_retries - 1:
                if not json_prints:
                    Logger.debug_print(
                        f"Retrying Task Status Request: {task_service_uri}"
                    )
                time.sleep(interval)
        return status, task_dict

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    @abstractmethod
    def update_component(
        self,
        cmd_args,
        update_uri,
        update_file,
        time_out,
        json_dict=None,
        parallel_update=False,
    ):
        """define steps to update target"""

    @abstractmethod
    def is_fungible_component(self, component_name):
        """check if given component is fungible on the target"""

    @abstractmethod
    def get_component_version(self, pldm_version_dict, ap_name):
        """get version of ap in PLDM"""

    @abstractmethod
    def get_identifier_from_chassis(self, ap_inv_uri):
        """get AP identifier from Chassis response"""

    @abstractmethod
    def get_version_sku(self, identifier, pldm_version_dict, ap_name):
        """get version from pldm for given identifier"""

    # pylint: disable=bare-except
    def validate_json(self, param_list):
        """
        Verify if an input is valid json
        Parameter:
            param_list Update parameters to check if in JSON format
        Returns:
            True if the param list is valid JSON or
            False if param list is not valid JSON
        """
        try:
            json.loads(param_list)
        except:
            return False
        return True

    def version_newer(self, pkg_version, sys_version):
        """
        True if pkg version is > system version
        Parameters:
            pkg_version Package version for a component
            sys_version Running system version for a component
        Returns:
            True if component package version is newer than running system version,
            False if system version is newer
        """
        pkg_arr = re.split("[.|-]", pkg_version)
        sys_arr = re.split("[.|-]", sys_version)
        pkg_is_new = False
        if len(pkg_arr) == len(sys_arr):
            for index, pkg in enumerate(pkg_arr):
                sys_ver = sys_arr[index].strip()
                pkg = pkg.strip()
                if len(pkg) > len(sys_ver):
                    sys_ver = sys_ver.zfill(len(pkg))
                elif len(sys_ver) > len(pkg):
                    pkg = pkg.zfill(len(sys_ver))
                if pkg != sys_ver:
                    if pkg > sys_ver:
                        pkg_is_new = True
                    break
        else:
            pkg_is_new = True
        return pkg_is_new

    def query_job_status(self, task_id, print_json=None):
        """
        Parse task status response without printing
        Parameters:
            task_id The task id of an ongoing update
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True, response dictionary with the update task status or
            False and an empty dictionary if an error occurs
        """
        task_service_uri = self.get_task_service_uri(task_id)
        status, my_dict = self.target_access.dispatch_request(
            "GET", task_service_uri, None, json_prints=print_json
        )

        return status, my_dict

    # pylint: disable=too-many-branches
    def print_job_status(self, task_id, my_dict, status, print_json=None):
        """
        Print task status response
        Parameters:
            task_id The task id of an ongoing update
            my_dict The response dictionary for a task
            status Boolean True if the system was reachable, False if not
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            0, Task State in a string format for successful tasks
            1, Task State in a string format for failed tasks
            1, 'error' string if the job status could not be parsed or
            another error occurs
        """

        # Get TaskState if present
        task_state = my_dict.get("TaskState")

        # set task_state to all lowercase if present
        if task_state is not None:
            task_state = task_state.lower()

        if not print_json:
            # Print delineator
            Logger.indent_print("-" * 120)
            Logger.indent_print(f"Task Info for Id: {task_id}")

        err_status = 0

        if print_json:
            print_json["Output"].append(my_dict)
            if status is False:
                return 1, task_state
            return 0, task_state

        if "error" in my_dict:
            Logger.debug_print(f"{my_dict}")
            Logger.indent_print(f"Input Taskid does not exist: {task_id} ")
            return 1, task_state

        if status is False:
            Logger.debug_print(f"{my_dict}")
            try:
                Logger.indent_print(f"{my_dict} ", 1)
                return 1, task_state
            except KeyError:
                return 1, task_state

        Logger.indent_print(f"StartTime: {my_dict.get('StartTime')}", 1)
        Logger.indent_print(f"TaskState: {my_dict.get('TaskState')}", 1)

        try:
            Logger.indent_print(f"PercentComplete: {my_dict['PercentComplete']}", 1)
        except KeyError:
            pass

        Logger.indent_print(f"TaskStatus: {my_dict.get('TaskStatus', 'Unknown')}", 1)

        try:
            Logger.indent_print(f"EndTime: {my_dict['EndTime']}", 1)
        except KeyError:
            pass
        # Calculate Overall time if task is completed
        if task_state in self.TASK_FAILURE_STATES or task_state == "completed":
            # Timestamp format is different for hmc/bmc
            try:
                # Calculate overall timetaken by the task
                start_time = self.get_timestamp(my_dict["StartTime"])
                end_time = self.get_timestamp(my_dict["EndTime"])

                Logger.indent_print(f"Overall Time Taken: {end_time - start_time}", 1)
            except KeyError:
                pass

        Logger.indent_print(
            f"Overall Task Status: {json.dumps(my_dict, sort_keys=False, indent=4)}", 1
        )
        if task_state in self.TASK_PENDING_STATES:
            Logger.indent_print("Update is still running.")
            err_status = 0
        elif task_state == "completed":
            task_status = my_dict.get("TaskStatus", "Unknown")
            if task_status == "OK":
                Logger.indent_print("Update is successful.")
                err_status = 0
            else:
                Logger.indent_print(f"Update completed with TaskStatus {task_status}")
                err_status = 1
        else:
            Logger.indent_print("Update failed with errors")
            err_status = 1

        return err_status, task_state

    # pylint: disable=too-many-branches
    # pylint: disable=too-many-statements
    def process_job_status(self, task_id, print_json=None):
        """
        Parse task status response and print
        Parameters:
            task_id The task id of an ongoing update
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            0 for successful tasks or
            1 for failed tasks or other errors
        """
        if not print_json:
            Logger.indent_print(f"Task Info for Id: {task_id}")
        task_service_uri = self.get_task_service_uri(task_id)
        status, my_dict = self.target_access.dispatch_request(
            "GET", task_service_uri, None, json_prints=print_json
        )
        err_status = 0

        if print_json:
            print_json["Output"].append(my_dict)
            if status is False:
                return 1
            return 0

        if "error" in my_dict:
            Logger.debug_print(f"{my_dict}")
            Logger.indent_print(f"Input Taskid does not exist: {task_id} ")
            return 1

        if status is False:
            Logger.debug_print(f"{my_dict}")
            try:
                Logger.indent_print(f"{my_dict} ", 1)
                return 1
            except KeyError:
                return 1

        Logger.indent_print(f"StartTime: {my_dict['StartTime']}", 1)
        Logger.indent_print(f"TaskState: {my_dict['TaskState']}", 1)

        try:
            Logger.indent_print(f"PercentComplete: {my_dict['PercentComplete']}", 1)
        except KeyError:
            pass

        Logger.indent_print(f"TaskStatus: {my_dict['TaskStatus']}", 1)

        try:
            Logger.indent_print(f"EndTime: {my_dict['EndTime']}", 1)
        except KeyError:
            pass
        # Calculate Overall time if task is completed
        if (
            my_dict["TaskState"].lower() in self.TASK_FAILURE_STATES
            or my_dict["TaskState"].lower() == "completed"
        ):
            # Timestamp format is different for hmc/bmc
            try:
                # Calculate overall timetaken by the task
                start_time = self.get_timestamp(my_dict["StartTime"])
                end_time = self.get_timestamp(my_dict["EndTime"])

                Logger.indent_print(f"Overall Time Taken: {end_time - start_time}", 1)
            except KeyError:
                pass

        Logger.indent_print(
            f"Overall Task Status: {json.dumps(my_dict, sort_keys=False, indent=4)}", 1
        )
        if my_dict["TaskState"].lower() in self.TASK_PENDING_STATES:
            Logger.indent_print("Update is still running.")
            err_status = 0
        elif my_dict["TaskState"] == "Completed":
            task_status = my_dict.get("TaskStatus", "Unknown")
            if task_status == "OK":
                Logger.indent_print("Update is successful.")
                err_status = 0
            else:
                Logger.indent_print(f"Update completed with TaskStatus {task_status}")
                err_status = 1
        else:
            Logger.indent_print("Update failed with errors")
            err_status = 1

        return err_status

    def get_timestamp(self, str_time):
        """
        get timestamps from update response strings
        Parameter:
            str_time Time to be formatted
        Returns:
            Formatted Time Stamp
        """
        time_stmp = None
        try:
            time_stmp = datetime.strptime(str_time, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            time_stmp = datetime.strptime(str_time, "%Y-%m-%dT%H:%M:%S-0000")
        return time_stmp

    def check_for_failure(self, task_dict):
        """
        check update status for failures
        Parameter:
            task_dict Task dictionary for an ongoing task
        Returns:
            True if the update task status contains a failure or
            False if it does not contain a failure
        """
        task_msgs = task_dict.get("Messages")
        if task_msgs is not None:
            for each in task_msgs:
                msg_id = each.get("MessageId", "")
                msg = each.get("Message", "")
                failed_msgs = ["failed", "error", "violation"]
                if any(err_str in msg_id.lower() for err_str in failed_msgs) or any(
                    err_str in msg.lower() for err_str in failed_msgs
                ):
                    return True
        return False

    def print_task_completion(self, task_dict):
        """
        Print task completion with time taken
        Parameter:
            task_dict Task dictionary for an ongoing task
        """
        try:
            # Calculate overall timetaken by the task
            start_time = self.get_timestamp(task_dict["StartTime"])
            end_time = self.get_timestamp(task_dict["EndTime"])
            Logger.indent_print(f"Overall Time Taken: {end_time - start_time}", 0)
            Logger.indent_print(f"{self.update_completion_msg}", 0)
        except KeyError:
            pass

    def get_update_uri(self, _):
        """
        get update URI from update service
        Returns:
            /redfish/v1/UpdateService URI
        """
        return "/redfish/v1/UpdateService"

    def get_task_service_uri(self, task_id):
        """
        get URI for task monitoring
        Parameter:
            task_id The task id of an ongoing update
        Returns:
            The Redfish Task Service URI for the provided task
        """
        task_service_uri = re.sub(
            r"/+", "/", f"/redfish/v1/TaskService/Tasks/{task_id}"
        )
        return task_service_uri

    # pylint: disable=too-many-arguments
    def update_component_multipart(
        self,
        param_list,
        update_uri,
        update_file,
        time_out,
        param_json,
        json_dict=None,
        parallel_update=False,
    ):
        """
        Method to perform FW update using redfish request for DGX platforms
        returns task id
        Parameters:
            param_list List containing a file of special parameters
            used for the update
            update_uri Target Redfish URI used for the update
            update_file Firmware package file path used for the update
            time_out Timeout period in seconds for the requests
            param_json Special JSON parameters used for the update
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        Returns:
            Task ID of the ongoing update or
            None if there is an error or failure
        """
        task_id = ""
        status = False
        response_dict = None
        if param_list is not None:
            status, response_dict = self.target_access.multipart_file_upload(
                url=update_uri,
                pkg_file=update_file,
                upd_params_file=param_list[0],
                time_out=time_out,
                updparams_json=None,
                json_prints=json_dict,
                parallel_update=parallel_update,
            )
            if not status:
                Util.bail_nvfwupd_threadsafe(
                    1,
                    f"Firmware update request failed! {response_dict}",
                    print_json=json_dict,
                    parallel_update=parallel_update,
                )
                return None
        elif param_json is not None:
            status, response_dict = self.target_access.multipart_file_upload(
                url=update_uri,
                pkg_file=update_file,
                upd_params_file=None,
                time_out=time_out,
                updparams_json=param_json,
                json_prints=json_dict,
                parallel_update=parallel_update,
            )
            if not status:
                Util.bail_nvfwupd_threadsafe(
                    1,
                    f"Firmware update request failed! {response_dict}",
                    print_json=json_dict,
                    parallel_update=parallel_update,
                )
                return None
        else:
            status, response_dict = self.target_access.multipart_file_upload(
                url=update_uri,
                pkg_file=update_file,
                upd_params_file=None,
                time_out=time_out,
                updparams_json=None,
                json_prints=json_dict,
                parallel_update=parallel_update,
            )
        if status is False:
            Util.bail_nvfwupd_threadsafe(
                1,
                f"File upload failed with error {response_dict}",
                print_json=json_dict,
                parallel_update=parallel_update,
            )
            return None

        if not json_dict:
            print(json.dumps(response_dict))
        task_id = response_dict.get("Id", "")
        if task_id == "":
            try:
                messages = response_dict["Messages"][0]
                task_id = messages["MessageArgs"][0].rsplit("/", 1)[-1]
            except KeyError:
                pass

        # append the response for the json output
        if json_dict:
            json_dict["Output"].append(response_dict)

        return task_id

    def update_component_pushuri(
        self,
        param_list,
        update_uri,
        update_file,
        time_out,
        json_dict=None,
        parallel_update=False,
    ):
        """
        Method to perform FW update using redfish request with HTTP Push URI
        returns task id
        Parameters:
            param_list List of update parameters
            update_uri Target Redfish URI used for the update
            update_file The file used for the firmware update
            time_out Timeout period in seconds for the requests
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        Returns:
            Task ID of the ongoing update or
            None if there is an error or failure
        """
        task_id = ""
        if param_list is not None:
            # Send patch request for update params
            status, err_dict = self.target_access.dispatch_request(
                "PATCH",
                update_uri,
                param_data=param_list,
                time_out=time_out,
                json_prints=json_dict,
            )
            if not status:
                Util.bail_nvfwupd_threadsafe(
                    1,
                    f"Patch update request failed! {err_dict}",
                    print_json=json_dict,
                    parallel_update=parallel_update,
                )
                return None
        # POST fw update command via Redish System API
        status, response_dict = self.target_access.dispatch_file_upload(
            update_uri,
            input_data=update_file,
            time_out=time_out,
            json_output=json_dict,
            parallel_update=parallel_update,
        )
        if status is False:
            Util.bail_nvfwupd_threadsafe(
                1,
                f"File upload failed with error {response_dict}",
                print_json=json_dict,
                parallel_update=parallel_update,
            )
            return None

        # append the response for the json output
        if json_dict:
            json_dict["Output"].append(response_dict)

        task_id = response_dict.get("Id", "")
        return task_id

    def start_update_monitor(
        self,
        recipe_list,
        pkg_parser,
        cmd_args,
        time_out,
        parallel_update,
        json_dict=None,
    ):
        """
        start FW update and monitor it till completion
        Parameters:
            recipe_list A list of update packages
            pkg_parser An initialized package parser class
            cmd_args Parsed input command arguments
            time_out Timeout period in seconds for the requests
            parallel_update Boolean value, True if doing a parallel update
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            0 and a list of task ids if a parallel update is ongoing and successful
            0 and an empty list of task ids if a single update is successful
            1 and None if there is an error
        """
        # pylint: disable=too-many-branches, too-many-nested-blocks, too-many-statements, too-many-locals
        err_status = 0
        update_uri = ""
        task_id_list = []
        # Verify if the UpdateService is enabled
        status, my_dict = self.target_access.dispatch_request(
            "GET", "/redfish/v1/UpdateService", None, json_prints=json_dict
        )
        if (status is False) or (my_dict["ServiceEnabled"] is False):
            Util.bail_nvfwupd(
                1,
                "UpdateService is not enabled in the system",
                Util.BailAction.PRINT_DIVIDER,
                print_json=json_dict,
            )
            err_status = 1
            return err_status, None

        if cmd_args.staged_update or cmd_args.staged_activate_update:
            try:
                multipart_option_support = my_dict["Oem"]["Nvidia"][
                    "MultipartHttpPushUriOptions"
                ]["UpdateOptionSupport"]
                if (
                    "StageAndActivate" not in multipart_option_support
                    or "StageOnly" not in multipart_option_support
                ):
                    Util.bail_nvfwupd(
                        1,
                        "System does not support staged update",
                        Util.BailAction.DO_NOTHING,
                        print_json=json_dict,
                    )
                    err_status = 1
                    return err_status, None
            except KeyError:
                Util.bail_nvfwupd(
                    1,
                    "System does not support staged update",
                    Util.BailAction.DO_NOTHING,
                    print_json=json_dict,
                )
                err_status = 1
                return err_status, None
        # fetch the URI service for POST

        update_uri = self.get_update_uri(my_dict)

        task_id = ""
        final_result = []
        seen_result = {}
        for each in recipe_list:
            status, msg = pkg_parser.parse_pkg(each)
            if status is False:
                if not json_dict:
                    Logger.indent_print(
                        f"WARN: {each} is not a valid package. Ignoring"
                    )
                Util.bail_nvfwupd(
                    1, msg, Util.BailAction.DO_NOTHING, print_json=json_dict
                )
                err_status = 1
                break
            # send update requests here
            task_id = self.update_component(
                cmd_args, update_uri, each, time_out, json_dict, parallel_update
            )
            if task_id is None:
                Util.bail_nvfwupd(
                    1,
                    "Failed to acquire task ID",
                    Util.BailAction.DO_NOTHING,
                    print_json=json_dict,
                )
                err_status = 1
                return err_status, None
            task_service_uri = self.get_task_service_uri(task_id)

            # if the POST cmd is successful, we should receive a task ID
            if task_id != "":
                if not json_dict:
                    Logger.indent_print(f"FW update started, Task Id: {task_id}")
                if parallel_update:
                    # append task id to the list
                    task_id_list.append(task_id)
                    continue
                # if update needs to be monitored, below code will be executed
                if cmd_args.background is False:
                    # workaround for DGX
                    _, task_dict = self.target_access.dispatch_request(
                        "GET", task_service_uri, None, json_prints=json_dict
                    )
                    if "error" in task_dict:
                        if not json_dict:
                            Logger.indent_print(
                                f"Input Taskid does not exist: {task_id} "
                            )
                        err_status = 1
                        break
                    count = 0
                    last_progress = 0
                    last_update_time = time.time()
                    task_timeout = 600
                    # Until messageId proceeds to FirmwareUpdateStarted, we won't get
                    # PercentComplete field which will break foreground monitoring
                    count = 0
                    break_out = 0
                    while count < 10:
                        if not json_dict:
                            print("Wait for Firmware Update to Start...")
                        _, task_dict = self.target_access.dispatch_request(
                            "GET", task_service_uri, None, json_prints=json_dict
                        )

                        if not json_dict:
                            Logger.debug_print(f"{task_dict}")
                        try:
                            task_state = task_dict.get("TaskState")
                            for each_msg in task_dict["Messages"]:
                                if (
                                    "Update.1.0.InstallingOnComponent"
                                    in each_msg["MessageId"]
                                ):
                                    if not json_dict:
                                        print()
                                        Logger.indent_print(
                                            f"Started Updating: {each_msg['MessageArgs'][1]}"
                                        )
                                elif (
                                    task_state is not None
                                    and task_state.lower() in self.TASK_FAILURE_STATES
                                ):

                                    if not json_dict:
                                        print()
                                        print(
                                            f"{json.dumps(task_dict, sort_keys=False, indent=4)}"
                                        )
                                    Util.bail_nvfwupd(
                                        1,
                                        "FW update failed with the errors",
                                        Util.BailAction.DO_NOTHING,
                                        print_json=json_dict,
                                    )
                                    err_status = 1
                                    break_out = 1
                                    break
                            break
                        except KeyError:
                            pass
                        count = count + 1
                        time.sleep(15)
                    # if count is = 10, then we didn't get the FirmwareUpdateStarted message
                    # or any error yet print current task details before proceeding as monitoring
                    # loop will not print anything if PercentComplete is missing
                    if count == 10:
                        if not json_dict:
                            print(
                                f"Waiting for Task Id {task_id} to start. Current task details:"
                            )
                            print(f"{json.dumps(task_dict, sort_keys=False, indent=4)}")
                    if break_out > 0:
                        break
                    time.sleep(10)
                    try:
                        while True:
                            time.sleep(5)
                            status, task_dict = self.dispatch_request_with_retry(
                                method="GET",
                                task_service_uri=task_service_uri,
                                input_data=None,
                                json_prints=json_dict,
                                max_retries=3,
                                interval=5,
                            )
                            if not status:
                                Util.bail_nvfwupd(
                                    1,
                                    "Failed to get task status.",
                                    Util.BailAction.DO_NOTHING,
                                    print_json=json_dict,
                                )
                            task_state = task_dict["TaskState"]
                            task_status = task_dict.get("TaskStatus", "Unknown")
                            progress = task_dict["PercentComplete"]
                            count = len(task_dict["Messages"])
                            if not json_dict:
                                Logger.debug_print(f"{task_dict}")
                            # print task details when there is any update
                            if progress != last_progress:
                                last_progress = progress
                                if not json_dict:
                                    if cmd_args.details:
                                        self.start_update_monitor_table(
                                            task_dict, final_result, seen_result
                                        )
                                    else:
                                        Logger.indent_print(f"TaskState: {task_state}")
                                        Logger.indent_print(
                                            f"PercentComplete: {task_dict['PercentComplete']}"
                                        )
                                        Logger.indent_print(
                                            f"TaskStatus: {task_status}"
                                        )
                            if task_state == "Completed":
                                if task_status == "OK":
                                    if not json_dict:
                                        Logger.indent_print(
                                            "Firmware update successful!"
                                        )
                                        self.print_task_completion(task_dict)
                                    err_status = 0
                                    break_out = 1
                                    break
                                # In case of Warning or other task_status values
                                try:
                                    if not json_dict:
                                        Logger.indent_print(
                                            "Task Message:"
                                            f"{task_dict['Messages'][count -1]['Message']}"
                                        )
                                        Logger.indent_print(
                                            f"Severity: {task_dict['Messages'][count -1]['Message']}"
                                        )
                                except KeyError:
                                    pass
                                if not json_dict:
                                    Logger.indent_print(
                                        f"TaskState: {task_dict['TaskState']}"
                                    )
                                    Logger.indent_print(
                                        f"{json.dumps(task_dict, sort_keys=False, indent=4)}"
                                    )
                                if self.check_for_failure(task_dict):
                                    Util.bail_nvfwupd(
                                        1,
                                        "Firmware update had errors.",
                                        Util.BailAction.DO_NOTHING,
                                        print_json=json_dict,
                                    )
                                    err_status = 1
                                    break_out = 1
                                    break
                                if not json_dict:
                                    Logger.indent_print(
                                        f"Firmware update was completed with status {task_status}"
                                    )
                                    self.print_task_completion(task_dict)
                                err_status = 0
                                break_out = 1
                                break
                            if task_state == "Cancelled":
                                try:
                                    if not json_dict:
                                        Logger.indent_print(
                                            f"TaskStatus: {task_dict['Messages'][count -1]['Message']}"
                                        )
                                        Logger.indent_print(
                                            f"Severity: {task_dict['Messages'][count -1]['Severity']}"
                                        )
                                except KeyError:
                                    pass
                                if not json_dict:
                                    Logger.indent_print(
                                        f"TaskState: {task_dict['TaskState']}"
                                    )
                                Util.bail_nvfwupd(
                                    1,
                                    "Firmware update request cancelled by host BMC",
                                    Util.BailAction.DO_NOTHING,
                                    print_json=json_dict,
                                )
                                err_status = 1
                                break_out = 1
                                break
                            # If task is not running anymore, check for failure and exit
                            if task_state.lower() in self.TASK_FAILURE_STATES:
                                if not json_dict:
                                    if cmd_args.details:
                                        self.start_update_monitor_table(
                                            task_dict, final_result, seen_result
                                        )
                                    else:
                                        print(
                                            f"{json.dumps(task_dict, sort_keys=False, indent=4)}"
                                        )
                                Util.bail_nvfwupd(
                                    1,
                                    "Update failed with exception",
                                    Util.BailAction.DO_NOTHING,
                                    print_json=json_dict,
                                )
                                break_out = 1
                                err_status = 1
                                break
                            last_update_time = time.time()
                            if (time.time() - last_update_time) > task_timeout:
                                Util.bail_nvfwupd(
                                    1,
                                    "Timeout reached,"
                                    + "check the task status with show_update_progress command.",
                                    Util.BailAction.DO_NOTHING,
                                    print_json=json_dict,
                                )
                                err_status = 1
                                break_out = 1
                                break
                            time.sleep(15)

                        if break_out > 0:
                            break
                    except KeyError:
                        if not json_dict:
                            print(f"Task Id missing key: {sys.exc_info()[1]}")
                            Logger.indent_print("Error monitoring task status")
                        Util.bail_nvfwupd(
                            0,
                            "use show_update_progress command to monitor the progress",
                            Util.BailAction.DO_NOTHING,
                            print_json=json_dict,
                        )
                        err_status = 1
                        break
                else:
                    if not json_dict:
                        Logger.indent_print("Firmware update in progress")
                    Util.bail_nvfwupd(
                        0,
                        "use show_update_progress command to monitor the progress",
                        Util.BailAction.DO_NOTHING,
                        print_json=json_dict,
                    )
                    err_status = 0
                    break
            if "error" in my_dict:
                err_status = 1
                for value in my_dict.values():
                    if "message" in value:
                        try:
                            if not json_dict:
                                Logger.indent_print(f"Error: {value['message']}")
                        except KeyError:
                            pass
                        Util.bail_nvfwupd(
                            1,
                            "Firmware Update request failed",
                            Util.BailAction.DO_NOTHING,
                            print_json=json_dict,
                        )
                        break
            elif not status:
                err_status = 1
                Util.bail_nvfwupd(
                    1,
                    "Firmware update request failed!",
                    Util.BailAction.DO_NOTHING,
                    print_json=json_dict,
                )
                break
        return err_status, task_id_list

    def start_update_monitor_table(self, task_dict, final_result, seen_result):
        """
        Print Update Progress to console as tabular format
        Parameters:
            task_dict Returned task dictionary for an ongoing task
            final_result List to assist with table printing
            seen_result Dictionary to store used keys and values
        Returns:
            None
        """
        displayed_data = []
        table_header = ["MessageId", "Message"]
        final_result, seen_result = Util.compare_dict(
            task_dict["Messages"], final_result, seen_result
        )
        displayed_data.extend(final_result)
        table = [
            [Util.wrap_text(key, 25), Util.wrap_text(value, 60)]
            for item in displayed_data
            for key, value in item.items()
        ]
        if not self.progress_table_header_printed:
            print(tabulate(table, headers=table_header, tablefmt="grid"))
            self.progress_table_header_printed = True
            del displayed_data[:]
            del final_result[:]
            return
        print(tabulate(table, tablefmt="grid"))

        del displayed_data[:]
        del final_result[:]
