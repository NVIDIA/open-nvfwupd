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
through BMC using Redfish protocol and Switch through
REST APIS
"""

import os
import sys
import signal
from nvfwupd.cli_schema import CLISchema

# File uses instances of all classes when returned by called functions
# pylint: disable=wildcard-import
# pylint: disable=unused-wildcard-import
from nvfwupd.updcommand import *
from nvfwupd.utils import Util


def keyboard_int_handler(_, __):
    """Method to handle user pressing Ctrl+C"""
    # Ignore multiple Ctrl-C and ask user to confirm exit or continue
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    res = input("Ctrl-C was pressed, Exit from nvfwupd tool? (y/n)")
    if res.lower() == "y":
        print("Exiting...")
        Util.bail_nvfwupd(1)
    print("Continuing...")
    signal.signal(signal.SIGINT, keyboard_int_handler)


def get_arguments(schema):
    """
    Split the command line arguments to global options,
    and script command arguments such as
    show_version, update_fw,

    Parameter:
        schema Loaded command schema
    Returns:
        Executable name, global options, and command arguments
    """

    exec_name = sys.argv[0].split(os.sep)[-1]
    cmd_args = []
    global_options = []

    cmd_list = schema.get_command_list()

    index = 1
    #
    # Scan the command arguments. First part is the global options.
    # Tokens following the global options are script commands and
    # command arguments.
    for each in sys.argv[1:]:
        if each in cmd_list:
            break

        global_options.append(each)

        index += 1

    cmd_args = sys.argv[index:]
    # check if the command is version other than standard version command
    if len(sys.argv) > 1:
        if sys.argv[1] == "-V" or sys.argv[1] == "--version":
            cmd_args = sys.argv[1]

    return exec_name, global_options, cmd_args


def instantiate_cmd(schema, exec_name, global_options, cmd_args):
    """
    Instantiate firmware command
    Parameters:
        schema Loaded command schema
        exec_name Name of this executable
        global_options List of Passed in Global target options
        cmd_args List of input command and arguments
    """

    cmd_record = schema.get_command_schema(cmd_args[0])

    if not cmd_record:
        FwUpdCmdHelp.print_usage(exec_name, "Error: Invalid command", schema)
        Util.bail_nvfwupd(1)

    class_name = "FwUpdCmd" + cmd_record["Class"]

    #
    # Pass parameters in a dictionary shut up pylint
    # complaining about too-many-arguments
    arg_dict = {
        "GlobalOptions": global_options,
        "Command": cmd_args[0],
        "CmdArgs": cmd_args[1:],
        "CmdSchema": cmd_record,
    }

    cmd_instance = globals()[class_name](schema, exec_name, arg_dict)

    cmd_instance.run_command()


def main():
    """
    Main function
    """

    path = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, path)

    resource = Util.get_abs_path("cli_schema.yaml")
    schema = CLISchema()
    schema.load_schema(resource)

    #
    # Decompose command line arguments into global options and command options
    exec_name, global_options, cmd_args = get_arguments(schema)

    if Util.check_duplicate_item(global_options):
        Util.bail_nvfwupd(
            1,
            "Error: nvfwupd tool expects any global config input exactly one time.",
            Util.BailAction.EXIT,
        )

    if len(cmd_args) == 0:
        #
        FwUpdCmdHelp.print_usage(exec_name, "Error: Missing command argument", schema)
        Util.bail_nvfwupd(1)
    elif cmd_args in ["-V", "--version"]:
        FwUpdCmdToolVersion.print_version()
        sys.exit(0)

    instantiate_cmd(schema, exec_name, global_options, cmd_args)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, keyboard_int_handler)
    main()
