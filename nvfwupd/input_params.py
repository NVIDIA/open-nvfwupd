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
"""input parameters for nvfwupd"""
import copy


# pylint: disable=too-few-public-methods
class TaskId:
    """
    Class used for task id tracking
    ...
    Attributes
    ----------
    task_id : str
        Task id from the system being updated
    status : bool
        True if the system was reachable
    response_dict : dict
        Update task response dictionary

    """

    def __init__(self, task_id, status=None, response_dict=None):
        """
        Task Id Class Constructor
        Parameters:
            task_id The task id of an ongoing update
            status True if the system was reachable, otherwise False
            response_dict The response dictionary for the task id
        """
        self.task_id = task_id
        self.status = status
        self.response_dict = response_dict


# pylint: disable=too-many-instance-attributes
class InputParams:
    """
    Base class to implement input params for nvfwupd
    ...
    Attributes
    ----------
    target_ip : Namespace
        Namespace that contains ip, username, password. May
        also contain port, servertype, package, update parameters,
        and systemname.
    ip : str
        System IP address
    package_parser : FirmwarePkg
        Initialized PLDM or TarPkg class parser for acquiring package
        information
    cmd_args : argparse.Namespace
        Namespace containing passed in command arguments
    package_name : str
        File path of an update package
    special : dict
        Dictionary of special update parameters such as specific firmware
        target
    json_dict : dict
        Dictionary used for json mode output and error printing
    task_id_list : list
        List of update task ids associated with a single system
    rf_target : RFTarget
        Initialized target communication class for a system
    system_name : str
        Optional user defined system name for printing

    """

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        target_ip,
        ip,
        cmd_args,
        package_parser=None,
        package=None,
        special=None,
        json_dict=None,
        system_name=None,
    ):
        """
        Input Parameters Class Constructor
        Parameters:
            target_ip Target Namespace containing ip, username, password
            ip System IP Address
            cmd_args Parsed input command arguments
            package_parser Initialized package parser for the update package
            package The name of the update package
            special JSON Update Parameters for the firmware update
            json_dict Optional JSON Dictionary used for JSON Mode and Prints
            system_name Optional user defined string system name
        """
        self.target_ip = target_ip
        self.ip = ip
        self.package_parser = package_parser

        # must use a deep copy of cmd_args in this case
        self.cmd_args = copy.deepcopy(cmd_args)
        self.package_name = package
        self.special = special
        self.json_dict = copy.deepcopy(json_dict)

        # params used for task tracking
        self.task_id_list = None
        self.rf_target = None
        self.system_name = system_name
