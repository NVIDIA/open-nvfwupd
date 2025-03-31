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
Utils module for nvfwupd
"""
import subprocess
import textwrap
import sys
import json
import enum
import os
import logging
import re
from enum import Enum


class BuiltInLogSanitizers(Enum):
    """
    Supported Built-In log sanitizer regex
    """

    IPV4 = "ipv4_address"
    IPV6 = "ipv6_address"


class LogSanitizer(logging.Formatter):
    """
    Class to handle log sanitization
    ...
    Attributes
    ----------
    compiled_string : str
        Compiled pattern string for regex
    replacement : str
        String used to replace target strings

    Methods
    -------
    sanitize(string) :
        Sanitizes a string for printing or logging
    """

    builtin_regex = {
        BuiltInLogSanitizers.IPV4: r"((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])",
        BuiltInLogSanitizers.IPV6: r"(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))",
    }

    def __init__(
        self,
        fmt=None,
        datefmt=None,
        style="%",
        string_list=None,
        replacement_string="XXXX",
        additional_regex=[BuiltInLogSanitizers.IPV4, BuiltInLogSanitizers.IPV6],
    ):
        """
        Sanitizer constructor. Provide the list of strings to filter out from the logs
        Parameters:
            fmt Format string style. Doesn't affect sanitize() output.
            datefmt Format style for date/time. Doesn't affect sanitize() output.
            style Determines how the format string will be merged.
            string_list List of strings to filter out
            replacement_string String to replace target strings. Default is XXXX
            additional_regex List of in-built log collectors to be used
        """
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)
        self.compiled_string = None
        if not isinstance(string_list, list):
            string_list = []
        string_list = list(
            map(lambda x: r"(?<!\w)" + re.escape(x) + r"(?!\w)", string_list)
        )
        for regex in additional_regex:
            string_list.append(self.builtin_regex[regex])
        if len(string_list) == 0:
            return
        self.compiled_string = re.compile("|".join(string_list), flags=re.M)
        self.replacement = replacement_string

    def sanitize(self, string):
        """
        Sanitizes a given string based on initialized strings and in-built sanitizers
        Parameter:
            string A string to be sanitized
        Returns:
            A sanitized string
        """
        return (
            re.sub(self.compiled_string, self.replacement, string)
            if self.compiled_string
            else string
        )


class Util:
    """
    Class with static methods
    ...
    Methods
    -------
    get_tokens(text, sep) :
        Returns text tokens delimited by the
        provided separator
    default_log_config() :
        Returns the default sanitized log
        configuration
    get_abs_path(resource) :
        Get the absolute path to a resource
        in the working directory
    ping_to_check_system(host) :
        Ping the provided host IP address to see
        if it is reachable
    get_log_sanitize_config(config, json_dict=False) :
        Create a global dictionary configuration
        from the passed in configuration list
    get_sanitizer(log_config, enabled=True) :
        Returns a LogSanitizer object from the provided
        log configuration
    sanitize_log(data) :
        Sanitizes a log message
    target_platform_supported(target_access, platform_type) :
        Validates a target platform servertype with the access
        class
    bail_nvfwupd(error_code, msg="", action = BailAction.EXIT, print_json=None) :
        Exit program, print dividers, or print the provided error message
    bail_nvfwupd_threadsafe(error_code, msg="",
                                action = BailAction.EXIT,
                                print_json=None,
                                parallel_update=False) :
        Exit program, print dividers, or print the provided error message. Stops
        program exit during parallel updates
    check_duplicate_item(data: list) :
        Check if the provided list contains duplicate items
    compare_dict(data, result, seen) :
        Compare two dictionaries
    wrap_text(text, width) :
        Wrap text for printing to console
    """

    is_sanitize = True
    sanitize_config = None

    class BailAction(enum.Enum):
        """
        BailAction Enum
        """

        EXIT = 0
        PRINT_DIVIDER = 1
        DO_NOTHING = 2

    @staticmethod
    def get_tokens(text, sep):
        """
        Return tokens delimited by sep
        Parameters:
            text String text to be delimited
            sep Separator to delimit the text
        Returns:
            Tokens delimited by the input separator
        """
        tmp = text.split(sep)

        return tmp

    @staticmethod
    def default_log_config():
        """
        Default Log config
        Returns:
            A list of ip, user, and password set to three x characters
        """
        return ["ip=xxx", "user=xxx", "password=xxx"]

    @staticmethod
    def get_abs_path(resource):
        """
        Get absolute path to resource
        Parameter:
            resource Filename to query
        Returns:
            A joined path of the current directory and a resource name
        """
        base_path = os.path.abspath(".")

        return os.path.join(base_path, resource)

    @staticmethod
    def ping_to_check_system(host):
        """
        Pings the given host and returns True if successful, False otherwise.
        Parameter:
            host IP Value of a system
        Returns:
            True if the ping was successful or
            False if the ping was not successful
        """
        command = ["ping", "-c", "1", host]
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
        return result.returncode == 0

    @staticmethod
    def get_log_sanitize_config(config: list, json_dict=False) -> dict:
        """
        This will convert global config target from list to dict
        Parameter:
            config Log configuration
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
        Returns:
            A converted global config dictionary or
            None if the config is invalid
        """
        if config:
            result = {}
            try:
                for item in config:
                    key, value = item.split("=", 1)
                    result[key] = value
                return result
            except ValueError as _:
                if json_dict is True:
                    # Special handling necessary for JSON mode error printing
                    # as this is before JSON mode even initialized
                    # Still need to provide proper JSON error output to console
                    json_output = {"Error": [], "Error Code": 0, "Output": []}

                    Util.bail_nvfwupd(
                        1,
                        f"Invalid command argument for {key}.",
                        Util.BailAction.EXIT,
                        json_output,
                    )
                else:
                    Util.bail_nvfwupd(
                        1, f"Invalid command argument for {key}.", Util.BailAction.EXIT
                    )
        return None

    @staticmethod
    def get_sanitizer(log_config, enabled=True):
        """
        Returns a LogSanitizer object based on the given config.
        If enabled is False, returns an "empty" sanitizer which returns the string as is
        Parameters:
            log_config Log configuration
            enabled Boolean value indicating if log sanitization is enabled
        Returns:
            A LogSanitizer object based on the input config
            or an empty sanitizer object if enabled is false
        """
        if not enabled or log_config is None:
            return LogSanitizer(string_list=[], additional_regex=[])
        filter_list = []
        cred_fields = [
            "BMC_IP",
            "BMC_USERNAME",
            "BMC_PASSWORD",
            "HOST_IP",
            "HOST_USERNAME",
            "HOST_PASSWORD",
            "RF_User",
            "RF_Pass",
            "BMC_SSH_USERNAME",
            "BMC_SSH_PASSWORD",
            "HMC_IP",
            "user",
            "password",
            "ip",
        ]
        for field in cred_fields:
            if (
                field in log_config
                and log_config.get(field)
                and isinstance(log_config[field], (str, int))
            ):
                filter_list.append(log_config[field])
        return LogSanitizer(string_list=filter_list)

    @staticmethod
    def sanitize_log(data):
        """
        Sanitize Log
        Parameter:
            data String to be sanitized
        Returns:
            The string data sanitized or
            the string data unsanitized if sanitization is disabled
        """
        if Util.is_sanitize is False:
            return data
        logger = Util.get_sanitizer(Util.sanitize_config)
        return logger.sanitize(str(data))

    @staticmethod
    def target_platform_supported(target_access, platform_type):
        """
        Check platform support
        Parameters:
            target_access Servertype passed in the configuration file
            platform_type DUT Access class
        Returns:
            None if the target platform is supported or
            an error message if the target platform is a supported platform,
            but is not communicating in an expected manner
        """
        if target_access is not None and isinstance(target_access, str):
            target_access = target_access.lower()
        if target_access in [
            "dgx",
            "hgx",
            "gb200",
            "hgxb100",
            "mgx-nvl",
            "gb200switch",
        ]:
            if platform_type not in ["BMCLoginAccess", "BMCPortForwardAccess"]:
                return (
                    f"Configured target platform is {target_access} "
                    f"but target does not support Redfish service."
                )
        else:
            return None

    @staticmethod
    def bail_nvfwupd(error_code, msg="", action=BailAction.EXIT, print_json=None):
        """
        Exit program or print dividers with given error code and message
        Parameters:
            error_code Error code to exit the program
            msg String Error message
            action Exit, Print Divider, or Do Nothing Bail action
            print_json Optional JSON Dictionary used for JSON Mode and Prints
        """

        if len(msg) > 0:
            if print_json and error_code != 0:
                print_json["Error"].append(msg)
                print_json["Error Code"] = error_code
            elif not print_json:
                print(msg)

        if action == Util.BailAction.EXIT:
            if print_json:
                print_json["Error Code"] = error_code
                json_formatted_str = json.dumps(print_json, indent=4)
                print(json_formatted_str)
            else:
                print(f"Error Code: {error_code}")
            sys.exit(error_code)
        else:
            if action == Util.BailAction.PRINT_DIVIDER:
                if not print_json:
                    print("-" * 120)
            elif action == Util.BailAction.DO_NOTHING:
                pass

    @staticmethod
    def bail_nvfwupd_threadsafe(
        error_code,
        msg="",
        action=BailAction.EXIT,
        print_json=None,
        parallel_update=False,
    ):
        """
        Exit program with given error code and message. Does
        not allow program exit during parallel updates
        Parameters:
            error_code Error code to exit the program
            msg String Error message
            action Exit, Print Divider, or Do Nothing Bail action
            print_json Optional JSON Dictionary used for JSON Mode and Prints
            parallel_update Boolean value, True if doing a parallel update
        """

        if parallel_update:
            # Util.BailAction.EXIT not allowed during parallel updates
            if action is None or action == Util.BailAction.EXIT:
                Util.bail_nvfwupd(
                    error_code, msg, Util.BailAction.DO_NOTHING, print_json
                )
            else:
                Util.bail_nvfwupd(error_code, msg, action, print_json)
        else:
            Util.bail_nvfwupd(error_code, msg, action, print_json)

    @staticmethod
    def check_duplicate_item(data: list):
        """
        Check if the provided list contains duplicate items.

        Parameters:
            data (list): The list to check for duplicates.
        Returns:
            True if there are duplicates in the list
            False otherwise.
        """
        return len(data) != len(set(data))

    @staticmethod
    def compare_dict(data, result, seen):
        """
        Compare two dicts
        Parameters:
            data Task Dictionary of Messages
            result List of results
            seen Stored dictionary of previous values
        Returns:
            A list of key value pairs from messages and a dictionary of used
            keys and values
        """
        temp_list = []
        for item in data:
            temp_list.append({item["MessageId"]: item["Message"]})

        for l_item in temp_list:
            key, value = next(iter(l_item.items()))
            if key not in seen:
                seen[key] = [value]
                result.append({key: value})
            else:
                if value not in seen[key]:
                    seen[key].append(value)
                    result.append({key: value})
        return result, seen

    @staticmethod
    def wrap_text(text, width):
        """
        Wrap the text based on the provided width
        Parameters:
            text String text to wrap
            width Maximum numerical width of wrapped lines
        Returns:
            Wrapped text based on the provided width
        """
        wrapped_line = textwrap.wrap(str(text), width)
        return "\n".join(line.ljust(width) for line in wrapped_line)
