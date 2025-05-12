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

"""Class that defines update related RF APIs for Redfish platforms"""

import re
from nvfwupd.utils import Util
from nvfwupd.rf_target import RFTarget


class BaseRFTarget(RFTarget):
    """Class to implement specific FW update related Redfish APIs inherited
    by other Redfish based Platforms
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
    version_newer(pkg_version, sys_version) :
        Determines if package or system firmware version is newer
    update_component(cmd_args, update_uri, update_file, time_out,
                         json_dict=None, parallel_update=False) :
        Update a firmware component or target system
    is_fungible_component(component_name) :
        Determines if a component is fungible for a given system
    is_hgx_pkg(pkg_name) :
        Determines if a package is an HGX package (Compute Tray)
    get_component_version(pldm_version_dict, ap_name) :
        Get a component version from a pldm dictionary
    get_identifier_from_chassis(ap_inv_uri) :
        Get a component identifier from the chassis uri
    get_version_sku(identifier, pldm_version_dict, ap_name) :
        Get a component package version based on device sku
    get_sku_from_chassis(ap_name) :
        Acquire component SKU from the Chassis URI
    """

    def __init__(self, dut_access):
        """
        Contructor for BaseRFTarget class
        Parameter:
            dut_access Initialized access class to the DUT
        """
        super().__init__()
        self.target_access = dut_access
        self.fungible_components = ["gpu"]
        self.update_completion_msg = (
            "Refer to 'NVIDIA Firmware Update Document' on "
            + "activation steps for new firmware to take effect."
        )

    def version_newer(self, pkg_version, sys_version):
        """
        Check if the package version is newer than the system version.
        Parameters:
            pkg_version Package version for a component
            sys_version Running system version for a component
        Returns:
            True if pkg version is > system version
            False otherwise
        """
        if sys_version.find(".") == -1:
            pkg_version = pkg_version.replace(".", "")
        regex = re.compile("GraceBMC[_|-]", re.IGNORECASE)
        match = regex.match(sys_version)
        if match:
            sys_version = regex.sub("", sys_version, 1)
            end_match = re.search("-[a-zA-Z]+", sys_version)
            if end_match is not None:
                sys_version = sys_version[: end_match.start()]
        return super().version_newer(pkg_version, sys_version)

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
        Method to perform FW update using redfish requests
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
        # cmd_args.special - User passed in JSON Update Parameters or file with Update Parameters
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

    def is_fungible_component(self, component_name):
        """
        return True if gpu and not erot_gpu or inforom_gpu
        Parameter:
            component_name The string name of the component
        Returns:
            True if the component is fungible or
            False if the component is not fungible
        """
        if "gpu" in component_name and "hgx" in component_name:
            if not any(map(component_name.__contains__, ["inforom", "erot"])):
                return True
        return False

    def is_hgx_pkg(self, pkg_name):
        """
        Check if pkg is for the HGX tray
        Parameter:
            pkg_name The string name of the passed in package
        Returns:
            True if the package is an HGX package or
            False if the package is not an HGX package
        """
        hgx_platforms = ["HGX", "4059", "4764", "4974", "4975", "MGX-NVL16"]
        if next((platform for platform in hgx_platforms if platform in pkg_name), None):
            return True
        return False

    def get_component_version(self, pldm_version_dict, ap_name):
        """
        Get matching component version from PLDM dict for given ap
        Parameters:
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name The string name of a component
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
        elif not hgx_pkg_only and "pcie" in ap_name:
            ap_name = "pcieswitch"
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

    def get_identifier_from_chassis(self, ap_inv_uri):
        """
        Get Redfish Chassis uri for getting sku id
        Parameter:
            ap_inv_uri The Redfish inventory URI for a component
        Returns:
            SKU ID value for the given URI or
            None if there was an error or SKU is not available
        """
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

    def get_version_sku(self, identifier, pldm_version_dict, ap_name):
        """
        Get pkg version for gpu with matching sku_id
        Parameters:
            identifier A string identifier used to match a package component
            pldm_version_dict A dictionary of package names alongside
            their contained component information
            ap_name Unused
        Returns:
            Pkg version for a GPU with matching sku ID or
            N/A if not found
        """
        for _, pkg_dict in pldm_version_dict.items():
            for pkg_ap, pkg_data in pkg_dict.items():
                if "gpu" in pkg_ap.lower():
                    if pkg_data[1] == identifier:
                        return pkg_data[0]
        return "N/A"

    def get_sku_from_chassis(self, ap_name):
        """
        Get Redfish Chassis uri for getting sku id
        Parameter:
            ap_name The string name of a component
        Returns:
            GPU SKU if available for the component name or
            None if not available
        """
        ap_chassis = ap_name.replace("FW_", "")
        status, gpu_dict = self.target_access.dispatch_request(
            "GET", "/redfish/v1/Chassis/" + ap_chassis, None, suppress_err=True
        )
        if status is False or gpu_dict is None:
            return None
        gpu_sku = gpu_dict.get("SKU")
        return gpu_sku
