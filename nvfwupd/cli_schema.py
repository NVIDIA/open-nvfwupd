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
CLI provides interface to update firmware components
through BMC using Redfish protocol
"""

import argparse
import sys
import yaml
from nvfwupd.utils import Util


class CLISchema:
    """
    Class handling CLI schema related operations:
     1. Load schema YAML file
     2. Methods to retrieve CLI global options and
        and Commands defined in schema
    ...
    Attributes
    ----------
    m_schema_data : dict
        Dictionary of loaded yaml schema data

    Methods
    -------
    load_schema(schema_name) :
        Load a schema into memory
    get_command_list() :
        Get the list of commands from a schema
    get_global_options() :
        Get the global options from a schema
    get_command_options(cmd) :
        Get the command options for given command
    get_command_schema(cmd_name) :
        Acquire the command schema for a given command
    get_global_option_parser() :
        Acquire the argparser for schema global options
    get_command_option_parser(cmd_schema) :
        Acquire the argparser for a provided command
    """

    def __init__(self):
        """
        Contructor for CLISchema class
        """
        self.m_schema_data = None

    def load_schema(self, schema_name):
        """
        Load CLI schema
        Parameter:
            schema_name The file path of the yaml schema
        """

        try:
            with open(schema_name, "r", encoding="utf-8") as file_handle:
                self.m_schema_data = yaml.safe_load(file_handle)
        except IOError:
            Util.bail_nvfwupd(1, "Error open CLI schema\n")

    def get_command_list(self):
        """
        Acquire command names from a schema.
        Returns:
            List of commands in a given schema
        """
        cmd_list = []

        for each in self.m_schema_data["Commands"]:
            cmd_list.append(each["Name"])

        return cmd_list

    def get_global_options(self):
        """
        Acquire global options from a schema.
        Returns:
            List of Global Options as a list of dictionaries
        """

        options_dict = {}
        global_options = self.m_schema_data["GlobalOptions"]

        for each in global_options["Options"]:
            for option_name, option_entry in each.items():
                options_dict[option_name] = option_entry

        return options_dict

    def get_command_options(self, cmd):
        """
        Acquire options for a given command.
        Parameter:
            cmd The name of the command used
        Returns:
            List of option dictionaries for a given command or
            an empty list if there is an error
        """

        for each in self.m_schema_data["Commands"]:
            if each["Name"] == cmd:
                try:
                    return each["Options"]
                except KeyError:
                    break

        return []

    def get_command_schema(self, cmd_name):
        """
        Get command schema for the given cmd_name
        Command entry includes following field in the schema:
        - Name
        - Class
        - RequiredGlobalOptions
        - Array of command options dictionary
        Parameter:
            cmd_name The name of the command used
        Returns:
            Command schema for the provided command name or
            None if nothing matches
        """

        for each in self.m_schema_data["Commands"]:
            if each["Name"] == cmd_name:
                return each

        return None

    def get_global_option_parser(self):
        """
        Get argparse for global options
        Returns:
            Argument parser for global options of type argparse
        """

        global_options_schema = self.m_schema_data["GlobalOptions"]

        options_dict = self.get_global_options()

        parser = argparse.ArgumentParser(
            add_help=False, usage=sys.argv[0] + " " + global_options_schema["Usage"]
        )

        for _, option_entry in options_dict.items():
            kwargs = {"dest": option_entry["Long"], "action": option_entry["Action"]}

            #
            # non-boolean option should have nargs
            if "Nargs" in option_entry:
                kwargs["nargs"] = option_entry["Nargs"]

            parser.add_argument(
                "-" + option_entry["Short"], "--" + option_entry["Long"], **kwargs
            )

        return parser

    def get_command_option_parser(self, cmd_schema):
        """
        Get argparse for given command
        Parameters:
            cmd_schema The loaded command schema
        Returns:
            Argument parser for a given command of type argparse
        """
        cmd_name = cmd_schema["Name"]

        parser = argparse.ArgumentParser(
            add_help=False, usage=cmd_schema.get("Usage", "")
        )

        options_dict = cmd_schema.get("Options", [])

        # add_argument for each option in given cmd_schema
        for options in options_dict:
            kwargs = {"dest": options["Long"], "action": options["Action"]}

            #
            # non-boolean option should have nargs
            if "Nargs" in options:
                kwargs["nargs"] = options["Nargs"]

            if "Required" in options:
                kwargs["required"] = options["Required"]

            if cmd_name != "force_update":
                parser.add_argument(
                    "-" + options["Short"], "--" + options["Long"], **kwargs
                )
            else:
                # with added json option, force update must allow for a short option
                try:
                    parser.add_argument(
                        "-" + options["Short"], "--" + options["Long"], **kwargs
                    )
                except:  # pylint: disable=bare-except
                    parser.add_argument(**kwargs)

        return parser
