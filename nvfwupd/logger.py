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
Provide utilities and helper functions consumed by
nvfwupd.
"""

import os
import time
from pprint import pprint


class Logger:
    """
    Class with static methods
    ...
    Attributes
    ----------
    LOG_FILE : str
        Pathname of a log file
    JSON : bool
        True if JSON printing is enabled
    VERBOSE : bool
        True if verbose printing is enabled

    Methods
    -------
    debug_print(*args, **kwargs) :
        Prints debug messages if NVFWUPD_DEBUG is set in
        environment
    verbose_log(msg, log_file_only=False) :
        Prints verbose log messages if the verbose flag is
        set in input options
    cli_log(log_msg, log_file_only=False) :
        Appends a log message to the log file
    indent_print(text, indent_level = 2, log=False) :
        Helper function to print with indents
    debug_dict_print(my_dict) :
        Pretty print the provided dictionary if
        NVFWUPD_DEBUG is set

    """

    LOG_FILE = os.path.expanduser("nvfwupd_log.txt")
    JSON = False
    VERBOSE = False

    def __init__(self, log_file="nvfwupd_log.txt", json=False, verbose=False):
        """
        Logger Class Constructor
        Parameters:
            log_file The log file path
            json Boolean value for enabling the use of JSON mode
            verbose Boolean value for enabling verbose logging
        """
        Logger.LOG_FILE = os.path.expanduser(log_file)
        Logger.JSON = json
        Logger.VERBOSE = verbose

    @staticmethod
    def debug_print(*args, **kwargs):
        """
        Output debug message if DEBUG environ is set.
        To turn on debugging:
        # export DEBUG=1; main.py ....
        Parameters:
            args Variable Number of Arguments
            kwargs Variable Number of Keyword Arguments
        """

        if "NVFWUPD_DEBUG" in os.environ:
            print(f"DEBUG: {args} {kwargs}")

        if Logger.VERBOSE:
            Logger.cli_log(f"DEBUG: {args} {kwargs}", True)

    @staticmethod
    def verbose_log(msg, log_file_only=False):
        """
        If VERBOSE flag is set, print and log the message
        Parameters:
            msg String message for printing or logging
            log_file_only Boolean value to log a message only without printing
        """
        if Logger.VERBOSE:
            Logger.cli_log(msg, log_file_only)

    @staticmethod
    def cli_log(log_msg, log_file_only=False):
        """
        Append log message to cli log file
        Parameters:
            log_msg String message for printing or logging
            log_file_only Boolean value to log a message only without printing
        """

        log_file = Logger.LOG_FILE

        file_handle = None
        try:
            # pylint: disable=consider-using-with
            if os.path.exists(log_file) is False:
                file_handle = open(log_file, "w+", encoding="utf-8")
            else:
                file_handle = open(log_file, "a+", encoding="utf-8")
        # pylint: disable=broad-exception-caught
        except Exception as err:
            if Logger.JSON is False:
                print(f"ERROR: there seems to be an issue with the log file{err}")

        if file_handle is not None:
            localtime = time.asctime(time.localtime(time.time()))
            file_handle.write(f"{localtime} : {log_msg}\n")

            file_handle.close()
        # if we need to print in json format or we dont need it
        if Logger.JSON is False and log_file_only is False:
            print(log_msg)

    @staticmethod
    def indent_print(text, indent_level=2, log=False):
        """
        Helper function for indent printing
        Parameters:
            text String message for printing or logging
            indent_level Number of spaces for the message
            log Boolean value to log a message only without printing
        """

        spaces = " " * indent_level

        Logger.cli_log(f"{spaces}{text}", log)

    @staticmethod
    def debug_dict_print(my_dict):
        """
        pprint given dictionary
        Parameter:
            my_dict Dictionary to print if NVFWUPD_DEBUG is set
        """

        if "NVFWUPD_DEBUG" in os.environ:
            pprint(my_dict)
