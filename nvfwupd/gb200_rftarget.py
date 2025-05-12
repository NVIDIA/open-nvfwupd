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
"""Class that defines update related behavior for GB200"""
import re
import os
import json
from nvfwupd.base_rftarget import BaseRFTarget
from nvfwupd.utils import Util


class GB200RFTarget(BaseRFTarget):
    """
    Class to implement FW update related Redfish APIs for GB200
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
    get_update_uri(update_service_response) :
        Acquire the update URI from the Redfish update service
    update_component(cmd_args, update_uri, update_file, time_out,
                         json_dict=None, parallel_update=False) :
        Update a firmware component or target system
    is_fungible_component(component_name) :
        Determines if a component is fungible for a given system
    version_newer(pkg_version, sys_version) :
        Determines if package or system firmware version is newer
    get_identifier_from_chassis(ap_inv_uri) :
        Acquire a component's unique identifier for comparison
    get_model_from_chassis(ap_name) :
        Acquire a component's model for comparison
    get_version_sku(identifier, pldm_version_dict, ap_name)
        Acquire a package version for a component with given identifier
    """

    def __init__(self, dut_access):
        """
        GB200 Redfish Target Constructor
        Parameter:
            dut_access Initialized DUT access class to reach the target
        """
        super().__init__(dut_access)
        self.target_access = dut_access
        self.fungible_components = ["gpu"]
        self.update_completion_msg = (
            "Refer to 'NVIDIA Firmware Update Document' on "
            + "activation steps for new firmware to take effect."
        )

    def get_update_uri(self, update_service_response):
        """
        get update URI from update service
        Parameter:
            update_service_response Dictionary of Redfish Update service response
        Returns:
            URI of the update service
        """
        return update_service_response.get(
            "MultipartHttpPushUri", "/redfish/v1/UpdateService"
        )

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
        Method to perform FW update using mutipart redfish request for GB200
        returns task id
        Parameters:
            cmd_args Parsed input command arguments
            update_uri Target Redfish URI used for the update
            update_file File used for the update
            time_out Timeout period in seconds for the requests
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            parallel_updates Boolean value, True if doing a parallel update
        Returns:
            Task ID of the update task
        """

        # cmd_args.special - User passed in JSON Update Parameters or file with Update Parameters
        param_list = cmd_args.special

        # Check if special update file was provided
        if param_list is None:
            file_name = os.path.basename(update_file)
            hgx_platforms = ["P4059", "P4764", "P4974", "P4975", "HGX"]
            if next(
                (platform for platform in hgx_platforms if platform in file_name), None
            ):
                # GPU Tray Update
                json_params = {"Targets": ["/redfish/v1/Chassis/HGX_Chassis_0"]}
            else:
                # BMC Tray Update
                json_params = {"Targets": []}
            param_list = json.dumps(json_params)

        # Set Staged Update Parameters
        if cmd_args.staged_update or cmd_args.staged_activate_update:
            # read in params and append the OEM options
            if param_list is not None and self.validate_json(param_list):
                json_data = json.loads(param_list)
            elif param_list is not None and os.path.isfile(param_list[0]):
                try:
                    with open(param_list[0], "r", encoding="utf-8") as file:
                        json_data = json.load(file)
                except json.JSONDecodeError:
                    Util.bail_nvfwupd(
                        1,
                        "Error: Invalid JSON special update file",
                        Util.BailAction.DO_NOTHING,
                        print_json=json_dict,
                    )

            # Add the OEM parameters for staging
            if cmd_args.staged_update:
                json_data["Oem"] = {"Nvidia": {"UpdateOption": "StageOnly"}}
            elif cmd_args.staged_activate_update:
                json_data["Oem"] = {"Nvidia": {"UpdateOption": "StageAndActivate"}}
            param_list = json.dumps(json_data)

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

    def is_fungible_component(self, component_name):
        """
        Fungible components for GB 200
        Parameters:
            component_name String name of the component
        Returns:
            True if the component is fungible,
            False if the component is not fungible
        """
        # Special Handling required for BMC Tray CPLD
        if "cpld" in component_name and "hgx" not in component_name:
            return True
        if any(map(component_name.__contains__, self.fungible_components)) and not any(
            map(component_name.__contains__, ["inforom", "erot"])
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
        regex = re.compile("[a-zA-Z0-9]*GH[a-zA-Z0-9]*[_|-]", re.IGNORECASE)
        match_sys = regex.match(sys_version)
        match_pkg = regex.match(pkg_version)
        # process sys version if sys format does not match pkg format
        if match_sys and not match_pkg:
            sys_version = regex.sub("", sys_version, 1)
            end_match = re.search("-[a-zA-Z]+", sys_version)
            if end_match is not None:
                sys_version = sys_version[: end_match.start()]
        return super().version_newer(pkg_version, sys_version)

    def get_identifier_from_chassis(self, ap_inv_uri):
        """
        Get Redfish Chassis uri for getting sku id
        Parameter:
            ap_inv_uri The Redfish inventory URI for a component
        Returns:
            SKU ID value for the given URI or
            None if there was an error or SKU is not available
        """
        ap_name = ap_inv_uri.rsplit("/", 1)[-1]
        if "cpld" in ap_name.lower():
            return self.get_model_from_chassis(ap_name)

        sku_id = None
        status, fw_inv_dict = self.target_access.dispatch_request(
            "GET", ap_inv_uri, None, suppress_err=True
        )
        if status is True:
            try:
                chassis_uri = fw_inv_dict.get("RelatedItem")[0]["@odata.id"]
            except (KeyError, IndexError, TypeError):
                return sku_id
            status, chassis_dict = self.target_access.dispatch_request(
                "GET", chassis_uri, None
            )
            if status is True:
                sku_id = chassis_dict.get("SKU")
        return sku_id

    def get_model_from_chassis(self, ap_name):
        """
        Get Redfish Chassis uri for getting CPLD model
        Parameter:
            ap_name A component string name
        Returns:
            Model string for the given component or
            None if there was an error or Model is not available
        """
        ap_chassis = ap_name.replace("FW_", "")
        status, cpld_dict = self.target_access.dispatch_request(
            "GET", "/redfish/v1/Chassis/" + ap_chassis, None, suppress_err=True
        )
        if status is False or cpld_dict is None:
            self.target_access.dut_logger.cli_log(
                f"Chassis URI failed to return: {ap_name}", log_file_only=True
            )
            return None
        model = cpld_dict.get("Model")
        if model is None:
            self.target_access.dut_logger.cli_log(
                f"CPLD Model not present: {ap_name}", log_file_only=True
            )

        if model == "BP":
            # Redfish model is shortened as BP
            # Metadata spells this out fully, adjust to match
            model = "Backplane"
        return model

    def get_version_sku(self, identifier, pldm_version_dict, ap_name):
        """
        Get pkg version for gpu with matching sku_id
        Parameters:
            identifier A string identifier used to match a package component
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name Unused
        Returns:
            Pkg version for a GPU or CPLD with matching identifier or
            N/A if not found
        """
        for _, pkg_dict in pldm_version_dict.items():
            for pkg_ap, pkg_data in pkg_dict.items():
                if "gpu" in pkg_ap.lower():
                    if pkg_data[1] == identifier:
                        return pkg_data[0]
                if "cpld" in pkg_ap.lower():
                    if identifier.lower() in pkg_ap.lower():
                        return pkg_data[0]
        return "N/A"
