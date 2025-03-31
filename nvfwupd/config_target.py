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
"""Class that defines update related RF APIs that can be called using config YAML"""

import json
import re
from nvfwupd.rf_target import RFTarget
from nvfwupd.base_rftarget import BaseRFTarget
from nvfwupd.dgx_rftarget import DGX_RFTarget
from nvfwupd.gb200_rftarget import GB200RFTarget
from nvfwupd.gb200_switch_target import GB200SwitchTarget
from nvfwupd.hgxb100_rftarget import HGXB100RFTarget, MGXNVLRFTarget
from nvfwupd.utils import Util


class ConfigTarget(RFTarget):
    """Class to implement FW update related Redfish APIs based on configured behavior
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
    config_platform_target : RFTarget
        Target class used for communication to specific platform type

    Methods
    -------
    init_platform_obj(json_dict=None) :
        Acquire the platform type from the yaml config file and initialize the
        config_platform_target with the related target class
    is_fungible_component(component_name) :
        Determines if a component is fungible for a given system
    get_component_version(pldm_version_dict, ap_name) :
        Get a component version from a pldm dictionary
    get_identifier_from_chassis(ap_inv_uri) :
        Get a component identifier from the chassis uri
    get_version_sku(identifier, pldm_version_dict, ap_name) :
        Get a component package version based on device sku
    version_newer(pkg_version, sys_version) :
        Determines if package or system firmware version is newer
    get_update_uri(update_service_response) :
        Acquire the update URI from the Redfish update service
    get_task_service_uri(task_id) :
        Acquire the task service URI from Redfish for task monitoring
    update_component(param_list, update_uri, update_file, time_out,
                         json_dict=None, parallel_update=False) :
        Update a firmware component or target system
    start_update_monitor(recipe_list, pkg_parser, cmd_args, time_out,
                             parallel_update, json_dict=None) :
        Begin an update an monitor it using the configuration target
    process_job_status(task_id, print_json=None) :
        Acquire task status for a given task id

    """

    def __init__(self, dut_access, config_dict, print_json=None):
        """
        Contructor for ConfigTarget class
        Parameters:
            dut_access Initialized DUT access class to reach the target
            config_dict A configuration dictionary with target information
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        """
        super().__init__()
        self.target_access = dut_access
        self.fungible_components = []
        self.update_completion_msg = (
            "Update successful. "
            + "Perform activation steps for new firmware to take effect."
        )
        self.config_dict = config_dict
        self.config_platform_target = None
        self.init_platform_obj(print_json)

    def init_platform_obj(self, json_dict=None):
        """
        Get platform type from config file and initialize config_platform_target
        Parameter:
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        """
        target_platform = self.config_dict.get("TargetPlatform")

        # Remove brackets for comparison if IPv6
        test_ip = re.sub(r"\[|\]", "", self.target_access.m_ip)

        if target_platform is None:
            # try the targets array used for parallel update
            targets_array = self.config_dict.get("Targets")
            if targets_array is not None:
                for target in targets_array:
                    if test_ip == target["BMC_IP"]:
                        target_platform = target.get("TARGET_PLATFORM", None)
                        break

        if target_platform is not None and isinstance(target_platform, str):
            target_platform = target_platform.lower()

        if target_platform == "hgx":
            self.config_platform_target = BaseRFTarget(self.target_access)
        elif target_platform == "hgxb100":
            self.config_platform_target = HGXB100RFTarget(self.target_access)
        elif target_platform == "mgx-nvl":
            self.config_platform_target = MGXNVLRFTarget(self.target_access)
        elif target_platform == "dgx":
            self.config_platform_target = DGX_RFTarget(self.target_access)
        elif target_platform == "gb200":
            self.config_platform_target = GB200RFTarget(self.target_access)
        elif target_platform == "gb200switch":
            self.config_platform_target = GB200SwitchTarget(self.target_access)
        elif target_platform is not None:
            Util.bail_nvfwupd(
                1,
                f"TargetPlatform {target_platform} is not supported",
                print_json=json_dict,
            )

    def is_fungible_component(self, component_name) -> bool:
        """
        check if given component is fungible on the target
        Parameter:
            component_name String name of a component
        Returns:
            True if the given component is fungible or
            False if the component is not fungible
        """
        if self.config_platform_target:
            return self.config_platform_target.is_fungible_component(component_name)
        return False

    def get_component_version(self, pldm_version_dict, ap_name) -> str:
        """
        get version of ap in PLDM
        Parameters:
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name String name of a component
        Returns:
            Component version if found in the bundle or
            N/A if not found in the bundle
        """
        if self.config_platform_target:
            return self.config_platform_target.get_component_version(
                pldm_version_dict, ap_name
            )
        return "N/A"

    def get_identifier_from_chassis(self, ap_inv_uri) -> str:
        """
        get AP identifier from Chassis response
        Parameter:
            ap_inv_uri The inventory URI for a component
        Returns:
            Component Identifier if available or
            None if not found
        """
        if self.config_platform_target:
            return self.config_platform_target.get_identifier_from_chassis(ap_inv_uri)
        return None

    def get_version_sku(self, identifier, pldm_version_dict, ap_name) -> str:
        """
        get version from pldm for given identifier
        Parameters:
            identifier A string for distinguishing a component in the package
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name The string name of a component
        Returns:
            SKU specific component version from package or
            N/A if not found in the package
        """
        if self.config_platform_target:
            return self.config_platform_target.get_version_sku(
                identifier, pldm_version_dict, ap_name
            )
        return "N/A"

    def version_newer(self, pkg_version, sys_version) -> bool:
        """
        Check if a component package version is newer than a running system version
        Parameters:
            pkg_version A component package version
            sys_version The running system version of a component
        Returns:
            True if the component package version is newer or
            False if the running component system version is newer
        """
        if self.config_platform_target:
            return self.config_platform_target.version_newer(pkg_version, sys_version)
        return False

    def get_update_uri(self, update_service_response) -> str:
        """
        get update URI from update service
        Parameter:
            update_service_response Dictionary of Redfish Update service response
        Returns:
            Update URI from the Redfish Update Service
        """
        update_uri = ""
        if self.config_dict.get("FwUpdateMethod", "") == "HttpPushUri":
            update_uri = self.config_dict.get(
                "HttpPushUri", "/redfish/v1/UpdateService"
            )
        elif self.config_dict.get("FwUpdateMethod", "") == "MultipartHttpPushUri":
            system_uri = update_service_response.get(
                "MultipartHttpPushUri", "/redfish/v1/UpdateService"
            )
            # If config file has multipart URI use that, otherwise the one from UpdateService
            update_uri = self.config_dict.get("MultipartHttpPushUri", system_uri)
        elif self.config_platform_target:
            update_uri = self.config_platform_target.get_update_uri(
                update_service_response
            )
        self.target_access.dut_logger.debug_print(f"Using update URI {update_uri}")
        return update_uri

    def get_task_service_uri(self, task_id):
        """
        get URI for task monitoring
        Parameters:
            task_id The task id of an ongoing or finished task
        Returns:
            Redfish Task URI for the given Task ID
        """
        task_uri = "/redfish/v1/TaskService/Tasks/"
        if self.config_dict.get("TaskServiceUri", "") != "":
            task_uri = self.config_dict.get("TaskServiceUri", "")
        task_uri = re.sub(r"/+", "/", f"{task_uri}/{task_id}")
        return task_uri

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
    ) -> str:
        """
        check update config param and call multipart update or http push uri
        read update targets param list from the config into a json
        Parameters:
            param_list List of special parameters used for the update
            update_uri Target URI used for the update
            update_file File used for the update
            time_out Timeout period in seconds for the requests
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        Returns:
            Task ID of the launched update
        """
        task_id = ""
        upd_params_config = self.config_dict.get("UpdateParametersTargets")
        update_method = self.config_dict.get("FwUpdateMethod", "")
        if update_method == "HttpPushUri":
            params_json = None
            if upd_params_config is not None:
                updparams_dict = {"HttpPushUriTargets": upd_params_config}
                if upd_params_config is not None and isinstance(
                    upd_params_config, dict
                ):
                    updparams_dict = {}
                params_json = json.dumps(updparams_dict)
            task_id = super().update_component_pushuri(
                params_json,
                update_uri,
                update_file,
                time_out,
                json_dict,
                parallel_update=parallel_update,
            )
        elif update_method == "MultipartHttpPushUri":
            params_json = None
            updparams_dict = {}
            if self.config_dict.get("MultipartOptions"):
                updparams_dict = self.config_dict.get("MultipartOptions")
                params_json = json.dumps(updparams_dict)
            if upd_params_config is not None:
                updparams_dict["Targets"] = upd_params_config
                if upd_params_config is not None and isinstance(
                    upd_params_config, dict
                ):
                    updparams_dict = {}
                params_json = json.dumps(updparams_dict)
            task_id = super().update_component_multipart(
                None,
                update_uri,
                update_file,
                time_out,
                params_json,
                json_dict=json_dict,
                parallel_update=parallel_update,
            )
        elif self.config_platform_target:
            task_id = self.config_platform_target.update_component(
                param_list,
                update_uri,
                update_file,
                time_out,
                json_dict=json_dict,
                parallel_update=parallel_update,
            )
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
        Method to start update monitor with config target
        Parameters:
            recipe_list A list of update packages
            pkg_parser An initialized package parser class
            cmd_args Parsed input command arguments
            time_out Timeout period in seconds for the requests
            parallel_update Boolean value, True if doing a parallel update
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            Result of the update_monitor
        """
        # Call the config platform targets update monitor for targets with their own defined
        # Otherwise, call the super version which will handle config targets
        if isinstance(self.config_platform_target, GB200SwitchTarget):
            return self.config_platform_target.start_update_monitor(
                recipe_list,
                pkg_parser,
                cmd_args,
                time_out,
                parallel_update,
                json_dict=json_dict,
            )

        return super().start_update_monitor(
            recipe_list,
            pkg_parser,
            cmd_args,
            time_out,
            parallel_update,
            json_dict=json_dict,
        )

    def process_job_status(self, task_id, print_json=None):
        """
        Method to process job status with config target
        Parameters:
            task_id The task id of an ongoing update
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            Result of the job status
        """
        return self.config_platform_target.process_job_status(
            task_id, print_json=print_json
        )
