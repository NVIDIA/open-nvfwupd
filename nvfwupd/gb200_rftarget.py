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
from nvfwupd.base_rftarget import BaseRFTarget


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
    update_component(param_list, update_uri, update_file, time_out,
                         json_dict=None, parallel_update=False) :
        Update a firmware component or target system
    is_fungible_component(component_name) :
        Determines if a component is fungible for a given system
    version_newer(pkg_version, sys_version) :
        Determines if package or system firmware version is newer

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
        param_list,
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
            param_list List or file of special parameters used for the update
            update_uri Target Redfish URI used for the update
            update_file File used for the update
            time_out Timeout period in seconds for the requests
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            parallel_updates Boolean value, True if doing a parallel update
        Returns:
            Task ID of the update task
        """

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
