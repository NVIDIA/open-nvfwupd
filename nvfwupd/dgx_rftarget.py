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
"""Class that defines update related RF APIs for all DGX variants"""

import json
import os
from nvfwupd.rf_target import RFTarget
from nvfwupd.utils import Util


# pylint: disable=invalid-name
class DGX_RFTarget(RFTarget):
    """
    Class to implement FW update related Redfish APIs specifically for DGX platforms
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
    get_version_sku(identifier, pldm_version_dict, ap_name) :
        Get a component package version based on device sku
    get_update_uri(update_service_response) :
        Acquire the update URI from the Redfish update service
    get_component_version(pldm_version_dict, ap_name) :
        Get a component version from a pldm dictionary
    get_identifier_from_chassis(ap_inv_uri) :
        Get a component identifier from the chassis uri
    get_sku_from_chassis(ap_name) :
        Acquire component sku from Chassis URI for given component
    get_partno_from_chassis(ap_name) :
        Acquire PSU part number from Chassis PowerSupplies URI

    """

    def __init__(self, dut_access):
        """
        DGX Redfish Target Constructor
        Parameter:
            dut_access Initialized DUT access class to reach the target
        """
        super().__init__()
        self.target_access = dut_access
        self.fungible_components = ["gpu", "psu"]
        self.update_completion_msg = (
            "Refer to the 'DGX Firmware Update Document' for"
            + " the specific model on activation steps for new"
            + " firmware to take effect."
        )

    def is_fungible_component(self, component_name):
        """
        Method to check if a component is fungible
        Parameter:
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
        Method to perform FW update using redfish request for DGX platforms
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
        task_id = ""
        status = False
        response_dict = None

        # cmd_args.special - User passed in JSON Update Parameters or file with Update Parameters
        param_list = cmd_args.special

        # Check if special update file was provided
        if param_list is None:
            file_name = os.path.basename(update_file)
            hgx_platforms = ["HGX"]
            if next(
                (platform for platform in hgx_platforms if platform in file_name), None
            ):
                # GPU Tray Update (wrapper bundle)
                json_params = {
                    "Targets": ["/redfish/v1/UpdateService/FirmwareInventory/HGX_0"]
                }
            else:
                # MB Tray Update
                json_params = {}
            param_list = json.dumps(json_params)

        if param_list is not None and os.path.isfile(param_list[0]):
            status, response_dict = self.target_access.multipart_file_upload(
                url=update_uri,
                pkg_file=update_file,
                upd_params_file=param_list[0],
                time_out=time_out,
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
        elif param_list is not None and self.validate_json(param_list):
            status, response_dict = self.target_access.multipart_file_upload(
                url=update_uri,
                pkg_file=update_file,
                upd_params_file=None,
                time_out=time_out,
                updparams_json=param_list,
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

    def get_version_sku(self, identifier, pldm_version_dict, ap_name):
        """
        Get pkg version for component with matching sku_id
        Parameters:
            identifier A string identifier used to match a package component
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name The name of a component
        Returns:
            Pkg version for a component with matching identifier or
            N/A if not found
        """
        pkg_version = "N/A"
        for pkg, pkg_dict in pldm_version_dict.items():
            if "HGX" not in pkg and "gpu" in ap_name:
                pkg_version = "N/A"
                continue
            for pkg_ap, pkg_data in pkg_dict.items():
                if "gpu" in pkg_ap.lower():
                    if pkg_data[1] == identifier:
                        return pkg_data[0]
                if "psu" in pkg_ap.lower():
                    if identifier.lower() in pkg_ap.lower():
                        return pkg_data[0]
        return pkg_version

    def get_update_uri(self, update_service_response):
        """
        Get the URI of the update service
        Parameter:
            update_service_response Dictionary of Redfish Update service response
        Returns:
            URI of the update service
        """
        return update_service_response.get(
            "MultipartHttpPushUri", "/redfish/v1/UpdateService"
        )

    def get_component_version(self, pldm_version_dict, ap_name):
        """
        Get component version by AP name matching
        Parameters:
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name The name of a component
        Returns:
            Component version or
            N/A if not found
        """
        # pylint: disable=too-many-branches
        ap_version = "N/A"
        hgx_pkg_only = False
        if ap_name.find("hgx_fw_") == 0:
            ap_name = ap_name[len("hgx_fw_") :]
            hgx_pkg_only = True
            if ap_name.startswith("bmc"):
                ap_name = "hmc"
        if ap_name.startswith("erot"):
            ap_name = "erot"
        if "gpu" in ap_name and "inforom" not in ap_name:
            return ap_version
        if "bios" in ap_name:
            ap_name = "sbios"
        elif "bmc" in ap_name:
            ap_name = "bmc"
        elif "nvlink" in ap_name:
            ap_name = "cx7"
        elif "cx7nic" in ap_name:
            ap_name = "bluefield3"
        ap_name = ap_name.replace("_", "")
        for pkg, pkg_dict in pldm_version_dict.items():
            if hgx_pkg_only and "HGX" not in pkg:
                continue
            if not hgx_pkg_only and "HGX" in pkg:
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
                if not hgx_pkg_only and (
                    "pcieretimer" in ap_pkg or "pcieswitch" in ap_pkg
                ):
                    if ap_pkg == ap_name:
                        ap_version = pkg_version[0]
                    else:
                        alt_ap = ap_pkg + "0"
                        if alt_ap == ap_name:
                            ap_version = pkg_version[0]
        return ap_version

    def get_identifier_from_chassis(self, ap_inv_uri):
        """
        Parameter:
            ap_inv_uri The inventory URI for a component
        Returns:
            Part number for PSU or
            Sku for another fungible component type
        """
        ap_name = ap_inv_uri.rsplit("/", 1)[-1]
        if "psu" in ap_name.lower():
            return self.get_partno_from_chassis(ap_name)
        return self.get_sku_from_chassis(ap_name)

    def get_sku_from_chassis(self, ap_name):
        """
        Get Redfish Chassis uri for getting sku id
        Parameter:
            ap_name The name of a component
        Returns:
            SKU value for the provided component or
            None if there is an error
        """
        ap_chassis = ap_name.replace("FW_", "")
        status, gpu_dict = self.target_access.dispatch_request(
            "GET", "/redfish/v1/Chassis/" + ap_chassis, None, suppress_err=True
        )
        if status is False or gpu_dict is None:
            return None
        gpu_sku = gpu_dict.get("SKU")
        return gpu_sku

    def get_partno_from_chassis(self, ap_name):
        """
        Get Redfish Chassis uri for getting PSU part number
        Parameter:
            ap_name The name of a component
        Returns:
            Component Part Number or
            None if not available or there is an error
        """
        ap_chassis = ap_name.replace("FW_", "")
        ap_chassis = ap_name.replace("_", "")
        status, psu_dict = self.target_access.dispatch_request(
            "GET",
            "/redfish/v1/Chassis/DGX/PowerSubsystem/PowerSupplies/" + ap_chassis,
            None,
            suppress_err=True,
        )
        if status is False or psu_dict is None:
            self.target_access.dut_logger.cli_log(
                f"DGX PowerSupplies URI failed to return: {ap_name}", log_file_only=True
            )
            return None
        part_num = psu_dict.get("PartNumber")
        if part_num is None:
            self.target_access.dut_logger.cli_log(
                f"DGX PSU PartNumber not present: {ap_name}", log_file_only=True
            )
        return part_num
