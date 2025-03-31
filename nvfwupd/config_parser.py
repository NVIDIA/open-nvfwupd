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
"""Defines class for parsing config file for nvfwupd"""

import os
import yaml
from nvfwupd.utils import Util


class ConfigParser:
    """
    Class to implement config file parser for nvfwupd
    ...
    Attributes
    ----------
    config_dict : dict
        Dictionary containing config.yaml target information
    targets : list
        A list of system targets each containing at least IP, username,
        and password
    config_file_path : str
        Path of the config.yaml file

    Methods
    -------
    parse_config_data() :
        Open the configuration file, read yaml data into memory and create the
        targets list
    make_targets_list() :
        Create a list of targets from the parsed config file

    """

    def __init__(self, config_file_path):
        """
        Contructor for ConfigParser class
        Parameters:
            config_file_path The configuration file path
        """
        self.config_dict = None
        self.targets = []
        self.config_file_path = config_file_path

    def parse_config_data(self):
        """
        open config file read yaml data and return yaml dict or None
        prepare targets list
        """
        if not os.path.exists(self.config_file_path) or not os.path.isfile(
            self.config_file_path
        ):
            Util.bail_nvfwupd(
                1,
                f"Config file {self.config_file_path} does not exist.",
                Util.BailAction.EXIT,
            )
        with open(self.config_file_path, "r", encoding="utf-8") as config_data:
            try:
                self.config_dict = yaml.safe_load(config_data)
                if self.config_dict is None:
                    Util.bail_nvfwupd(
                        1,
                        f"Config file {self.config_file_path} is empty. "
                        "Please provide valid YAML config",
                        Util.BailAction.EXIT,
                    )
            except yaml.YAMLError:
                Util.bail_nvfwupd(
                    1,
                    f"Unable to parse config file {self.config_file_path}."
                    "Please provide valid YAML config",
                    Util.BailAction.EXIT,
                )
        self.make_targets_list()

    def make_targets_list(self):
        """
        Prepare list of targets
        """
        self.targets = self.config_dict.get("Targets")
        if self.targets is None:
            target_dict = {}
            target_dict["BMC_IP"] = self.config_dict.get("BMC_IP")
            target_dict["RF_USERNAME"] = self.config_dict.get("RF_USERNAME")
            target_dict["RF_PASSWORD"] = self.config_dict.get("RF_PASSWORD")
            if self.config_dict.get("TUNNEL_TCP_PORT") is not None:
                target_dict["TUNNEL_TCP_PORT"] = self.config_dict.get("TUNNEL_TCP_PORT")
            self.targets = [target_dict]
