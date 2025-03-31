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
Provide interface to query firmware recipe from PLDM firmware package.
This module calls pldm_parse on the given PLDM package files, stores
firmware device information in YAML to a dictionary encapsulated in
PLDM object.
"""

import json
import os
import shutil
import tarfile
import tempfile
import threading
from nvfwupd.utils import Util
from nvfwupd.deps.fwpkg_unpack import PLDMUnpack


class FirmwarePkg:
    """
    The tool supports PLDM FW package and a tar FW pkg
    This is the base class that declares parsing related methods
    that must be implemented to validate and get AP and version information
    from each package
    ...
    Attributes
    ----------
    apname_version_dict : dict
        Dictionary for storing package metadata
    verbose : bool
        True if verbose logging is enabled

    Methods
    -------
    parse_pkg(_, json_dict=None) :
        Validate and parse package contents into a dictionary
    remove_files() :
        Delete extra files used during package parsing
    get_pkg_parser(file_path, verbose) :
        Identify the provided file type and create an appropriate
        parser object

    """

    def __init__(self):
        """
        Firmware Package Class Constructor
        """
        self.apname_version_dict = {}
        self.verbose = False

    def parse_pkg(self, _, json_dict=None):
        """
        package must be validated and contents parsed into apname_version_dict
        To be implemented by each of the child classes
        """
        return False, ""

    def remove_files(self):
        """
        Cleanup method if the parser needs to delete
        unpacked files after tool usage
        """
        return

    @staticmethod
    def get_pkg_parser(file_path, verbose):
        """
        Static method to identify file type and create
        appropriate parser object
        Parameters:
            file_path File path of a package file
            verbose Boolean value for setting verbose logging
        Returns:
            PLDM or TarPkg parser
        """
        pkg_parser = PLDM()
        if tarfile.is_tarfile(file_path):
            pkg_parser = TarPkg()
        pkg_parser.verbose = verbose
        return pkg_parser


class TarPkg(FirmwarePkg):
    """
    This class implements validations and parsing
    methods for tar files
    ...
    Attributes
    ----------
    apname_version_dict : dict
        Dictionary for storing package metadata
    verbose : bool
        True if verbose logging is enabled
    untar_file_path : str
        Path to extract tar file to

    Methods
    -------
    parse_pkg(package_name, json_dict=None) :
        Validates the tar file as valid, extracts
        files and creates a dictionary of metadata
        for apname_version_dict
    remove_files() :
        Delete extracted files that are no longer needed
    validate_json(json_data) :
        Validate that the fwlist.json file provided is valid
    parse_json_file(file_path) :
        Parse fwlist.json file and populate additional metadata
    """

    def __init__(self):
        """
        Tarfile Package Class Constructor
        """
        super().__init__()
        self.untar_file_path = ""

    def parse_pkg(self, package_name, json_dict=None):
        """
        Validates tar file, extracts all files and
        creates metadata dict in apname_version_dict
        Parameters:
            package_name File path of a tar file
            json_dict Unused
        Returns:
            True and an empty string if the tar package is valid,
            False and an error message if the tar package is not valid
        """
        dirpath = tempfile.mkdtemp("nvfwupd")
        tar_file = tarfile.open(package_name)
        file_list = tar_file.getnames()
        valid_tar = False
        json_path = ""
        err_msg = "Invalid tar file"
        for each_file in file_list:
            name = each_file.rsplit("/", 1)[-1]
            if name == "fwlist.json":
                valid_tar = True
                json_path = each_file
                break
        if valid_tar:
            tar_file.extractall(dirpath)
            tar_file.close()
            valid_tar, err_msg = self.parse_json_file(f"{dirpath}/{json_path}")
            self.untar_file_path = (
                os.path.abspath(os.path.dirname(f"{dirpath}/{json_path}")) + "/"
            )
        return valid_tar, err_msg

    def remove_files(self):
        """
        Method to clear extracted files that must be removed after use
        """
        if self.untar_file_path != "":
            shutil.rmtree(self.untar_file_path, ignore_errors=True)

    def validate_json(self, json_data):
        """
        Input tar file is expected to have a fwlist.json file in following
        format
        Parameters:
            json_data fwlist.json File in a dict form
        Returns:
            True if all required fields are present,
            False if not all required fields are present
        """
        required_fields = ["FW-ID", "Components"]
        for field in required_fields:
            if field not in json_data or not json_data[field]:
                return False
        return True

    def parse_json_file(self, file_path):
        """
        Method to parse data from fwlist.json and populate apname_version_dict
        Parameter:
            file_path File path of the fwlist.json file
        Returns:
            True, empty error message if the json file can be parsed,
            False, error message if there is an error during parsing
        """
        status = False
        error_msg = ""
        with open(file_path, "r", encoding="utf-8") as file:
            try:
                json_data = json.load(file)
                if self.validate_json(json_data):
                    components = json_data["Components"]
                    self.apname_version_dict[file_path] = components
                    status = True
                else:
                    error_msg = "Invalid JSON data. Missing or empty field(s)."
            except json.JSONDecodeError as err:
                error_msg = "Error decoding JSON file: ", str(err)
        return status, error_msg


class PLDM(FirmwarePkg):
    """
    Class implements PLDM package firmware device information
    retrieval.
    ...
    Attributes
    ----------
    apname_version_dict : dict
        Dictionary for storing package metadata
    verbose : bool
        True if verbose logging is enabled
    m_pldm_dict : dict
        Dictionary storing PLDM package and firmware metadata
        parsed from the PLDM parser
    unpack_file_ap_dict : dict
        Dictionary storing metadata from unpacking the PLDM file
    unpack_dirpath : str
        Filepath to unpack a firmware package to

    Methods
    -------
    parse_pkg(package_name, json_dict=None) :
        Parse a PLDM package and create a dictionary of
        the package contents
    unpack_pkg(package_name, out_dir='./', unpack=False) :
        Unpack a PLDM package and prepare records metadata
    get_ap_sku(records, ap_name) :
        Acquire VendorDefinedDescriptorData SKU for a given
        component
    add_apname_version(pldm) :
        Create a version dictionary for a package name that
        contains its component name, version, and sku
    get_unpack_file_dict(pkg_name) :
        Create a dictionary for a package name that contains
        the componennt name, component version, and unpacked
        update file path
    remove_files() :
        Delete extra extracted files
    print_package(package_name) :
        Print the PLDM package data in JSON format
    """

    def __init__(self):
        """
        Contructor for PLDM class
        """
        super().__init__()
        self.m_pldm_dict = {}  # Dictionary of PLDM packages with firmware device info
        # output from pldm parser.
        self.unpack_file_ap_dict = {}
        self.unpack_dirpath = ""

    def parse_pkg(self, package_name, json_dict=None):
        """
        Parse a PLDM package and add contents to m_pldm_dict
        Parameters:
            package_name File path of a PLDM file
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            True, and an empty string if the package is valid
        """
        status, pldm, _ = self.unpack_pkg(package_name, out_dir="./", unpack=False)
        if status is False:
            Util.bail_nvfwupd(
                1,
                f"Given input file {package_name} is not a valid PLDM fwpkg",
                print_json=json_dict,
            )
        og_pkg_name = self.m_pldm_dict[package_name]["PackageHeaderInformation"][
            "PackageVersionString"
        ]
        if "HGX" in og_pkg_name and "DGX" in og_pkg_name:
            del self.m_pldm_dict[package_name]

            # Acquire thread_id to ensure unique directory name
            thread_id = threading.get_ident()
            outdir_string = "./" + str(thread_id)

            # unpack to unique thread ID directory
            status, _, _ = self.unpack_pkg(
                package_name, out_dir=outdir_string, unpack=True
            )
            if status is False:
                # Remove the extra directory if it was created
                shutil.rmtree(outdir_string, ignore_errors=True)
                Util.bail_nvfwupd(
                    1,
                    f"Given input file {package_name} is not a valid PLDM fwpkg",
                    print_json=json_dict,
                )
            pkg_dict = self.m_pldm_dict[package_name]
            hgx_pkg_name = ""
            for fw_record in pkg_dict["FirmwareDeviceRecords"]:
                for fw_comp in fw_record["Components"]:
                    if "HGX" in fw_comp["ComponentVersionString"]:
                        hgx_pkg_name = fw_comp["FWImage"]
                        break
            del self.m_pldm_dict[package_name]
            if hgx_pkg_name != "":
                status, pldm, _ = self.unpack_pkg(
                    hgx_pkg_name, out_dir=outdir_string, unpack=False
                )
                package_name = hgx_pkg_name
                shutil.rmtree(outdir_string, ignore_errors=True)
                if status is False:
                    Util.bail_nvfwupd(
                        1,
                        f"Given input file {package_name} "
                        f"is not a valid PLDM fwpkg",
                        print_json=json_dict,
                    )
        self.add_apname_version(pldm)
        return True, ""

    def unpack_pkg(self, package_name, out_dir="./", unpack=False):
        """
        Call pldm parser function with unpack enabled
        Parameters:
            package_name File path of a PLDM file
            out_dir Directory to output extracted files to
            unpack Boolean value indicating to unpack or not
        Returns:
            True, PLDMUnpack class and an empty error message,
            False, PLDMUnpack class and an error message string if there is an error
        """
        pldm = PLDMUnpack()
        pldm.unpack = unpack
        status = pldm.unpack_pldm_package(package_name, out_dir)
        if status is True:
            success, pkg_json = pldm.prepare_records_json()
            if success:
                self.m_pldm_dict[package_name] = json.loads(pkg_json)
                return True, pldm, ""
        return False, pldm, "Pldm parse failed"

    def get_ap_sku(self, records, ap_name):
        """
        Get SKU from VendorDefinedDescriptorData
        Parameters:
            records Records from package metadata
            ap_name The name of a component
        Returns:
            SKU information for the provided component name
        """
        ap_sku = ""
        descriptor_type = "APSKU"
        if ap_name.lower() == "erot":
            descriptor_type = "ECSKU"
        for rec_dict in records:
            title_str = rec_dict.get("VendorDefinedDescriptorTitleString")
            if title_str is not None and title_str == descriptor_type:
                ap_sku = "0x" + rec_dict["VendorDefinedDescriptorData"]
                break
        return ap_sku

    def add_apname_version(self, pldm):
        """
        Prepare dict of pkg name with its ap name, version, sku
        Parameter:
            pldm Initialized PLDM Unpack Class
        """
        ver_dict = {}
        for index, comp_img in enumerate(pldm.component_img_info_list):
            name, records = pldm.get_image_name_from_records(index)
            if name != "":
                sku_id = ""
                sku_id = self.get_ap_sku(records, name)
                ap_name = f"{name},{sku_id}"
                ver_dict[ap_name] = [comp_img["ComponentVersionString"], sku_id.lower()]
        pkg_ver_name = pldm.header_map["PackageVersionString"]
        self.apname_version_dict[pkg_ver_name] = ver_dict

    def get_unpack_file_dict(self, pkg_name):
        """
        Prepare dict of pkg name with its ap name, version, unpacked update filepath
        Parameter:
            pkg_name File path of a PLDM file
        """
        self.unpack_dirpath = tempfile.mkdtemp("nvfwupd")
        _, pldm, _ = self.unpack_pkg(pkg_name, out_dir=self.unpack_dirpath, unpack=True)
        file_dict = {}
        for index, comp_img in enumerate(pldm.component_img_info_list):
            name, _ = pldm.get_image_name_from_records(index)
            if name != "":
                fw_file = ""
                ap_name = name
                fw_file = comp_img["FWImageName"]
                file_dict[ap_name] = [comp_img["ComponentVersionString"], fw_file]
        self.unpack_file_ap_dict = file_dict

    def remove_files(self):
        """
        Method to clear extracted files that must be removed after use
        """
        if self.unpack_dirpath != "":
            shutil.rmtree(self.unpack_dirpath, ignore_errors=True)

    def print_package(self, package_name):
        """
        Print PLDM package with given package_name
        Parameter:
            package_name String name of a package
        """
        pkg_data = self.m_pldm_dict[package_name]
        print(json.dumps(pkg_data, sort_keys=False, indent=4))


def unit_test():
    """
    Unit test implementation
    """
    # pylint: disable=unused-variable
    # pylint: disable=import-outside-toplevel
    import pprint
    import sys

    pldm = PLDM()
    status, msg = pldm.parse_pkg(sys.argv[1])

    print(f"Status : {status}")
    my_pretty_print = pprint.PrettyPrinter(indent=2)
    my_pretty_print.pprint(pldm.m_pldm_dict)
    print(msg)

    if status is True:
        sys.exit(0)
    else:
        sys.exit(1)


# Uncomment for unit testing
# unit_test()
