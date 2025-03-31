# OPEN-NVFWUPD

> SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
>
> SPDX-License-Identifier: Apache-2.0

## Description
open-nvfwupd is a tool designed for updating firmware components using OOB methods on NVIDIA server platforms.

## Features
- Ability to identify active system component firmware versions and compare to given PLDM .fwpkg firmware package versions.
    - **Dry Run** : Show firmware versions for OOB updatable components before a firmware update
- Update component firmware using OOB methods.
    - **Platform Support** : Support for GB200 NVL and DGX systems.
    - **Monitored Update** : Default behavior monitors a firmware update task to completion.
    - **Background Update** : Optional update task launch and manual monitoring.
    - **Parallel Update** : Launch updates on multiple systems at once using the yaml configuration file.

## Prerequisites

Before you begin, ensure you have met the following requirements:

- You have installed the correct version of Python. This project requires **Python 3.10** or higher. You can check your Python version by using the command `python --version` or `python -V` in your terminal.
- You have installed git-lfs, git large file system.
```shell
sudo apt-get install git-lfs
git lfs install
```
- Install all Python modules listed in the requirements.txt file

## See Running System Firmware Versions vs a PLDM Package

Run nvfwupd.py alongside the target system's ip address, username, password and servertype using the show_version command with a .fwpkg component bundle. This will show a system's running firmware versions alongside any package versions for any components present.

```shell
python3 nvfwupd.py -t ip=<system_ip> user=<username> password=<password> servertype=<servertype i.e GB200> show_version -p <package_name>

System Model: GB200 NVL
Part number: 699-24764-0001-TS3
Serial number: 1333124010099
Packages: ['GB200-P4975_0009_241117.1.0_custom']
Connection Status: Successful

Firmware Devices:
AP Name                                  Sys Version                    Pkg Version                    Up-To-Date
-------                                  -----------                    -----------                    ----------
CX7_0                                    28.42.1230                     N/A                            No        
CX7_1                                    28.42.1230                     N/A                            No        
CX7_2                                    28.42.1230                     N/A                            No        
CX7_3                                    28.42.1230                     N/A                            No        
FW_BMC_0                                 GB200Nvl-25.01-E               N/A                            No        
FW_CPLD_0                                0x00 0x0b 0x03 0x04            N/A                            No        
FW_CPLD_1                                0x00 0x0b 0x03 0x04            N/A                            No        
FW_CPLD_2                                0x00 0x10 0x01 0x0f            N/A                            No        
FW_CPLD_3                                0x00 0x10 0x01 0x0f            N/A                            No        
FW_ERoT_BMC_0                            01.04.0008.0000_n04            N/A                            No        
NIC_0                                    32.41.1300                     N/A                            No        
NIC_1                                    32.41.1300                     N/A                            No        
HGX_FW_BMC_0                             GB200Nvl-25.01-E               GB200Nvl-24.10-9               Yes       
HGX_FW_CPLD_0                            0.1C                           0.1C                           Yes       
HGX_FW_CPU_0                             02.03.19                       02.03.07                       Yes       
HGX_FW_CPU_1                             02.03.19                       02.03.07                       Yes       
HGX_FW_ERoT_BMC_0                        01.04.0008.0000_n04            01.03.0250.0000_n04            Yes       
HGX_FW_ERoT_CPU_0                        01.04.0008.0000_n04            01.03.0250.0000_n04            Yes       
HGX_FW_ERoT_CPU_1                        01.04.0008.0000_n04            01.03.0250.0000_n04            Yes       
HGX_FW_ERoT_FPGA_0                       01.04.0008.0000_n04            01.03.0250.0000_n04            Yes       
HGX_FW_ERoT_FPGA_1                       01.04.0008.0000_n04            01.03.0250.0000_n04            Yes       
HGX_FW_FPGA_0                            1.20                           1.16                           Yes       
HGX_FW_FPGA_1                            1.20                           1.16                           Yes       
HGX_FW_GPU_0                             97.00.82.00.18                 97.00.52.00.02                 Yes       
HGX_FW_GPU_1                             97.00.82.00.18                 97.00.52.00.02                 Yes       
HGX_FW_GPU_2                             97.00.82.00.18                 97.00.52.00.02                 Yes       
HGX_FW_GPU_3                             97.00.82.00.18                 97.00.52.00.02                 Yes       
HGX_InfoROM_GPU_0                        G548.0201.00.03                N/A                            No        
HGX_InfoROM_GPU_1                        G548.0201.00.03                N/A                            No        
HGX_InfoROM_GPU_2                        G548.0201.00.03                N/A                            No        
HGX_InfoROM_GPU_3                        G548.0201.00.03                N/A                            No        
HGX_PCIeSwitchConfig_0                   01170424                       N/A                            No        
------------------------------------------------------------------------------------------------------------------------
Error Code: 0

```
Four columns are displayed including the component AP Name, running system firmware version, package version (if component is present in package) and if the component is
up to date.


## Update System Firmware

Run nvfwupd.py alongside the target system's ip address, username, password and servertype using the update_fw command with a .fwpkg component bundle. Additionally, for certain platform types such as GB200, an additional special update json file is required to select the proper update target.

Special Update File

In order to update GB200 BMC Tray, the special update file will require the following contents:

```shell
{
    "Targets": []
}
```

In order to update GB200 Compute Tray, the special update file will require the following contents:

```shell
{
    "Targets": ["/redfish/v1/Chassis/HGX_Chassis_0"]
}
```

```shell
python3 nvfwupd.py -t ip=<system_ip> user=<username> password=<password> servertype=<servertype i.e GB200> update_fw -p <package_name> -s <special_update_file.json>
Updating ip address: ip=XXXX
FW package: ['nvfw_GB200-P4975_0009_241117.1.0_custom_dbg-signed.fwpkg']
Ok to proceed with firmware update? <Y/N>
y
{"@odata.id": "/redfish/v1/TaskService/Tasks/HGX_0", "@odata.type": "#Task.v1_4_3.Task", "Id": "HGX_0", "TaskState": Running", "TaskStatus": "OK"}
FW update started, Task Id: HGX_0
Wait for Firmware Update to Start...
TaskState: Running
PercentComplete: 20
TaskStatus: OK
TaskState: Running
PercentComplete: 40
TaskStatus: OK
TaskState: Completed
PercentComplete: 100
TaskStatus: OK
Firmware update successful!
Overall Time Taken: 0:09:46
Refer to 'NVIDIA Firmware Update Document' on activation steps for new firmware to take effect.
-----------------------------------------------------------------------------------
Error Code: 0

```

The update task is launched and monitored until full completion. After performing a firmware update of a component, or a full bundle, complete an AC power cycle to activate the new firmware. It can take up to five minutes for the BMC and the Redfish service to come up after the power cycle is complete. To check new system versions after the BMC Redfish service is back, run the show version command.

## Contributing to OPEN-NVFWUPD

Refer to CONTRIBUTING.md for instructions.