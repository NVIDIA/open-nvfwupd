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
"""Class that defines update related behavior for HGX-B100"""
import re
import json
import os
from nvfwupd.utils import Util
from nvfwupd.base_rftarget import BaseRFTarget


class HGXB100RFTarget(BaseRFTarget):
    """
    Class to implement FW update related Redfish APIs for HGX-B100
    based on configured behavior
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
    is_fungible_component(component_name) :
        Determines if a component is fungible for a given system
    version_newer(pkg_version, sys_version) :
        Determines if package or system firmware version is newer
    get_version_sku(identifier, pldm_version_dict, ap_name) :
        Get a component package version based on device sku
    get_component_version(pldm_version_dict, ap_name) :
        Get a component version from a pldm dictionary
    update_component(cmd_args, update_uri, update_file, time_out,
                        json_dict=None, parallel_update=False) :
        Update a firmware component or target system

    """

    def __init__(self, dut_access):
        """
        HGXB100 Redfish Target Class Constructor
        Parameter:
            dut_access Initialized DUT access class to reach the target

        """
        super().__init__(dut_access)
        self.target_access = dut_access
        self.fungible_components = ["gpu", "nvswitch", "fpga", "erot"]
        self.update_completion_msg = (
            "Refer to Firmware Update Document on "
            + "activation steps for new firmware to take effect."
        )

    def is_fungible_component(self, component_name):
        """
        Fungible component for HGX B100
        Parameter:
            component_name The string name of the component
        Returns:
            True if the component is fungible or
            False if the component is not fungible
        """
        if any(map(component_name.__contains__, self.fungible_components)) and not any(
            map(component_name.__contains__, ["inforom"])
        ):
            return True
        return False

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
        if sys_version.find(".") == -1:
            pkg_version = pkg_version.replace(".", "")
        regex = re.compile("[0-9]+_[0-9]+_[0-9]+", re.IGNORECASE)
        if regex.match(sys_version) or regex.match(pkg_version):
            pkg_version = pkg_version.replace("_", "")
            sys_version = sys_version.replace("_", "")
        regex = re.compile("[a-zA-Z0-9]*[_|-]", re.IGNORECASE)
        match = regex.match(sys_version)
        if match:
            sys_version = regex.sub("", sys_version, 1)
            end_match = re.search("-[a-zA-Z]+", sys_version)
            if end_match is not None:
                sys_version = sys_version[: end_match.start()]
        return super().version_newer(pkg_version, sys_version)

    def get_version_sku(self, identifier, pldm_version_dict, ap_name):
        """
        Get pkg version for gpu with matching sku_id
        Parameters:
            identifier A string identifier used to match a package component
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name The name of a component
        Returns:
            Pkg version for a component with matching sku ID or
            N/A if not found
        """
        for _, pkg_dict in pldm_version_dict.items():
            for _, pkg_data in pkg_dict.items():
                if pkg_data[1] == identifier:
                    return pkg_data[0]
        return "N/A"

    def get_component_version(self, pldm_version_dict, ap_name):
        """
        Get matching component version from PLDM dict for given ap
        Parameters:
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name The name of a component
        Returns:
            The component version for the passed in component name or
            N/A if it could not be determined
        """
        # pylint: disable=too-many-branches
        ap_version = "N/A"
        hgx_pkg_only = False
        if ap_name.find("hgx_") == 0:
            if ap_name.find("hgx_fw_") == 0:
                ap_name = ap_name[len("hgx_fw_") :]
            else:
                ap_name = ap_name[len("hgx_") :]
            hgx_pkg_only = True
            if ap_name.startswith("bmc"):
                ap_name = "hmc"
        if "erot" in ap_name:
            ap_name = "erot"
        if "gpu" in ap_name and "inforom" not in ap_name:
            ap_name = "gpu"
        elif "cpu" in ap_name:
            ap_name = "sbios"
        elif "nvlink" in ap_name:
            ap_name = "cx7"
        ap_name = ap_name.replace("_", "")
        for pkg, pkg_dict in pldm_version_dict.items():
            pkg_is_hgx = self.is_hgx_pkg(pkg)
            if hgx_pkg_only and not pkg_is_hgx:
                continue
            if not hgx_pkg_only and pkg_is_hgx:
                continue
            for ap_full, pkg_version in pkg_dict.items():
                ap_pkg = ap_full.split(",")[0].lower()
                ap_pkg = ap_pkg.split(":")[0].lower()
                ap_pkg = ap_pkg.replace("_", "")
                ap_pkg = ap_pkg.replace("-", "")
                if "inforom" in ap_name and "inforom" not in ap_pkg:
                    continue
                if ap_pkg in ap_name:
                    ap_version = pkg_version[0]
                elif "smr" in ap_pkg and "fpga" in ap_name:
                    ap_version = pkg_version[0]
                else:
                    alt_ap = ap_pkg + "0"
                    if alt_ap == ap_name:
                        ap_version = pkg_version[0]
        return ap_version

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def update_component(
        self,
        cmd_args,
        update_uri,
        update_file,
        time_out,
        json_dict=None,
        parallel_update=False,
    ):
        """
        Method to perform FW update using redfish request for B100, B200
        returns task id
        Parameters:
            cmd_args Parsed input command arguments
            update_uri Target Redfish URI used for the update
            update_file File used for the update
            time_out Timeout period in seconds for the requests
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        Returns:
            Task ID of the update task or
            None if there was a failure
        """
        # cmd_args.special - User passed in JSON Update Parameters or file with Update Parameters
        param_list = cmd_args.special

        # By default use HTTPPUSHURI
        push_uri = True
        json_data = None

        # Read in params if they exist, then decide to use either push_uri or multipart
        if param_list is not None and self.validate_json(param_list):
            json_data = json.loads(param_list)
        elif param_list is not None and os.path.isfile(param_list[0]):
            try:
                with open(param_list[0], "r", encoding="utf-8") as file:
                    json_data = json.load(file)
            except json.JSONDecodeError:
                # Improper update file
                Util.bail_nvfwupd_threadsafe(
                    1,
                    "Error: Invalid JSON special update file",
                    print_json=json_dict,
                    parallel_update=parallel_update,
                )
                return None

        # Presence of empty dictionary or Targets means use multipart
        if json_data is not None and ("Targets" in json_data or json_data == {}):
            push_uri = False

        if cmd_args.staged_update or cmd_args.staged_activate_update:
            # staged or stage and activate means multipart must be used
            push_uri = False

            if json_data is not None and "HttpPushUriTargets" in json_data:
                # This is not supported, as staged and staged activate require multipart
                Util.bail_nvfwupd_threadsafe(
                    1,
                    "Error: HttpPushUriTargets is not supported with staged updates",
                    print_json=json_dict,
                    parallel_update=parallel_update,
                )
                return None

            if param_list is None:
                # If no options selected assume whole update for multipart
                json_data = {}

            # Add the OEM parameters for staging
            if cmd_args.staged_update:
                json_data["Oem"] = {"Nvidia": {"UpdateOption": "StageOnly"}}
            elif cmd_args.staged_activate_update:
                json_data["Oem"] = {"Nvidia": {"UpdateOption": "StageAndActivate"}}
            # Update parameters
            param_list = json.dumps(json_data)

        if push_uri:
            # Default HTTPPUSHURI
            special_targets = ""
            task_id = ""
            if param_list is not None:
                if self.validate_json(param_list):
                    special_targets = param_list
                else:
                    try:
                        with open(param_list[0], "r", encoding="utf-8") as params_file:
                            special_targets = params_file.read()
                    except IOError as e_io_error:
                        Util.bail_nvfwupd_threadsafe(
                            1,
                            f"Failed to open or read given file {param_list[0]} "
                            + f"error: ({e_io_error})",
                            print_json=json_dict,
                            parallel_update=parallel_update,
                        )
                        return None
                status, err_dict = self.target_access.dispatch_request(
                    "PATCH",
                    "/redfish/v1/UpdateService",
                    param_data=special_targets,
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
        else:
            # need to adjust update_uri if using multipart
            update_service_status, update_service_response = (
                self.target_access.dispatch_request(
                    "GET", "/redfish/v1/UpdateService", None, json_prints=json_dict
                )
            )
            if (update_service_status is False) or (
                update_service_response["ServiceEnabled"] is False
            ):
                Util.bail_nvfwupd_threadsafe(
                    1,
                    "UpdateService is not enabled in the system",
                    Util.BailAction.PRINT_DIVIDER,
                    print_json=json_dict,
                    parallel_update=parallel_update,
                )
                return None
            # Update the required update URI
            update_uri = update_service_response.get(
                "MultipartHttpPushUri", "/redfish/v1/UpdateService"
            )

            # Multipart Update
            task_id = ""
            if param_list is not None and self.validate_json(param_list):
                task_id = super().update_component_multipart(
                    None,
                    update_uri,
                    update_file,
                    time_out,
                    param_list,
                    json_dict,
                    parallel_update=parallel_update,
                )
            else:
                task_id = super().update_component_multipart(
                    param_list,
                    update_uri,
                    update_file,
                    time_out,
                    None,
                    json_dict,
                    parallel_update=parallel_update,
                )

        return task_id


class MGXNVLRFTarget(HGXB100RFTarget):
    """
    Class to implement FW update related Redfish APIs for MGX-NVL
    based on configured behavior
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
    is_fungible_component(component_name) :
        Determines if a component is fungible for a given system
    update_component(cmd_args, update_uri, update_file, time_out,
                        json_dict=None, parallel_update=False) :
        Update a firmware component or target system
    """

    def __init__(self, dut_access):
        """
        MGX NVL Redfish Target Class Constructor
        Parameter:
            dut_access Initialized DUT access class to reach the target
        """
        super().__init__(dut_access)
        self.target_access = dut_access
        self.fungible_components = ["gpu"]
        self.update_completion_msg = (
            "Refer to Firmware Update Document on "
            + "activation steps for new firmware to take effect."
        )

    def is_fungible_component(self, component_name):
        """
        Fungible component for MGX-NVL
        Parameters:
            component_name The string name of the component
        Returns:
            True if the component is fungible or
            False if the component is not fungible
        """
        if any(map(component_name.__contains__, self.fungible_components)) and not any(
            map(component_name.__contains__, ["inforom", "erot"])
        ):
            return True
        return False

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def update_component(
        self,
        cmd_args,
        update_uri,
        update_file,
        time_out,
        json_dict=None,
        parallel_update=False,
    ):
        """
        Method to perform FW update using redfish request for MGX-NVL Platforms
        Parameters:
            cmd_args Parsed input command arguments
            update_uri Target Redfish URI used for the update
            update_file File used for the update
            time_out Timeout period in seconds for the requests
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        Returns:
            Task ID of the update task or
            None if there was a failure
        """
        special_targets = ""
        task_id = ""
        param_list = cmd_args.special
        if param_list is not None:
            if self.validate_json(param_list):
                special_targets = param_list
            else:
                try:
                    with open(param_list[0], "r", encoding="utf-8") as params_file:
                        special_targets = params_file.read()
                except IOError as e_io_error:
                    Util.bail_nvfwupd_threadsafe(
                        1,
                        f"Failed to open or read given file {param_list[0]} "
                        + f"error: ({e_io_error})",
                        print_json=json_dict,
                        parallel_update=parallel_update,
                    )
                    return None
            status, err_dict = self.target_access.dispatch_request(
                "PATCH",
                "/redfish/v1/UpdateService",
                param_data=special_targets,
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
