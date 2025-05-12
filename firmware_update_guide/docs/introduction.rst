
Introduction
============

An NVIDIA® Grace™ Blackwell™ server comprises Grace CPUs, optional GPUs, and a few other components (refer to table below). Application Programming (AP) components can be updated using Out-Of-Band (OOB) with Redfish APIs or using in-band with vendor-provided tools.

:ref:`The table below <grace-blackwell-ap-components>` lists the available Grace Blackwell AP components, the update methods, and where to find the instructions to update these components.

.. _grace-blackwell-ap-components:

.. list-table:: Grace Blackwell Components
    :widths: auto
    :header-rows: 1

    * - Component
      - OOB Bundle
      - In Band Update
    * - Entire Bundle
      - Y
      - N
    * - BMC ERoT
      - Y
      - N
    * - BMC
      - Y
      - N
    * - CPU ERoT
      - Y
      - N
    * - GPU
      - Y
      - N
    * - FPGA
      - Y
      - N

Supported Platforms
--------------------

The following platforms are supported in Grace Blackwell:

-  NVIDIA GB200 NVL, NVIDIA GB300 NVL


Updating Grace Blackwell Firmware
------------------------------

This section provides information about how to update the firmware using the nvfwupd tool.

Tool and Firmware Availability
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To determine the tool and firmware availability, complete the following steps:

1. To get a PLDM firmware package that is signed by NVIDIA, contact the Application Engineering (AE) Team.

2. Enter the following information:

   - BMC-IP address or hostname

   - User ID

   - password

The following python version and modules are required to run nvfwupd.py.

.. code-block::

  python>=3.10
  requests
  PyYAML
  paramiko
  scp
  tabulate

.. important::

   -  Any Linux distribution that supports the required python version and the listed python modules should be able to run ``open-nvfwupd``.

Command Syntax
--------------

.. code-block::

  Usage: nvfwupd.py [ global options ] <command>

  Global options:
      -t --target ip=<BMC IP> user=<BMC login id> password=<BMC password> port=<port num for port forwarding> servertype=<Type of server>
            BMC target comprising BMC IP address and BMC login credentials. servertype and port are optional. Valid value for servertype is one of [DGX, HGX, HGXB100, GB200, GB300, MGX-NVL, GB200Switch]

      -c --config Path for config file (optional).
            Configure tool behavior

      -v --verbose Chosen path for logfile (optional). Default path is current working directory.
            Increase verbosity

  Commands:
      help       Show tool help.                         

      version    Show tool version.                      

      <Global options...> show_version [ options... ]
          -p  --package                PLDM firmware package                                       
          -j  --json                   show output in JSON
          -s  --staged                 Show staged firmware versions                                  

      <Global options...> update_fw [ options... ]
          -p  --package                PLDM firmware package                                       
          -y  --yes                    Bypass firmware update confirmation prompt                  
          -b  --background             Exit without waiting for the update process to finish       
          -t  --timeout                API request timeout value in seconds                        
          -s  --special                Special Update json file                                    
          -d  --details                Show update progress in table format                        
          -j  --json                   show output in JSON. Must be paired with the -b background option, and always bypasses update confirmation prompt.
          -u  --staged_update          SPI Staged Update                                           
          -a  --staged_activate_update SPI and Activate Staged Update

      <Global options...> force_update [ options... ]
          enable|disable|status        enable, disable or check current force update value on target
          -j  --json                   show output in JSON                                         

      <Global options...> show_update_progress [ options... ]
          -i  --id                     List of Task IDs delimited by space                         
          -j  --json                   show output in JSON                                         


