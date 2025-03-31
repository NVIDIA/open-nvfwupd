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
"""Class that defines update related REST API for GB200 NVL Switch platforms"""

import json
import time
import pprint
import re
import paramiko
from paramiko import SSHClient
from scp import SCPClient
from nvfwupd.utils import Util
from nvfwupd.rf_target import RFTarget


class GB200SwitchTarget(RFTarget):
    """
    Class to implement FW update related REST API for GB200 NVL Switch platforms
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
    ap_file_ext : dict
        Dictionary matching component name to file extension
    bundle_to_target : dict
        Dictionary matching bundle name to target name

    Methods
    -------
    get_target_apname(bundle_ap) :
        Acquire target name for a given bundle component name
    upload_image(file_path, ap_name, parallel_update, print_json=None) :
        Upload an image using scp to the target system
    update_component(param_list, update_uri, update_file, time_out,
                         json_dict=None, parallel_update=False) :
        Unused method (Returns empty string)
    get_update_file(target_comp, pkg_parser) :
        Acquire update file from package for given target
    print_task_completion(task_dict) :
        Use pretty printing to display task completion to console
    start_update_monitor(recipe_list, pkg_parser, cmd_args, time_out,
                             parallel_update, json_dict=None) :
        Begin update task and monitor the task
    get_job_status_with_retry(task_id, json_dict=None, max_retries=3,
                                  interval=5) :
        Query the state of a task id up to the max_retries times
    get_task_status(task_id, json_dict=None) :
        Query the state of a provided task id and print to console
    process_job_status(task_id, print_json=None) :
        Process a task id and return only an error code
    query_job_status(task_id, print_json=None) :
        Acquire task status without printing to console
    print_job_status(task_id, resp_dict, status, json_dict=None) :
        Print previously acquired task status to console
    is_fungible_component(_) :
        Determines if a component is fungible for a given system
    get_component_version(pldm_version_dict, ap_name) :
        Get a component version from a pldm dictionary
    get_identifier_from_chassis(_) :
        Unused method for this class (Returns None)
    get_version_sku(identifier, pldm_version_dict, ap_name) :
        Unused method for this class (Returns N/A)

    """

    UPDATE_URL = "/nvue_v1/platform/firmware/{}/files/{}"
    DEST_UPLOAD_PATH = "/host/fw-images/"

    PENDING_TASK_STATE = {"running", "start"}
    COMPLETED_TASK_STATE = {"action_error", "action_success"}
    UPDATE_ORDER_0000 = ["bmc", "erot", "fpga"]
    UPDATE_ORDER_0002 = ["bios", "erot"]

    def __init__(self, switch_access):
        """
        GB200Switch Target Class Constructor
        Parameter:
            switch_access Initialized switch access class to reach the target
        """
        super().__init__()
        self.target_access = switch_access
        self.fungible_components = []
        self.ap_file_ext = {
            "bios": ".fwpkg",
            "bmc": ".fwpkg",
            "cpld1": ".vme",
            "erot": ".fwpkg",
            "fpga": ".fwpkg",
        }
        self.bundle_to_target = {
            "sbios": "bios",
            "bmc": "bmc",
            "smr": "fpga",
            "cpld": "cpld1",
            "erot": "erot",
        }

    def get_target_apname(self, bundle_ap):
        """
        Get ap name used on target for a given ap name in bundle
        Parameter:
            bundle_ap Component name from bundle
        Returns:
            The found component name
        """
        ap_name = bundle_ap.split(":")[0]
        if "," in ap_name:
            ap_name = bundle_ap.split(",")[0]
        ap_name = self.bundle_to_target.get(ap_name.lower(), ap_name)
        return ap_name

    def upload_image(self, file_path, ap_name, parallel_update, print_json=None):
        """
        Method to scp put the file to target system
        Parameter:
            file_path File path of the update image
            ap_name The name of a component
            parallel_update Boolean value, True if doing a parallel update
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            The filepath of the uploaded remote file or
            None if there was an error
        """
        ssh = None
        scp = None
        remote_file = None
        upload_path = GB200SwitchTarget.DEST_UPLOAD_PATH
        if ap_name == "cpld1":
            ap_folder_name = "cpld"
        else:
            ap_folder_name = ap_name
        try:
            ssh = SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy)
            # ipv6 required without brackets in this instance
            # ipv4 unaffected
            connection_ip = re.sub(r"\[|\]", "", self.target_access.m_ip)
            ssh.connect(
                hostname=connection_ip,
                username=self.target_access.m_user,
                password=self.target_access.m_password,
            )
            ssh.exec_command(f"mkdir -p {upload_path}{ap_folder_name}")
            # Remove old update files from upload path
            ssh.exec_command(f"rm {upload_path}{ap_folder_name}/*")
            scp = SCPClient(ssh.get_transport())
            remote_name = file_path.rsplit("/", 1)[-1]
            expected_ext = self.ap_file_ext.get(ap_name, ".bin")
            remote_name = remote_name.replace(".bin", expected_ext)
            remote_file = f"{upload_path}{ap_folder_name}/{remote_name}"
            scp.put(file_path, remote_file)
            if not print_json:
                print(f"Update file {file_path} was uploaded successfully")
        # pylint: disable=broad-except
        except Exception as all_err:
            # Do not exit the program for parallel updates
            Util.bail_nvfwupd_threadsafe(
                1,
                f"File upload failed for {file_path} error: {all_err}",
                print_json=print_json,
                parallel_update=parallel_update,
            )
            return None
        if scp:
            scp.close()
        if ssh:
            ssh.close()
        return remote_file

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def update_component(
        self,
        param_list,
        update_uri,
        update_file,
        time_out,
        json_dict=None,
        parallel_update=False,
    ):
        """
        Method to perform FW update using redfish request for Switch platforms
        returns task id
        Parameters:
            Unused Parameters
        Returns:
            Empty String
        """
        return ""

    def get_update_file(self, target_comp, pkg_parser):
        """
        Method to identify the file in unpack output for the given target_comp
        return path of the binary file
        Parameters:
            target_comp Target component name
            pkg_parser Package parser to parse the update package
        Returns:
            The update file or
            None if not found
        """
        for bundle_name, ap_data in pkg_parser.unpack_file_ap_dict.items():
            ap_name = self.get_target_apname(bundle_name)
            if ap_name in target_comp.lower():
                return ap_data[1]
        return None

    def print_task_completion(self, task_dict):
        """
        Print task completion using pretty printing
        Parameters:
            task_dict Task Dictionary
        """
        pprint.pprint(task_dict)
        print("")

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
        Identify update target, initiate and monitor the update task
        Parameters:
            recipe_list A list of update packages
            pkg_parser An initialized package parser class
            cmd_args Parsed input command arguments
            time_out Unused
            parallel_update Boolean value, True if doing a parallel update
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            Error code of 0 and update task id list or
            Error code of 0 and empty update task id list for single update or
            1 and None if an error occurs
        """
        # pylint: disable=too-many-branches, too-many-return-statements, too-many-locals, too-many-statements
        task_id_list = []

        status, msg = pkg_parser.parse_pkg(recipe_list[0])
        if status is False:
            Util.bail_nvfwupd(
                1,
                f"Invalid input file {recipe_list[0]}",
                Util.BailAction.DO_NOTHING,
                print_json=json_dict,
            )
            return 1, None
        all_targets = None
        err_code = 0
        pkg_parser.get_unpack_file_dict(recipe_list[0])
        if cmd_args.special is not None:
            # support json input from config file
            if self.validate_json(cmd_args.special):
                json_params = json.loads(cmd_args.special)
                all_targets = json_params.get("Targets")
                if all_targets is None:
                    Util.bail_nvfwupd(
                        1,
                        "Invalid target input",
                        Util.BailAction.DO_NOTHING,
                        print_json=json_dict,
                    )
                    return 1, None
            else:
                try:
                    with open(
                        cmd_args.special[0], "r", encoding="utf-8"
                    ) as params_file:
                        file_dict = json.load(params_file)
                        all_targets = file_dict.get("Targets")
                        if all_targets is None:
                            Util.bail_nvfwupd(
                                1,
                                f"No Targets specified in targets file {cmd_args.special[0]}",
                                Util.BailAction.DO_NOTHING,
                                print_json=json_dict,
                            )
                            return 1, None
                except IOError as e_io_error:
                    Util.bail_nvfwupd(
                        1,
                        "Failed to open or read given special targets file"
                        + f"{cmd_args.special[0]} error: ({e_io_error})",
                        Util.BailAction.DO_NOTHING,
                        print_json=json_dict,
                    )
                    return 1, None
        elif (
            getattr(RFTarget, "config_dict", None) is not None
            and RFTarget.config_dict.get("UpdateParametersTargets", None) is not None
        ):
            all_targets = RFTarget.config_dict.get("UpdateParametersTargets", None)
            if all_targets is None:
                Util.bail_nvfwupd(
                    1,
                    "No targets specified for UpdateParametersTargets in config file",
                    Util.BailAction.DO_NOTHING,
                    print_json=json_dict,
                )
                return 1, None
        else:
            # If special targets not specified, update all components in the fwpkg
            all_targets = []
            targets = []
            for ap_name, _ in pkg_parser.unpack_file_ap_dict.items():
                target_name = self.get_target_apname(ap_name)
                targets.append(target_name)
            if "bios" in targets:
                all_targets = [
                    ap.upper()
                    for ap in GB200SwitchTarget.UPDATE_ORDER_0002
                    if ap in targets
                ]
            elif "cpld1" in targets:
                all_targets = [ap.upper() for ap in targets]
            else:
                all_targets = [
                    ap.upper()
                    for ap in GB200SwitchTarget.UPDATE_ORDER_0000
                    if ap in targets
                ]
        if all_targets is None or not all_targets:
            Util.bail_nvfwupd(
                1,
                "Unable to determine update targets",
                Util.BailAction.DO_NOTHING,
                print_json=json_dict,
            )
            return 1, None
        file_name = ""
        if not json_dict:
            print(f"The following targets will be updated {all_targets}")
        for target in all_targets:
            expected_ext = self.ap_file_ext.get(target.lower(), ".bin")
            file_path = None
            if expected_ext != ".fwpkg":
                # If NVOS needs a non-PLDM update file, call unpack and get the right FW file
                file_path = self.get_update_file(target, pkg_parser)
            else:
                file_path = recipe_list[0]
            if file_path is None:
                if not json_dict:
                    print(f"Could not find a matching firmware file for {target}")
                err_code = 1
                continue

            # upload the file and get the upload path on destination
            dest_path = self.upload_image(
                file_path, target.lower(), parallel_update, print_json=json_dict
            )
            if dest_path is None:
                return 1, None
            file_name = dest_path.rsplit("/", 1)[-1]
            if not json_dict:
                print(f"Starting FW update for: {target}")
            url = GB200SwitchTarget.UPDATE_URL.format(target, file_name)
            post_json = {"@install": {"state": "start", "parameters": {"force": False}}}
            status, err_dict, msg = self.target_access.dispatch_rest_request_post(
                url, post_json, print_json=json_dict
            )

            if status is False:
                Util.bail_nvfwupd(
                    1,
                    f"Update failed with status: {err_dict}",
                    Util.BailAction.DO_NOTHING,
                    print_json=json_dict,
                )
                err_code = 1
                continue
            # If successful, POST response contains task ID only, no JSON body
            job_id = msg.strip()
            if job_id == "":
                Util.bail_nvfwupd(
                    1,
                    "No job ID in response",
                    Util.BailAction.DO_NOTHING,
                    print_json=json_dict,
                )
                err_code = 1
                continue

            if json_dict:
                id_object = {}
                id_object["Id"] = job_id

                # Request to append with ID object
                json_dict["Output"].append(id_object)

            if not json_dict:
                print(f"FW update task was created with ID {job_id}")
                # No reason to query task status for printing when using JSON output
                _, job_status, task_dict = self.get_task_status(job_id, json_dict)
                if task_dict is None:
                    return 1, None

                task_status = task_dict.get("status", "")
                task_state = task_dict.get("state", "")

            if parallel_update:
                # append task id to the list
                task_id_list.append(job_id)
                continue

            # json output is only supported with background
            if cmd_args.background is False and not json_dict:
                if "error" not in job_status and "reboot" in task_status.lower():
                    # Poll to check if system has rebooted
                    # Only needed for SBIOS update, works unreliably
                    reboot_status = self.target_access.get_system_rebooted_status()
                    if not reboot_status:
                        _, job_status, task_dict = self.get_task_status(job_id)
                        Util.bail_nvfwupd(
                            1,
                            f"Task {job_id} reboot not complete",
                            Util.BailAction.DO_NOTHING,
                        )
                        err_code = 1
                elif (
                    "error" not in job_status
                    and task_state in GB200SwitchTarget.PENDING_TASK_STATE
                ):
                    while task_state in GB200SwitchTarget.PENDING_TASK_STATE:
                        _, job_status, task_dict = self.get_task_status(job_id)

                        if task_dict is not None:
                            task_state = task_dict.get("state", "")

                        time.sleep(20)

        return err_code, task_id_list

    def get_job_status_with_retry(
        self, task_id, json_dict=None, max_retries=3, interval=5
    ):
        """
        Query state of task_id and retry 3 times if fails to get status
        Parameters:
            task_id The task id of an ongoing update
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            max_retries Maximum number of retries to get job status
            interval Wait time between retries in seconds
        Returns:
            True, response dictionary with the update task status or
            False/None and None if an error occurs
        """
        status = None
        resp_dict = None
        for attempt in range(max_retries):
            status, resp_dict = self.target_access.get_job_status(
                task_id, json_dict=json_dict
            )
            if status:
                http_status = resp_dict.get("http_status")
                if http_status in range(200, 300):
                    return status, resp_dict
            if attempt < max_retries - 1:
                if not json_dict:
                    print(f"Retrying Task Status Request: {task_id}")
                time.sleep(interval)
        return status, resp_dict

    def get_task_status(self, task_id, json_dict=None):
        """
        Query state of task_id and print to CLI
        Parameters:
            task_id The task id of an ongoing update
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            0, job state as a string, and task response dictionary or
            1, job state as a string, and task response dictionary for errors
        """
        job_state = "running"
        status, resp_dict = self.get_job_status_with_retry(task_id, json_dict=json_dict)
        if status:
            http_status = resp_dict.get("http_status")
            if http_status not in range(200, 300):
                job_state = "error"
            else:
                job_state = resp_dict.get("state", "unknown")
        else:
            job_state = "error"
        if "error" in job_state:
            # system responses appended to output
            # instead of error for JSON mode
            if json_dict:
                json_dict["Output"].append(resp_dict)
            else:
                Util.bail_nvfwupd(
                    1,
                    f"Failure status for job {task_id}: Error {resp_dict}",
                    Util.BailAction.DO_NOTHING,
                    print_json=json_dict,
                )
            return 1, job_state, resp_dict

        if json_dict:
            json_dict["Output"].append(resp_dict)

        if not json_dict:
            print(f"Status for Job Id {task_id}:")
            self.print_task_completion(resp_dict)
        return 0, job_state, resp_dict

    def process_job_status(self, task_id, print_json=None):
        """
        Query state of task_id
        Parameters:
            task_id The task id of an ongoing update
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            0 if the task did not encounter an error or
            1 if the task encountered an error
        """

        ret_val, _, _ = self.get_task_status(task_id, print_json)
        return ret_val

    def query_job_status(self, task_id, print_json=None):
        """
        Acquire job status without printing
        Parameters:
            task_id The task id of an ongoing update
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True, response dictionary with the update task status or
            False/None and None if an error occurs
        """
        status, resp_dict = self.target_access.get_job_status(
            task_id, json_dict=print_json
        )

        return status, resp_dict

    def print_job_status(self, task_id, resp_dict, status, json_dict=None):
        """
        Print previously acquired job status
        Parameters:
            task_id The task id of an ongoing update
            resp_dict The response dictionary for a task
            status Boolean True if the system was reachable, False if not
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            0 and the job state as a string or
            1 and the error job state as a string if there is an error
        """
        job_state = "running"

        if not json_dict:
            # Print delineator
            print("-" * 120)
            print(f"Status for Job Id: {task_id}")

        if status:
            http_status = resp_dict.get("http_status")
            if http_status not in range(200, 300):
                job_state = "error"
            else:
                job_state = resp_dict.get("state", "unknown")
        else:
            job_state = "error"
        if "error" in job_state:
            Util.bail_nvfwupd(
                1,
                f"Failure status for job {task_id}: Error {resp_dict}",
                Util.BailAction.DO_NOTHING,
                print_json=json_dict,
            )
            return 1, job_state.lower()

        if json_dict:
            json_dict["Output"].append(resp_dict)

        if not json_dict:
            self.print_task_completion(resp_dict)
        return 0, job_state.lower()

    def is_fungible_component(self, _):
        """
        Returns:
            False
        """
        return False

    def get_component_version(self, pldm_version_dict, ap_name):
        """
        get package version for ap_name
        Parameters:
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name The name of a component
        Returns:
            Component Version for the provided component name
        """
        # Special handling required for CPLD 4 part ID
        if ap_name in ["cpld1", "cpld2", "cpld3", "cpld4"]:
            temp_ap_name = "cpld1"
        else:
            temp_ap_name = ap_name

        ap_version = "N/A"
        for _, pkg_dict in pldm_version_dict.items():
            for ap_pkg, ap_data in pkg_dict.items():
                bundle_ap_name = self.get_target_apname(ap_pkg)
                if temp_ap_name in bundle_ap_name or bundle_ap_name in temp_ap_name:
                    ap_version = ap_data[0]
                    break

        # Special handling required for CPLD 4 part ID
        if ap_name in ["cpld1", "cpld2", "cpld3", "cpld4"] and ap_version != "N/A":
            version_list = ap_version.split("_")
            # If not 8 segments, this is a non-standard or very old CPLD version
            # Simply display the full length CPLD version for each if this happens
            if len(version_list) == 8:
                if ap_name == "cpld1":
                    ap_version = f"CPLD{version_list[0]}_{version_list[1]}"
                if ap_name == "cpld2":
                    ap_version = f"CPLD{version_list[2]}_{version_list[3]}"
                if ap_name == "cpld3":
                    ap_version = f"CPLD{version_list[4]}_{version_list[5]}"
                if ap_name == "cpld4":
                    ap_version = f"CPLD{version_list[6]}_{version_list[7]}"

        return ap_version

    def get_identifier_from_chassis(self, _):
        """
        Get Redfish Chassis uri for getting sku id
        Returns:
            None
        """
        return None

    def get_version_sku(self, identifier, pldm_version_dict, ap_name):
        """
        Get pkg version for ap_name with matching sku_id
        Parameters:
            Unused Parameters
        Returns:
            N/A
        """
        return "N/A"
