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
# pylint: disable=too-many-locals, too-many-lines

"""
CLI provides interface to update firmware components
through BMC using Redfish protocol and Switch through
REST APIS
"""
import json
import os
import sys
import socket
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor

import nvfwupd.version
from nvfwupd.dut_access import DUTAccess

# File uses instances of these classes when returned by called functions
# pylint: disable=unused-import
from nvfwupd.dgx_rftarget import DGX_RFTarget
from nvfwupd.hgxb100_rftarget import HGXB100RFTarget, MGXNVLRFTarget
from nvfwupd.base_rftarget import BaseRFTarget
from nvfwupd.pldm import PLDM
from nvfwupd.rf_target import RFTarget
from nvfwupd.pldm import FirmwarePkg
from nvfwupd.pldm import TarPkg
from nvfwupd.config_parser import ConfigParser
from nvfwupd.config_target import ConfigTarget
from nvfwupd.gb200_rftarget import GB200RFTarget
from nvfwupd.gb200_switch_target import GB200SwitchTarget
from nvfwupd.input_params import InputParams
from nvfwupd.input_params import TaskId
from nvfwupd.utils import Util
from nvfwupd.logger import Logger


class FwUpdCmd:
    """Base class for firmware update command
    ...
    Attributes
    ----------
    m_schema : CLISchema
        Initialized CLISchema class for processing cli_schema.yaml
    m_exec_name : str
        Executable name
    m_cmd_name : str
        Command name
    m_cmd_schema : dict
        Dictionary of command schema options
    m_global_options : dict
        Dictionary of global options
    m_args : dict
        Dictionary of input command arguments
    logger : Logger
        Initialized logger class for log and printing operations
    config_parser : ConfigParser
        Class for parsing the yaml config file

    Methods
    -------
    validate_recipes(recipes, json_dict=None) :
        Verify that package files exist and are legitimate
        PLDM files
    validate_cmd(json_input=None) :
        Validate input command and global parameters
        using argparse
    make_target_list(targets, json_dict=None) :
        Create a target list from the configuration yaml
        file
    validate_target_json(global_args, json_dict=None) :
        Validates target list from JSON or config file
    get_parsers() :
        Acquire global and command parsers for a command
    run_command() :
        Run the firmware command
    match_platform(target_platform) :
        Identify the target platform and return its target
        instance class
    create_input_params_list(target_ips_list, cmd_args, package_parser, json_dict=None) :
        Create a list of input parameters used in parallel updates
    init_platform(dut_access, platform_type=None, json_dict=None, parallel_update=False) :
        Acquire target platform from passed in server type or configuration file

    """

    # pylint: disable=too-few-public-methods, too-many-instance-attributes

    g_verbose = False

    def __init__(self, schema, exec_name, arg_dict):
        """
        FwUpdCmd Class constructor

        Parameters:
            schema Loaded command schema
            exec_name Name of this executable
            arg_dict Dictionary of passed in arguments
        """
        self.m_schema = schema
        self.m_exec_name = exec_name
        self.m_cmd_name = arg_dict["Command"]
        self.m_cmd_schema = arg_dict["CmdSchema"]
        #
        # Input global options.
        self.m_global_options = arg_dict["GlobalOptions"]
        #
        # Input command arguments
        self.m_args = arg_dict["CmdArgs"]
        # Update g_verbose
        log_file = "nvfwupd_log.txt"
        FwUpdCmd.g_verbose = False
        if any(option in ["-v", "--verbose"] for option in arg_dict["GlobalOptions"]):
            FwUpdCmd.g_verbose = True
            # Instantiate Logger class
            global_args = None  # global args namespace

            global_option_parser, _ = self.get_parsers()

            if global_option_parser is not None:
                global_args = global_option_parser.parse_args(self.m_global_options)
                if global_args.verbose is not None:
                    log_file = (
                        "nvfwupd_log.txt"
                        if len(global_args.verbose) == 0
                        else global_args.verbose[0]
                    )
                    if log_file.endswith("/") or os.path.isdir(log_file):
                        Util.bail_nvfwupd(
                            1,
                            f"Invalid log file path. {log_file} is a directory.",
                            Util.BailAction.EXIT,
                        )
        # Initialize Logger in JSON mode if passed json options
        if any(option in ["-j", "--json"] for option in arg_dict["CmdArgs"]):
            self.logger = Logger(log_file, True, FwUpdCmd.g_verbose)
        else:
            self.logger = Logger(log_file, False, FwUpdCmd.g_verbose)
        self.config_parser = None
        if any(option == "-c" for option in arg_dict["GlobalOptions"]):
            global_args = None  # global args namespace
            global_option_parser, _ = self.get_parsers()
            if global_option_parser is not None:
                global_args = global_option_parser.parse_args(self.m_global_options)
                if global_args.config is not None:
                    self.config_parser = ConfigParser(global_args.config[0])
                    self.config_parser.parse_config_data()
                sanitize_config = self.config_parser.config_dict.get(
                    "SANITIZE_LOG", None
                )
                if sanitize_config is not None:
                    # If config file only had 1 parameter which was to disable log sanitization
                    # then let the tool enable logs and
                    # continue to behave as though no config file override was given
                    if len(self.config_parser.config_dict) == 1:
                        self.config_parser = None
                    Util.is_sanitize = sanitize_config

    def validate_recipes(self, recipes, json_dict=None):
        """
        Validate recipe files, file exists and is a valid PLDM
        Parameters:
            recipes List of package files
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            A list of recipe files
        """
        if recipes is None and self.config_parser is not None:
            recipes = []
            if self.config_parser.config_dict.get("ParallelUpdate") is True:
                targets_list = self.config_parser.config_dict.get("Targets")
                for target in targets_list:
                    package = target.get("PACKAGE")
                    if package is not None:
                        recipes.append(package)
            else:
                recipes = self.config_parser.config_dict.get("FWUpdateFilePath")
        if recipes is None:
            return recipes
        for each in recipes:
            if not os.path.exists(each):
                Util.bail_nvfwupd(
                    1,
                    f"Error: {self.m_exec_name}: firmware file {each} not found",
                    print_json=json_dict,
                )
        return recipes

    def validate_cmd(self, json_input=None):
        """
        Validate command parameters including global options with argparse
        Parameter:
            json_input Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            Namespace for global and command arguments
        """

        global_args = None  # global args namespace

        global_option_parser, cmd_option_parser = self.get_parsers()

        if global_option_parser is not None:
            global_args = global_option_parser.parse_args(self.m_global_options)

            if self.config_parser is None and (
                global_args.target is None or len(global_args.target) == 0
            ):
                Util.bail_nvfwupd(
                    1,
                    "Error: Required option -t/--target or -c/--config is missing.",
                    print_json=json_input,
                )

        cmd_args = cmd_option_parser.parse_args(self.m_args)
        if global_args:
            log_config = global_args.target
            if global_args.target is not None and len(global_args.target) == 1:
                log_config = Util.default_log_config()
            if global_args.target is None:
                log_config = Util.default_log_config()

            if hasattr(cmd_args, "json") and cmd_args.json is True:
                Util.sanitize_config = Util.get_log_sanitize_config(log_config, True)
            else:
                Util.sanitize_config = Util.get_log_sanitize_config(log_config, False)
            log_string = Util.sanitize_log(str(global_args))
            if not json_input:
                self.logger.debug_print("Global args", log_string)
                self.logger.debug_print("Cmd args", cmd_args)
            FwUpdCmd.g_verbose = global_args.verbose

        return global_args, cmd_args

    # pylint: disable=too-many-statements, too-many-branches
    def make_target_list(self, targets, json_dict=None):
        """
        validate target list from targets JSON or config file and return list
        Parameters:
            targets List of platform targets from config file
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            A validated list of server targets
        """
        targets_list = []
        ip_key = "ip"
        user_key = "user"
        pass_key = "password"
        port_key = "port"
        type_key = "servertype"

        package_key = None
        target_parameters_key = None
        system_name_key = None
        if self.config_parser is not None:
            ip_key = "BMC_IP"
            user_key = "RF_USERNAME"
            pass_key = "RF_PASSWORD"
            port_key = "TUNNEL_TCP_PORT"
            type_key = "TARGET_PLATFORM"

            # optional parameters when using parallel update
            package_key = "PACKAGE"
            target_parameters_key = "UPDATE_PARAMETERS_TARGETS"
            system_name_key = "SYSTEM_NAME"

        if len(targets) == 0:
            Util.bail_nvfwupd(1, "Error: target list is empty", print_json=json_dict)
        for target in targets:
            ip_addr = target.get(ip_key)
            user = target.get(user_key)
            password = target.get(pass_key)
            port = target.get(port_key, "")
            platform_type = None
            package = None
            target_parameters = None
            system_name = None
            if type_key:
                platform_type = target.get(type_key)

            if package_key:
                package = target.get(package_key)
            if target_parameters_key:
                target_parameters = target.get(target_parameters_key)
                if target_parameters is not None:
                    # convert to json as that is what Redfish/NVOS expects
                    target_parameters = json.dumps(target_parameters)
            if system_name_key:
                system_name = target.get(system_name_key)

            if not isinstance(target, dict):
                Util.bail_nvfwupd(
                    1,
                    f"Error: {Util.sanitize_log(target)} is not a valid object",
                    print_json=json_dict,
                )

            if (
                self.config_parser is not None
                and self.m_cmd_name == "update_fw"
                and self.config_parser.config_dict.get("ParallelUpdate") is True
            ):
                # separate package for each target is required for parallel fw updates
                if not all(
                    key in target for key in (ip_key, user_key, pass_key, package_key)
                ):
                    Util.bail_nvfwupd(
                        1,
                        f"Error: {Util.sanitize_log(target)} object has missing/invalid keys  ",
                        print_json=json_dict,
                    )
            else:
                if not all(key in target for key in (ip_key, user_key, pass_key)):
                    Util.bail_nvfwupd(
                        1,
                        f"Error: {Util.sanitize_log(target)} object has missing/invalid keys  ",
                        print_json=json_dict,
                    )

            for value in target.values():
                if isinstance(value, int):
                    value = str(value)
                if isinstance(value, dict):
                    value = str(value)
                if value is None or value.strip() == "":
                    Util.bail_nvfwupd(
                        1,
                        f"Error: {Util.sanitize_log(target)} object missing values",
                        print_json=json_dict,
                    )
            try:
                addr_info = socket.getaddrinfo(ip_addr, None)
                # Disabling pylint for following unused variables as
                # these values may be used in the future and are informative
                # pylint: disable=unused-variable
                for family, socktype, proto, canonname, sockaddr in addr_info:
                    if socktype == socket.SOCK_STREAM:
                        # IP address - Index 0, port is Index 1
                        ip_addr = sockaddr[0]
                        break
            except socket.gaierror:
                Util.bail_nvfwupd(
                    1,
                    f"Error: {Util.sanitize_log(ip_addr)} is an invalid FQDN/ip address",
                    print_json=json_dict,
                )

            target_namespace = [f"ip={ip_addr}", f"user={user}", f"password={password}"]
            if port != "":
                target_namespace.append(f"port={port}")
            elif platform_type:
                target_namespace.append(f"servertype={platform_type}")

            if package:
                target_namespace.append(f"package={package}")

            # {} and [] are still valid updateparameters
            if target_parameters is not None:
                target_namespace.append(f"UpdateParametersTargets={target_parameters}")
            if system_name is not None:
                target_namespace.append(f"systemname={system_name}")

            if self.config_parser is not None:
                update_config = self.config_parser.config_dict.get(
                    "TargetPlatform"
                )  # TargetPlatform
                if update_config is not None and isinstance(update_config, str):
                    update_config = update_config.lower()
                if update_config == "gb200switch":
                    target_namespace.append(f"servertype={update_config}")

            namespace = Namespace(target=target_namespace, verbose=self.g_verbose)
            targets_list.append(namespace)
        return targets_list

    def validate_target_json(self, global_args, json_dict=None):
        """
        Validate json or config file containing targets
        Parameters:
            global_args Parsed global arguments
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            A validated list of server targets
        """
        # pylint: disable=too-many-branches
        targets_list = []

        if global_args.target is not None and len(global_args.target) != 1:
            given_opts = []
            ip_addr = None
            # Extract IP address from the target list
            for input_opt in global_args.target:
                key_value = input_opt.split("=")
                if len(key_value) == 2 and key_value[0].lower() == "ip":
                    ip_addr = key_value[1].strip("[]")  # Remove square brackets
                    break  # Stop after finding the IP

            if ip_addr is None:
                Util.bail_nvfwupd(
                    1, "Error: Missing target IP in command input", print_json=json_dict
                )

            # Reconstruct the target list with the modified IP
            updated_target = []
            for input_opt in global_args.target:
                if input_opt.startswith("ip="):
                    updated_target.append(f"ip={ip_addr}")  # Update IP without brackets
                else:
                    updated_target.append(input_opt)  # Keep other values unchanged

            global_args.target = updated_target  # Update the target list

            for input_opt in global_args.target:
                if input_opt.split("=")[0].lower() not in (
                    "ip",
                    "port",
                    "user",
                    "password",
                    "servertype",
                ):
                    Util.bail_nvfwupd(
                        1,
                        f"Error: Incorrect input option {Util.sanitize_log(input_opt)}",
                        print_json=json_dict,
                    )
                given_opts.append(input_opt.split("=")[0].lower())
            if "ip" not in given_opts:
                Util.bail_nvfwupd(
                    1, "Error: Missing target IP in command input", print_json=json_dict
                )
            if "port" not in given_opts and (
                "user" not in given_opts or "password" not in given_opts
            ):
                Util.bail_nvfwupd(
                    1,
                    "Error: Missing target credentials user/password in command input",
                    print_json=json_dict,
                )
            ip_addr = global_args.target[0].split("=")[1]
            try:
                addr_info = socket.getaddrinfo(ip_addr, None)
                # Disabling pylint for following unused variables as
                # these values may be used in the future and are informative
                # pylint: disable=unused-variable
                for family, socktype, proto, canonname, sockaddr in addr_info:
                    if socktype == socket.SOCK_STREAM:
                        # IP address - Index 0, port is Index 1
                        ip_addr = sockaddr[0]
                        break

                global_args.target[0] = f"ip={ip_addr}"
            except socket.gaierror:
                Util.bail_nvfwupd(
                    1,
                    f"Error: {Util.sanitize_log(ip_addr)} is an invalid FQDN/ip address",
                    print_json=json_dict,
                )
            targets_list.append(global_args)
            return targets_list
        if self.config_parser is not None:
            return self.make_target_list(self.config_parser.targets, json_dict)

        if global_args.target[0].split("=")[0].lower() != "targets":
            if global_args.target[0].split("=")[0].lower() in (
                "ip",
                "port",
                "user",
                "password",
                "servertype",
            ):
                Util.bail_nvfwupd(
                    1,
                    "Error: Incomplete input value for option -t/--target",
                    print_json=json_dict,
                )
            Util.bail_nvfwupd(
                1,
                f"Error: Incorrect input option {Util.sanitize_log(global_args.target[0])}",
                print_json=json_dict,
            )

        if global_args.target[0].split("=")[0].lower() == "targets":
            Util.bail_nvfwupd(
                1,
                "Error: targets json file input support has been deprecated, "
                "please move to using config.yaml for the same multi-target inputs.",
                print_json=json_dict,
            )
        else:
            Util.bail_nvfwupd(
                1,
                "Error: Invalid input, either a target or config file must be "
                "defined.",
                print_json=json_dict,
            )

    def get_parsers(self):
        """
        Get global options and command parsers for this command
        Returns:
            Global and command option parsers
        """

        global_option_parser = None
        cmd_option_parser = None
        if self.m_cmd_schema["RequireGlobalOption"]:
            global_option_parser = self.m_schema.get_global_option_parser()

        cmd_option_parser = self.m_schema.get_command_option_parser(self.m_cmd_schema)
        return global_option_parser, cmd_option_parser

    def run_command(self):
        """
        Run firmware command
        """
        print("Command " + self.m_cmd_name + " not yet implemented\n")

    @staticmethod
    def match_platform(target_platform):
        """
        Method to identify target platform and return respective RFTarget instance
        Parameter:
            target_platform Target model string
        Returns:
            The name of the target class to use based on the target platform name
        """
        target_class = None
        if target_platform.strip() != "":
            # Look for a partial match
            for each_key, val in RFTarget.TARGET_CLASS_DICT.items():
                if each_key in target_platform or target_platform in each_key:
                    target_class = val
                    break
        return target_class

    @staticmethod
    def create_input_params_list(
        target_ips_list, cmd_args, package_parser, json_dict=None
    ):
        """
        Method to create a list of input param objects for parallel update
        Parameters:
            target_ips_list List of Target Namespaces containing ip, username, password
            cmd_args Parsed input command arguments
            package_parser Initialized package parser for the update package
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            A list of input parameters for parallel actions
        """
        input_params_list = []

        for target_ip in target_ips_list:
            arg_dict = {}
            if not target_ip.target is None:
                target_str = " ".join(target_ip.target)
                if Util.is_sanitize:
                    target_str = Util.sanitize_log(target_str)
                for each in target_ip.target:
                    tokens = each.split("=", 1)
                    if len(tokens) < 2:
                        if not json_dict:
                            print(len(tokens))
                        Util.bail_nvfwupd(
                            1,
                            f"Error: invalid target arguments: {target_str},token length:{len(tokens)}",
                            print_json=json_dict,
                        )

                    arg_dict[tokens[0]] = tokens[1]
            # acquire package and update parameters
            ip = arg_dict.get("ip")
            package = arg_dict.get("package")
            special_targets = arg_dict.get("UpdateParametersTargets")
            system_name = arg_dict.get("systemname")

            # create new input param object
            input_param = InputParams(
                target_ip,
                ip,
                cmd_args,
                package_parser,
                package,
                special_targets,
                json_dict,
                system_name,
            )

            # append the newly created object to the list
            input_params_list.append(input_param)

        return input_params_list

    # pylint: disable=too-many-return-statements
    def init_platform(
        self, dut_access, platform_type=None, json_dict=None, parallel_update=False
    ):
        """
        Method to identify target platform and return respective RFTarget instance
        Parameters:
            dut_access Initialized DUT access class to reach the target
            platform_type String server type
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        Returns:
            Initialized system target class or
            None if the system type was invalid or could not be determined
        """
        # pylint: disable=too-many-branches
        rf_target = None
        target_class = ""
        # Parallel Update has platform_types individually defined
        # Config single targets expected to use individual TargetPlatform
        if (platform_type and parallel_update) or (
            platform_type and not self.config_parser
        ):
            target_class = RFTarget.SERVER_TYPE_CLASS_DICT.get(
                platform_type.lower(), None
            )
            if not target_class:
                Util.bail_nvfwupd_threadsafe(
                    1,
                    "Invalid Server Type.",
                    print_json=json_dict,
                    parallel_update=parallel_update,
                )
                return None
            rf_target = globals()[target_class](dut_access)
            return rf_target
        if self.config_parser:
            RFTarget.config_dict = self.config_parser.config_dict
            update_config = self.config_parser.config_dict.get(
                "TargetPlatform"
            )  # TargetPlatform
            if update_config is not None and isinstance(update_config, str):
                update_config = update_config.lower()
            error_msg = (
                f"Configured target platform is {update_config} "
                "but target does not support Redfish service."
            )
            if update_config in [
                "dgx",
                "hgx",
                "gb200",
                "gb300",
                "hgxb100",
                "mgx-nvl",
                "gb200switch",
            ]:
                if type(dut_access).__name__ not in [
                    "BMCLoginAccess",
                    "BMCPortForwardAccess",
                    "GB200NVSwitchAccess",
                ]:
                    Util.bail_nvfwupd_threadsafe(
                        1,
                        error_msg,
                        print_json=json_dict,
                        parallel_update=parallel_update,
                    )
                    return None
                rf_target = ConfigTarget(
                    dut_access, self.config_parser.config_dict, print_json=json_dict
                )
            else:
                rf_target = ConfigTarget(
                    dut_access, self.config_parser.config_dict, print_json=json_dict
                )
            return rf_target
        target_platform = dut_access.m_model.lower()
        if "hgx" in target_platform:
            target_platform = "hgx"
        target_class = RFTarget.TARGET_CLASS_DICT.get(target_platform)
        if target_class is None:
            # Look for a partial match
            target_class = FwUpdCmd.match_platform(target_platform)
            if target_class is None:
                Util.bail_nvfwupd_threadsafe(
                    1,
                    f"Platform {target_platform} not supported",
                    print_json=json_dict,
                    parallel_update=parallel_update,
                )
                return None
        rf_target = globals()[target_class](dut_access)
        return rf_target


class FwUpdCmdToolVersion(FwUpdCmd):
    """
    version command
    ...
    Attributes
    ----------
    m_schema : CLISchema
        Initialized CLISchema class for processing cli_schema.yaml
    m_exec_name : str
        Executable name
    m_cmd_name : str
        Command name
    m_cmd_schema : dict
        Dictionary of command schema options
    m_global_options : dict
        Dictionary of global options
    m_args : dict
        Dictionary of input command arguments
    logger : Logger
        Initialized logger class for log and printing operations
    config_parser : ConfigParser
        Class for parsing the yaml config file

    Methods
    -------
    print_version() :
        Print open-nvfwupd tool version to console
    run_command() :
        Run the tool version command
    """

    @staticmethod
    def print_version():
        """
        Method to print tool version
        """
        print(f"open-nvfwupd version {nvfwupd.version.NVFWUPD_CLI_VERSION}")

    def run_command(self):
        """
        Run version command
        """
        print(f"{self.m_exec_name} version {nvfwupd.version.NVFWUPD_CLI_VERSION}")


class FwUpdCmdHelp(FwUpdCmd):
    """Help command
    ...
    Attributes
    ----------
    m_schema : CLISchema
        Initialized CLISchema class for processing cli_schema.yaml
    m_exec_name : str
        Executable name
    m_cmd_name : str
        Command name
    m_cmd_schema : dict
        Dictionary of command schema options
    m_global_options : dict
        Dictionary of global options
    m_args : dict
        Dictionary of input command arguments
    logger : Logger
        Initialized logger class for log and printing operations
    config_parser : ConfigParser
        Class for parsing the yaml config file

    Methods
    -------
    print_usage(exec_name, text, schema) :
        Print out the tool usage
    run_command() :
        Run the help command
    """

    # pylint: disable=too-few-public-methods

    @staticmethod
    def print_usage(exec_name, text, schema):
        """
        Static method to print CLI usage
        Parameters:
            exec_name Name of this executable
            text String error message for printing
            schema Loaded command schema
        """

        arg_dict = {
            "GlobalOptions": "",
            "Command": "help",
            "CmdArgs": sys.argv[1:],
            "CmdSchema": schema,
        }

        args = " ".join(sys.argv[1:])
        if len(args) > 0:
            print(text + ": " + args)
        else:
            print(text)

        print()

        help_cmd = FwUpdCmdHelp(schema, exec_name, arg_dict)
        help_cmd.run_command()

    def run_command(self):
        """
        Run help command
        """
        # pylint: disable=too-many-branches
        print(f"{self.m_exec_name} version {nvfwupd.version.NVFWUPD_CLI_VERSION}")
        print()
        print(f"Usage: {self.m_exec_name} [ global options ] <command>")
        print()

        print("Global options:")
        options_dict = self.m_schema.get_global_options()

        for _, option_entry in options_dict.items():
            print(
                f"    -{option_entry['Short']} --{option_entry['Long']} {option_entry['Arg']}"
            )
            print(f"           {option_entry['Description']}")
            print()

        print("Commands:")

        # Print out commands not requiring global options
        cmd_records = self.m_schema.m_schema_data["Commands"]
        for each in cmd_records:
            if not each["RequireGlobalOption"]:
                options = self.m_schema.get_command_options(each["Name"])
                if len(options) > 0:
                    print(f"{' ':<4} {each['Name']} [ options... ]")
                else:
                    print(f"{' ':<4} {each['Name']:<10} {each['Description']:<40}")

                for each_option in options:
                    option_str = f"-{each_option['Short']}  --{each_option['Long']}"
                    print(f"{' ':<8} {option_str:<20} {each_option['Description']:<60}")
                print()  # if not requiredGlobalOption

        for each in self.m_schema.m_schema_data["Commands"]:
            if each["RequireGlobalOption"]:
                print(f"{' ':<4} <Global options...> {each['Name']} [ options... ]")
                options = self.m_schema.get_command_options(each["Name"])
                for each_option in options:
                    option_str = (
                        f"-{each_option.get('Short')}  --{each_option.get('Long')}"
                    )
                    if (
                        each["Name"] == "force_update"
                        and each_option.get("Short") is None
                    ):
                        option_str = "enable|disable|status"
                    description = each_option["Description"]
                    print(f"{' ':<8} {option_str:<28} {description:<60}")
                print()  # if requiredGlobalOption


class FwUpdCmdShowVersion(FwUpdCmd):
    """
    Show version command
    ...
    Attributes
    ----------
    m_schema : CLISchema
        Initialized CLISchema class for processing cli_schema.yaml
    m_exec_name : str
        Executable name
    m_cmd_name : str
        Command name
    m_cmd_schema : dict
        Dictionary of command schema options
    m_global_options : dict
        Dictionary of global options
    m_args : dict
        Dictionary of input command arguments
    logger : Logger
        Initialized logger class for log and printing operations
    config_parser : ConfigParser
        Class for parsing the yaml config file

    Methods
    -------
    run_command():
        Run the show version command
    get_output_json_parallel(input_param):
        Acquire system inventories in parallel using input
        parameters
    get_output_json(target_ip, pkg_parser, recipe_list, show_staged=False, json_dict=None):
        Acquire system inventory for a target system and provide
        information in JSON format
    print_output_json(json_output, recipe_list, cmd_args, all_inv_status, json_error_return=None):
        Print the acquired system version information for a target system
    """

    # pylint: disable=too-few-public-methods, too-many-statements, too-many-branches

    # pylint: disable=consider-using-f-string
    def run_command(self):
        """
        Run show recipe command
        """

        global_args, cmd_args = self.validate_cmd()

        if cmd_args.json is True:
            # This will only print out if we hit an error
            # That causes an exit
            json_error_return = {"Error": [], "Error Code": 0, "Output": []}
        else:
            json_error_return = None

        list_of_target_ips = self.validate_target_json(global_args, json_error_return)

        recipe_list = self.validate_recipes(cmd_args.package, json_error_return)
        pkg_parser = None

        # determine if parallel update is set
        parallel_update = False
        if self.config_parser is not None:
            parallel_update = self.config_parser.config_dict.get("ParallelUpdate")
            if parallel_update is not None and not isinstance(parallel_update, bool):
                Util.bail_nvfwupd(
                    1, "Error: Improper format for ParallelUpdate parameter"
                )

        # Parallel update handles pkg parsing for each server separately
        if recipe_list is not None and len(recipe_list) != 0 and not parallel_update:
            pkg_parser = FirmwarePkg.get_pkg_parser(recipe_list[0], FwUpdCmd.g_verbose)
            for pkg_file in recipe_list:
                status, msg = pkg_parser.parse_pkg(pkg_file, json_error_return)
                if status is False:
                    print("WARN: {pkg_file} is not a valid package. Ignoring")
                    print(msg)
                    continue
            # Clean up untared files because show_version does not need them
            pkg_parser.remove_files()
        all_inv_status = 0

        if parallel_update:
            input_params_list = FwUpdCmd.create_input_params_list(
                list_of_target_ips, cmd_args, pkg_parser, json_error_return
            )

            with ThreadPoolExecutor(max_workers=3) as executor:
                results = executor.map(self.get_output_json_parallel, input_params_list)

            # convert generator to list
            printing_results = list(results)
            for result, parameter in zip(printing_results, input_params_list):
                # now print the gathered information in an orderly fashion
                inv_err, json_output = result
                all_inv_status = all_inv_status | inv_err
                if parameter.system_name != None and cmd_args.json is False:
                    print(f"Displaying version info for {parameter.system_name}")

                self.print_output_json(
                    json_output, parameter.package_name, cmd_args, all_inv_status
                )
            if cmd_args.json is True:
                sys.exit(0)
            else:
                Util.bail_nvfwupd(all_inv_status, "")

        for target_ip in list_of_target_ips:
            inv_err, json_output = self.get_output_json(
                target_ip, pkg_parser, recipe_list, cmd_args.staged, json_error_return
            )

            all_inv_status = all_inv_status | inv_err
            self.print_output_json(
                json_output, recipe_list, cmd_args, all_inv_status, json_error_return
            )

        if cmd_args.json is True:
            Util.bail_nvfwupd(all_inv_status, "", Util.BailAction.DO_NOTHING)
        else:
            Util.bail_nvfwupd(all_inv_status, "")

    def get_output_json_parallel(self, input_param):
        """
        Process input params in a parallel fashion for use with get_output_json
        Parameter:
            input_param Initialized InputParam class entry for a system
        Returns:
            0, and a dictionary with system information and firmware inventory or
            1, and a dictionary containing an error message for errors
        """

        target_ip = input_param.target_ip
        pkg_parser = input_param.package_parser
        cmd_args = input_param.cmd_args
        # packages are optional for show_version
        if input_param.package_name is None:
            recipe_list = None
        else:
            recipe_list = [input_param.package_name]
        json_dict = input_param.json_dict

        if pkg_parser is None:
            if recipe_list is not None and len(recipe_list) != 0:
                pkg_parser = FirmwarePkg.get_pkg_parser(
                    recipe_list[0], FwUpdCmd.g_verbose
                )
                for pkg_file in recipe_list:
                    status, msg = pkg_parser.parse_pkg(pkg_file)
                    if status is False:
                        print("WARN: {pkg_file} is not a valid package. Ignoring")
                        print(msg)
                        continue
                # Clean up untared files because show_version does not need them
                pkg_parser.remove_files()

        return self.get_output_json(
            target_ip, pkg_parser, recipe_list, cmd_args.staged, json_dict
        )

    def get_output_json(
        self, target_ip, pkg_parser, recipe_list, show_staged=False, json_dict=None
    ):
        """
        create JSON object for show_version output
        Parameters:
            target_ip Target Namespace containing ip, username, password
            pkg_parser An initialized package parser class
            recipe_list A list of update packages
            show_staged Boolean indicating whether to display staged components
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            0, and a dictionary with system information and firmware inventory or
            1, and a dictionary containing an error message for errors
        """
        json_output = {}

        status, dut_access, platform_type = DUTAccess.get_dut_access(
            target_ip, self.logger, json_dict
        )
        if dut_access is None:
            all_inv_status = 1
            dut_ip = Util.sanitize_log(target_ip.target[0])
            json_output["Connection Status"] = "Failed"
            Util.bail_nvfwupd(
                1,
                f"Error : Unable to access DUT {dut_ip}",
                Util.BailAction.DO_NOTHING,
                print_json=json_dict,
            )
            return all_inv_status, json_output
        json_output["Connection Status"] = "Successful"
        if recipe_list:
            for recipe in recipe_list:
                if (
                    type(dut_access).__name__ == "BMCLoginAccess"
                    and recipe.endswith("fwpkg") is False
                ):
                    Util.bail_nvfwupd(
                        1,
                        "Invalid Firmware Package selected.",
                        Util.BailAction.EXIT,
                        print_json=json_dict,
                    )
                else:
                    continue
        status, inv_err, inv_dict = dut_access.get_firmware_inventory(json_dict)
        if status is False:
            all_inv_status = 1
            Util.bail_nvfwupd(
                1,
                "Error : Failed to retrieve firmware inventory from DUT",
                Util.BailAction.PRINT_DIVIDER,
                print_json=json_dict,
            )
            return all_inv_status, json_output

        if not json_dict:
            self.logger.debug_dict_print(inv_dict)
        pkg_names = "N/A"
        if pkg_parser:
            pkg_names = list(pkg_parser.apname_version_dict.keys())
        json_output["System Model"] = dut_access.m_model
        json_output["Part number"] = dut_access.m_partnumber
        json_output["Serial number"] = dut_access.m_serialnumber
        json_output["Packages"] = pkg_names
        json_output["System IP"] = dut_access.m_ip
        json_output["Firmware Devices"] = []

        rf_target = self.init_platform(dut_access, platform_type, json_dict)
        for each_key, val in inv_dict.items():
            if show_staged:
                firmware_dev = {"AP Name": "", "Sys Version": "", "Staged Version": ""}
            else:
                firmware_dev = {"AP Name": "", "Sys Version": ""}

            dev_url = each_key
            ap_inv_name = dev_url
            if "OSFP" not in dev_url:
                ap_inv_name = dev_url.rsplit("/", 1)[-1]
            firmware_dev["AP Name"] = ap_inv_name
            ap_name = ap_inv_name.lower()
            sys_version = ""
            staged_version = "N/A"
            up_to_date = ""
            pkg_version = ""
            try:
                sys_version = val.get("Version", "unknown")
                firmware_dev["Sys Version"] = sys_version
                up_to_date = "Yes"
            except KeyError:
                pass

            if show_staged:
                try:
                    if (
                        val["Oem"]["Nvidia"]["InactiveFirmwareSlot"]["FirmwareState"]
                        == "Staged"
                    ):
                        staged_version = val["Oem"]["Nvidia"]["InactiveFirmwareSlot"][
                            "Version"
                        ]
                except KeyError:
                    staged_version = "N/A"
                    pass
                firmware_dev["Staged Version"] = staged_version

            if recipe_list and len(recipe_list) != 0:
                # use pkg parse output to match AP using names if -p was given
                if rf_target.is_fungible_component(ap_name):
                    pkg_version = "unknown"
                    identifier = rf_target.get_identifier_from_chassis(dev_url)
                    if identifier is not None:
                        pkg_version = rf_target.get_version_sku(
                            identifier.lower(), pkg_parser.apname_version_dict, ap_name
                        )
                else:
                    pkg_version = rf_target.get_component_version(
                        pkg_parser.apname_version_dict, ap_name
                    )

                if (
                    pkg_version == "unknown"
                    or sys_version == "unknown"
                    or pkg_version == "N/A"
                    or rf_target.version_newer(pkg_version.lower(), sys_version.lower())
                ):
                    up_to_date = "No"
                firmware_dev["Pkg Version"] = pkg_version
                firmware_dev["Up-To-Date"] = up_to_date
            json_output["Firmware Devices"].append(firmware_dev)
        return inv_err, json_output

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def print_output_json(
        self, json_output, recipe_list, cmd_args, all_inv_status, json_error_return=None
    ):
        """
        Print output for showversion
        Parameters:
            json_output A JSON dictionary containing system information and
            firmware inventory
            recipe_list A list of update packages
            cmd_args Parsed input command arguments
            all_inv_status Error code for firmware inventory
            json_error_return Optional JSON Dictionary used for JSON Mode and Prints
        """

        if cmd_args.json is True:
            if (
                json_error_return != None
                and all_inv_status != 0
                and "Error" in json_error_return
                and len(json_error_return["Error"]) != 0
            ):
                # Print the error array in this instance for headless mode
                # If some inventory is present, but we are still in the error state,
                # Output this information alongside the error output
                if "System Model" in json_output and "Part number" in json_output:
                    json_error_return["Output"].append(json_output)

                print(json.dumps(json_error_return, sort_keys=False, indent=4))
            else:
                json_output["Error Code"] = all_inv_status
                print(json.dumps(json_output, sort_keys=False, indent=4))
        else:
            print(f"System Model: {json_output.get('System Model', 'N/A')}")
            print(f"Part number: {json_output.get('Part number', 'N/A')}")
            print(f"Serial number: {json_output.get('Serial number', 'N/A')}")
            print(f"Packages: {json_output.get('Packages', 'N/A')}")
            print(
                f"Connection Status: {json_output.get('Connection Status', 'Failed')}"
            )
            print()
            fw_devices = json_output.get("Firmware Devices", [])
            print("Firmware Devices:")
            if recipe_list is not None and len(recipe_list) != 0:
                if cmd_args.staged:
                    print(
                        "{:<40} {:<30} {:<30} {:<30} {:<10}".format(
                            "AP Name",
                            "Sys Version",
                            "Staged Version",
                            "Pkg Version",
                            "Up-To-Date",
                        )
                    )
                    print(
                        "{:<40} {:<30} {:<30} {:<30} {:<10}".format(
                            "-------",
                            "-----------",
                            "--------------",
                            "-----------",
                            "----------",
                        )
                    )
                    for each_fw in fw_devices:
                        print(
                            "{:<40} {:<30} {:<30} {:<30} {:<10}".format(
                                each_fw.get("AP Name", "N/A"),
                                each_fw.get("Sys Version", "N/A"),
                                each_fw.get("Staged Version", "N/A"),
                                each_fw.get("Pkg Version", "N/A"),
                                each_fw.get("Up-To-Date", "N/A"),
                            )
                        )
                else:
                    print(
                        "{:<40} {:<30} {:<30} {:<10}".format(
                            "AP Name", "Sys Version", "Pkg Version", "Up-To-Date"
                        )
                    )

                    print(
                        "{:<40} {:<30} {:<30} {:<10}".format(
                            "-------", "-----------", "-----------", "----------"
                        )
                    )
                    for each_fw in fw_devices:
                        print(
                            "{:<40} {:<30} {:<30} {:<10}".format(
                                each_fw.get("AP Name", "N/A"),
                                each_fw.get("Sys Version", "N/A"),
                                each_fw.get("Pkg Version", "N/A"),
                                each_fw.get("Up-To-Date", "N/A"),
                            )
                        )
            else:
                if cmd_args.staged:
                    print(
                        "{:<40} {:<30} {:<30}".format(
                            "AP Name", "Sys Version", "Staged Version"
                        )
                    )
                    print(
                        "{:<40} {:<30} {:<30}".format(
                            "-------", "-----------", "--------------"
                        )
                    )
                    for each_fw in fw_devices:
                        print(
                            "{:<40} {:<30} {:<30}".format(
                                each_fw.get("AP Name", "N/A"),
                                each_fw.get("Sys Version", "N/A"),
                                each_fw.get("Staged Version", "N/A"),
                            )
                        )
                else:
                    print("{:<40} {:<30}".format("AP Name", "Sys Version"))
                    print("{:<40} {:<30}".format("-------", "-----------"))
                    for each_fw in fw_devices:
                        print(
                            "{:<40} {:<30}".format(
                                each_fw.get("AP Name", "N/A"),
                                each_fw.get("Sys Version", "N/A"),
                            )
                        )
            print("-" * 120)


class FwUpdCmdForceUpdate(FwUpdCmd):
    """
    Force update command
    ...
    Attributes
    ----------
    m_schema : CLISchema
        Initialized CLISchema class for processing cli_schema.yaml
    m_exec_name : str
        Executable name
    m_cmd_name : str
        Command name
    m_cmd_schema : dict
        Dictionary of command schema options
    m_global_options : dict
        Dictionary of global options
    m_args : dict
        Dictionary of input command arguments
    logger : Logger
        Initialized logger class for log and printing operations
    config_parser : ConfigParser
        Class for parsing the yaml config file

    Methods
    -------
    run_command() :
        Run the Force Update command
    """

    # pylint: disable=too-few-public-methods, unused-variable

    # pylint: disable=too-many-branches
    # pylint: disable=too-many-statements
    def run_command(self):
        """
        Run Force update command
        """

        global_args, cmd_args = self.validate_cmd()

        list_of_target_ips = self.validate_target_json(global_args)

        if cmd_args.json:
            json_output = {"Error": [], "Error Code": 0, "Output": []}
        else:
            json_output = None

        for target_ip in list_of_target_ips:
            dut_ip = Util.sanitize_log(target_ip.target[0])

            status, dut_access, platform_type = DUTAccess.get_dut_access(
                target_ip, self.logger
            )

            if dut_access is None:
                if not cmd_args.json:
                    print("DUT Connection Status: Failed")
                Util.bail_nvfwupd(
                    1,
                    f"Unable to access DUT {dut_ip}",
                    Util.BailAction.PRINT_DIVIDER,
                    print_json=json_output,
                )
                continue
            if not cmd_args.json:
                print("DUT Connection Status: Successful")
            if self.config_parser:
                target_platform = self.config_parser.config_dict.get(
                    "TargetPlatform"
                )  # TargetPlatform
                target_platform_supported = Util.target_platform_supported(
                    target_platform, type(dut_access).__name__
                )
                if target_platform_supported is not None:
                    Util.bail_nvfwupd(
                        1,
                        target_platform_supported,
                        Util.BailAction.EXIT,
                        print_json=json_output,
                    )

            status, task_dict = dut_access.dispatch_request(
                "GET", "/redfish/v1/UpdateService", None
            )

            if not status:
                Util.bail_nvfwupd(
                    1,
                    "Failed to get UpdateService data from the target.",
                    Util.BailAction.PRINT_DIVIDER,
                    print_json=json_output,
                )
                continue

            push_uri_dict = task_dict.get("HttpPushUriOptions")
            if push_uri_dict is not None:
                force_upd = push_uri_dict.get("ForceUpdate")

                if force_upd is None:
                    Util.bail_nvfwupd(
                        1,
                        "The force_update command is not supported for this platform.",
                        Util.BailAction.PRINT_DIVIDER,
                        print_json=json_output,
                    )
                    continue
            else:
                Util.bail_nvfwupd(
                    1,
                    "The force_update command is not supported for this platform.",
                    Util.BailAction.PRINT_DIVIDER,
                    print_json=json_output,
                )
                continue

            if cmd_args.force_upd_action[0].lower() == "status":
                if cmd_args.json:
                    json_output["Output"].append(task_dict)
                    continue

                if force_upd is not None:
                    Util.bail_nvfwupd(
                        0,
                        f"ForceUpdate is set to {force_upd}",
                        Util.BailAction.PRINT_DIVIDER,
                        print_json=json_output,
                    )
                else:
                    Util.bail_nvfwupd(
                        1,
                        "Failed to get ForceUpdate status in UpdateService data.",
                        Util.BailAction.PRINT_DIVIDER,
                        print_json=json_output,
                    )
                continue
            force_upd_val = False
            if cmd_args.force_upd_action[0].lower() == "enable":
                force_upd_val = True
            elif cmd_args.force_upd_action[0].lower() != "disable":
                Util.bail_nvfwupd(
                    1,
                    "Incorrect input option to force_update command.",
                    Util.BailAction.PRINT_DIVIDER,
                    print_json=json_output,
                )
                continue
            # Override forced update in pldm with RF
            force_updset = json.dumps(
                {"HttpPushUriOptions": {"ForceUpdate": force_upd_val}}
            )
            force_patch_uri = "/redfish/v1/UpdateService"
            status, err_dict = dut_access.dispatch_request(
                "PATCH", force_patch_uri, param_data=force_updset
            )
            if status is False:
                Util.bail_nvfwupd(
                    1,
                    f"Patch command for UpdateService data failed err: {err_dict}",
                    Util.BailAction.PRINT_DIVIDER,
                    print_json=json_output,
                )
                continue
            if cmd_args.json:
                json_output["Output"].append({"ForceUpdate": force_upd_val})
            else:
                print(
                    f"ForceUpdate flag was successfully set {force_upd_val} on the system."
                )
                print("-" * 120)

        if cmd_args.json:
            print(json.dumps(json_output, indent=4))


class FwUpdCmdUpdateFirmware(FwUpdCmd):
    """
    Update firmware command
    ...
    Attributes
    ----------
    m_schema : CLISchema
        Initialized CLISchema class for processing cli_schema.yaml
    m_exec_name : str
        Executable name
    m_cmd_name : str
        Command name
    m_cmd_schema : dict
        Dictionary of command schema options
    m_global_options : dict
        Dictionary of global options
    m_args : dict
        Dictionary of input command arguments
    logger : Logger
        Initialized logger class for log and printing operations
    config_parser : ConfigParser
        Class for parsing the yaml config file

    Methods
    -------
    validate_cmd(json_dict=None) :
        Validate command parameters and global options
        with argparse
    update_target(target_ip, cmd_args, recipe_list, pkg_parser,
                      parallel_update, json_output=None) :
        Update a firmware target
    update_fw_parallel(input_param) :
        Update separate target systems in parallel
    query_task_status_parallel(input_param) :
        Query the task status for separate server
        tasks in parallel
    run_command() :
        Run the update firmware command
    """

    def validate_cmd(self, json_dict=None):
        """
        Validate command parameters including global options with argparse
        Parameter:
            json_dict Unused
        Returns:
            Namespace for global and command arguments
        """
        global_args, cmd_args = super().validate_cmd()
        if self.config_parser is None and cmd_args.package is None:
            Util.bail_nvfwupd(1, "Missing command option -p/--package")
        elif (
            cmd_args.package is None
            and self.config_parser is not None
            and self.config_parser.config_dict.get("FWUpdateFilePath") is None
            and self.config_parser.config_dict.get("ParallelUpdate") is (None or False)
        ):
            Util.bail_nvfwupd(
                1,
                "Atleast 1 update package is required for update_fw. "
                "Please provide -p/--package in CLI or FWUpdateFilePath in config file.",
            )
        return global_args, cmd_args

    # pylint: disable=too-many-arguments,too-many-return-statements,too-many-branches, too-many-positional-arguments
    def update_target(
        self,
        target_ip,
        cmd_args,
        recipe_list,
        pkg_parser,
        parallel_update,
        json_output=None,
    ):
        """
        Update firmware target
        Parameters:
            target_ip Target Namespace containing ip, username, password
            cmd_args Parsed input command arguments
            recipe_list A list of update packages
            pkg_parser An initialized package parser class
            parallel_update Boolean value, True if doing a parallel update
            json_output Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            Update task id list, and error code of 0 or
            Empty update task id list, and error code of 0 for single update or
            None, and 1 if an error occurs
        """

        all_update_status = 0

        dut_ip = Util.sanitize_log(target_ip.target[0])
        if not cmd_args.json:
            print(f"Updating ip address: {dut_ip}")
        status, dut_access, platform_type = DUTAccess.get_dut_access(
            target_ip, self.logger, json_dict=json_output
        )

        if dut_access is None:
            Util.bail_nvfwupd(
                1,
                f"Unable to access DUT {dut_ip}",
                Util.BailAction.PRINT_DIVIDER,
                print_json=json_output,
            )
            all_update_status = 1
            return None, all_update_status

        for recipe in recipe_list:
            if (
                type(dut_access).__name__ == "BMCLoginAccess"
                and recipe.endswith("fwpkg") is False
            ):
                if not parallel_update:
                    action = Util.BailAction.EXIT
                else:
                    action = Util.BailAction.PRINT_DIVIDER

                Util.bail_nvfwupd_threadsafe(
                    1,
                    "Invalid Firmware Package selected.",
                    action,
                    print_json=json_output,
                    parallel_update=parallel_update,
                )
                all_update_status = 1
                return None, all_update_status
            else:
                continue

        rf_target = self.init_platform(
            dut_access,
            platform_type,
            json_dict=json_output,
            parallel_update=parallel_update,
        )

        if rf_target is None:
            all_update_status = 1
            return None, all_update_status

        # check staged update support
        if type(rf_target).__name__ not in [
            "HGXB100RFTarget",
            "GB200RFTarget",
            "ConfigTarget",
        ] and (cmd_args.staged_update or cmd_args.staged_activate_update):
            Util.bail_nvfwupd_threadsafe(
                1,
                "Target Platform does not support staged update",
                print_json=json_output,
                parallel_update=parallel_update,
            )
            all_update_status = 1
            return None, all_update_status

        if not cmd_args.json:
            print(f"FW package: {recipe_list}")
            self.logger.debug_print(cmd_args.background)
            self.logger.debug_print(cmd_args.yes)
        time_out = 900  # default value 900s
        if (
            cmd_args.timeout
            and cmd_args.timeout.isdigit()
            and int(cmd_args.timeout) != 0
        ):
            time_out = int(cmd_args.timeout)

        # If using json, we are already running in uninteractive mode
        # Skip this check for parallel update
        if cmd_args.yes is False and not cmd_args.json and not parallel_update:
            try:
                answer = input("Ok to proceed with firmware update? <Y/N>\n").lower()
                if answer != "y":
                    Util.bail_nvfwupd(
                        0,
                        "Exiting firmware update process..!",
                        Util.BailAction.PRINT_DIVIDER,
                    )
                    return None, all_update_status
            except RuntimeError:
                all_update_status = 1
                Util.bail_nvfwupd(
                    1,
                    "Exiting firmware update process..!",
                    Util.BailAction.PRINT_DIVIDER,
                )
                return None, all_update_status

        status, task_id_list = rf_target.start_update_monitor(
            recipe_list,
            pkg_parser,
            cmd_args,
            time_out,
            parallel_update,
            json_dict=json_output,
        )
        all_update_status = status | all_update_status
        pkg_parser.remove_files()
        if not cmd_args.json:
            print("-" * 120)

        return task_id_list, all_update_status

    def update_fw_parallel(self, input_param):
        """
        Process parallel input params for target updating
        Parameter:
            input_param Initialized InputParam class entry for a system
        Returns:
            An updated input parameter
        """

        target_ip = input_param.target_ip
        pkg_parser = input_param.package_parser
        recipe_list = [input_param.package_name]
        cmd_args = input_param.cmd_args
        json_output = input_param.json_dict
        system_name = input_param.system_name

        # Handle updateparameters
        special_targets = input_param.special
        if special_targets is not None and cmd_args.special is None:
            # Fix any irregularities in "" if they exist in the targets
            cmd_args.special = special_targets.replace("'", '"')

        # acquire task_id list returned from update
        task_id_list, _ = self.update_target(
            target_ip, cmd_args, recipe_list, pkg_parser, True, json_output
        )

        # If system name is specified, append it to the json output for system identification
        if system_name and json_output:
            for item in json_output["Output"]:
                item["system_name"] = system_name

        input_param.task_id_list = []
        # If task_id_list is none, then the update failed
        if task_id_list is None:
            # the input param with an empty task id list
            return input_param

        for task_value in task_id_list:
            task_object = TaskId(task_value)
            input_param.task_id_list.append(task_object)

        return input_param

    def query_task_status_parallel(self, input_param):
        """
        Query Task Status for each task belonging to a server
        Parameter:
            input_param Initialized InputParam class entry for a system
        """
        rf_target = input_param.rf_target

        # acquire status and response dict for each task
        for task in input_param.task_id_list:
            status, resp_dict = rf_target.query_job_status(task.task_id)
            task.status = status
            task.response_dict = resp_dict

    # pylint: disable=too-few-public-methods, too-many-nested-blocks
    def run_command(self):
        """
        Run update firmware command
        """
        # pylint: disable=too-many-statements, too-many-branches

        global_args, cmd_args = self.validate_cmd()

        if cmd_args.json:
            json_output = {"Error": [], "Error Code": 0, "Output": []}
        else:
            json_output = None

        if cmd_args.details and cmd_args.json:
            Util.bail_nvfwupd(
                1,
                "Table update progress is not supported with json option.",
                print_json=json_output,
            )

        if cmd_args.json and not cmd_args.background:
            Util.bail_nvfwupd(
                1,
                "JSON update is not supported without --background option.",
                print_json=json_output,
            )

        if cmd_args.staged_update and cmd_args.staged_activate_update:
            Util.bail_nvfwupd(
                1,
                "Stage only option is not supported alongside stage and activate option",
                print_json=json_output,
            )

        list_of_target_ips = self.validate_target_json(global_args, json_output)

        # determine if parallel update is set
        parallel_update = False
        if self.config_parser is not None:
            parallel_update = self.config_parser.config_dict.get("ParallelUpdate")
            if parallel_update is not None and not isinstance(parallel_update, bool):
                Util.bail_nvfwupd(
                    1, "Error: Improper format for ParallelUpdate parameter"
                )

        # Parallel update is supported for background update
        if (
            cmd_args.background is True
            and len(list_of_target_ips) > 1
            and not parallel_update
        ):
            Util.bail_nvfwupd(
                1,
                "Multi-target update is not supported with --background option.",
                print_json=json_output,
            )

        recipe_list = self.validate_recipes(cmd_args.package, json_output)

        if not recipe_list or len(recipe_list) == 0:
            Util.bail_nvfwupd(
                1,
                "Error: No valid packages input for fw_update",
                print_json=json_output,
            )

        pkg_parser = FirmwarePkg.get_pkg_parser(recipe_list[0], FwUpdCmd.g_verbose)

        if cmd_args.special:
            if not os.path.exists(cmd_args.special[0]) or not os.path.isfile(
                cmd_args.special[0]
            ):
                Util.bail_nvfwupd(
                    1,
                    f"Special command json file doesn't exist: {cmd_args.special[0]}",
                    print_json=json_output,
                )

        all_update_status = 0

        if parallel_update:
            input_params_list = FwUpdCmd.create_input_params_list(
                list_of_target_ips, cmd_args, pkg_parser, json_output
            )
            with ThreadPoolExecutor(max_workers=3) as executor:
                input_with_task_id_generator = executor.map(
                    self.update_fw_parallel, input_params_list
                )

            # Convert the generator to a list
            input_with_task_id = list(input_with_task_id_generator)

            # combine json outputs for final printing
            if cmd_args.json:
                for entry in input_with_task_id:
                    for output in entry.json_dict["Output"]:
                        json_output["Output"].append(output)
                    for error in entry.json_dict["Error"]:
                        json_output["Error"].append(error)
                if len(json_output["Error"]) != 0:
                    # Set the error code if not all systems succeeded
                    all_update_status = 1

            # loop through going backwards
            for target in reversed(input_with_task_id):
                if target is not None and len(target.task_id_list) != 0:
                    if target.rf_target is None:
                        _, dut_access, platform_type = DUTAccess.get_dut_access(
                            target.target_ip, self.logger, json_output
                        )

                        if dut_access is None:
                            if not cmd_args.json:
                                print(
                                    "Error in accessing DUT target,removing target & continuing"
                                )
                            # Remove the unreachable target from the list and continue
                            input_with_task_id.remove(target)
                            all_update_status = 1
                            continue

                        # save rf_target
                        target.rf_target = self.init_platform(
                            dut_access,
                            platform_type,
                            json_dict=json_output,
                            parallel_update=True,
                        )

                    # Remove any bad task ids less than 0
                    for task_object in target.task_id_list[:]:
                        try:
                            # Task ID is a string by default
                            if int(task_object.task_id) < 0:
                                # remove task_object from list
                                target.task_id_list.remove(task_object)
                        except ValueError:
                            # Task IDS such as HGX_0 (GB200 HMC) won't be able to be converted
                            pass
                else:
                    # Remove the empty tasks or those that are None
                    input_with_task_id.remove(target)
                    all_update_status = 1

            TASK_SUCCESS_STATES = ("completed", "action_success")

            # Known failure states across various systems
            TASK_FAILURE_STATES = (
                "cancelled",
                "cancelling",
                "exception",
                "interrupted",
                "killed",
                "stopping",
                "suspended",
                "error",
            )

            # If running in background mode, print task status once and exit
            if not cmd_args.json:
                # Use threadpool API to query job status in parallel
                with ThreadPoolExecutor(max_workers=3) as task_executor:
                    task_executor.map(
                        self.query_task_status_parallel, input_with_task_id
                    )

                for entry in input_with_task_id:
                    if len(entry.task_id_list) != 0:
                        print(
                            f"Printing Task status for IP: {Util.sanitize_log(entry.ip)}"
                        )
                        if entry.system_name:
                            print(
                                f"Printing Task status for system: {entry.system_name}"
                            )

                    for task in entry.task_id_list[:]:
                        ret_code, job_state = entry.rf_target.print_job_status(
                            task.task_id, task.response_dict, task.status
                        )

                        # if completed or failed, remove it from the list
                        if (
                            job_state is None
                            or job_state in TASK_SUCCESS_STATES
                            or job_state in TASK_FAILURE_STATES
                            or ret_code != 0
                        ):
                            entry.task_id_list.remove(task)

                            # set failure state
                            if (
                                job_state is None
                                or job_state in TASK_FAILURE_STATES
                                or ret_code != 0
                            ):
                                all_update_status = 1

            # If running in background mode, exit
            if cmd_args.background is True:
                Util.bail_nvfwupd(all_update_status, "", print_json=json_output)

            # ongoing query status
            while True:
                if len(input_with_task_id) == 0:
                    # If the list is empty, exit
                    Util.bail_nvfwupd(all_update_status, "", print_json=json_output)

                # Use threadpool API to query job status in parallel
                with ThreadPoolExecutor(max_workers=3) as task_executor:
                    task_executor.map(
                        self.query_task_status_parallel, input_with_task_id
                    )

                # Print job statuses
                for entry in input_with_task_id:
                    if len(entry.task_id_list) != 0:
                        if not cmd_args.json:
                            print(
                                f"Printing Task status for IP: {Util.sanitize_log(entry.ip)}"
                            )
                            if entry.system_name:
                                print(
                                    f"Printing Task status for system: {entry.system_name}"
                                )

                    for task in entry.task_id_list[:]:
                        ret_code, job_state = entry.rf_target.print_job_status(
                            task.task_id, task.response_dict, task.status
                        )

                        # if completed or failed, remove it from the list
                        if (
                            job_state is None
                            or job_state in TASK_SUCCESS_STATES
                            or job_state in TASK_FAILURE_STATES
                            or ret_code != 0
                        ):
                            entry.task_id_list.remove(task)

                            # set failure state
                            if (
                                job_state is None
                                or job_state in TASK_FAILURE_STATES
                                or ret_code != 0
                            ):
                                all_update_status = 1

                # Process removals
                for entry in input_with_task_id[:]:
                    if len(entry.task_id_list) == 0:
                        input_with_task_id.remove(entry)

                # sleep for 20 seconds before querying again
                time.sleep(20)

        for target_ip in list_of_target_ips:
            # Task ID list unused for single target update
            _, all_update_status = self.update_target(
                target_ip, cmd_args, recipe_list, pkg_parser, False, json_output
            )

        Util.bail_nvfwupd(all_update_status, "", print_json=json_output)


class FwUpdCmdShowUpdateProgress(FwUpdCmd):
    """
    Show FW update progress
    ...
    Attributes
    ----------
    m_schema : CLISchema
        Initialized CLISchema class for processing cli_schema.yaml
    m_exec_name : str
        Executable name
    m_cmd_name : str
        Command name
    m_cmd_schema : dict
        Dictionary of command schema options
    m_global_options : dict
        Dictionary of global options
    m_args : dict
        Dictionary of input command arguments
    logger : Logger
        Initialized logger class for log and printing operations
    config_parser : ConfigParser
        Class for parsing the yaml config file

    Methods
    -------
    run_command() :
        Run the show update progress command
    """

    def run_command(self):
        """
        Show FW update progress
        """
        global_args, cmd_args = self.validate_cmd()

        if cmd_args.json:
            json_output = {"Error": [], "Error Code": 0, "Output": []}
        else:
            json_output = None

        cmd_dict = vars(cmd_args)
        if not cmd_args.json:
            self.logger.debug_dict_print(cmd_dict)
        list_of_target_ips = self.validate_target_json(global_args, json_output)
        error_status = 0
        if len(list_of_target_ips) == 1:
            _, dut_access, platform_type = DUTAccess.get_dut_access(
                list_of_target_ips[0], self.logger, json_output
            )
            if dut_access is None:
                Util.bail_nvfwupd(
                    1,
                    f"Unable to access system {Util.sanitize_log(list_of_target_ips[0])}",
                    Util.BailAction.EXIT,
                    json_output,
                )
            rf_target = self.init_platform(
                dut_access, platform_type, json_dict=json_output
            )
            for task_id in cmd_dict["id"]:
                error_status = error_status | rf_target.process_job_status(
                    task_id, print_json=json_output
                )
                if not cmd_args.json:
                    print("-" * 120)
        else:
            Util.bail_nvfwupd(
                1,
                "Multiple targets not supported with show_update_progress command.",
                Util.BailAction.EXIT,
                json_output,
            )

        Util.bail_nvfwupd(error_status, "", print_json=json_output)
