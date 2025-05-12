GB200 NVL Update Examples
-------------------------

The following must be noted for the firmware update mechanism for GB200 NVL:

-  GB200 NVL uses three fwpkg bundles.

    - The **P4972** packages are for the BMC tray.
    - The **P4975** packages are for the compute tray.
    - The **P4978** packages are for the switch tray.

-  The update targets file are passed with the ``–s`` option, which is always required to specify the update target for the BMC and compute trays (refer to the sample outputs in the next section).

-  To downgrade the GB200 NVL BMC or compute tray firmware, set the ``ForceUpdate`` flag in the update target JSON file that is passed with the ``–s`` option. Downgrades are allowed by default for the GB200 NVL Switch tray.

Updating the GB200 NVL BMC Tray
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To update the complete BMC tray:

1. Create a JSON file like the ``BMC_Full.json`` file in the example.

2. Use the ``nvfwupd.py`` tool and run the ``update_fw`` command.

In the package name, the BMC tray update packages can be identified by ``GB200-P4972``.

1. After the update successfully completes, to activate the firmware, complete a power cycle.

2. After the BMC is up and the Redfish service is running, to determine whether the BMC tray components were updated and they match the versions in the package, run the ``show_version`` command.

Here is the output:

.. code-block::

    $ cat BMC_Full.json

    {
        "Targets": []
    }

    $ nvfwupd.py -t ip=<BMC IP> user=*** password=*** update_fw -s BMC_Full.json -p nvfw_GB200-P4972_0004_240808.1.1_custom_prod-signed.fwpkg

    Updating ip address: ip=XXXX
    FW package: ['nvfw_GB200-P4972_0004_240808.1.1_custom_prod-signed.fwpkg']
    Ok to proceed with firmware update? <Y/N>
    y
    {"@odata.id": "/redfish/v1/TaskService/Tasks/0", "@odata.type": "#Task.v1_4_3.Task", "Id": "0", "TaskState": "Running", "TaskStatus": "OK"}
    FW update started, Task Id: 0
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
    Overall Time Taken: 0:10:41
    Refer to 'NVIDIA Firmware Update Document' on activation steps for new firmware to take effect.
    ---------------------------------------------------------------------------------------
    Error Code: 0

.. note::
    For open-nvfwupd 1.0.1 and later, the ``-s`` option is no longer required when updating the entire BMC tray. The default "Targets" are all components without ``force_update``.

Updating the GB200 NVL Compute Tray
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To update the compute tray:

1. Create a JSON file, like the ``Compute_Full.json`` file, in the example.

2. Use the ``nvfwupd.py`` tool and run the ``update_fw`` command.

In the package name, the Compute tray update packages can be identified by ``GB200-P4975``.

1. After the update successfully completes, to activate the firmware, complete an AC cycle.

2. After the BMC is up and the Redfish service is running again, to determine whether the compute tray components were updated and they match the versions in the package, run the ``show_version`` command.

Here is an example:

.. code-block::

    $ cat Compute_Full.json

    {
        "Targets": ["/redfish/v1/Chassis/HGX_Chassis_0"]
    }

    $ nvfwupd.py -t ip=<BMC IP> user=*** password=*** servertype=GB200 update_fw -s Compute_Full.json -p nvfw_GB200-P4975_0004_240808.1.0_custom_prod-signed.fwpkg

    Updating ip address: ip=XXXX
    FW package: ['nvfw_GB200-P4975_0004_240808.1.0_custom_prod-signed.fwpkg']
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

GB200 NVL Firmware Downgrades Using the Force Update Option
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To downgrade the GB200 NVL firmware, you must use the force update multipart option, which can be set in the update parameters JSON file targets and are passed in the JSON file with the ``–s`` option. If you try firmware updates as described in the previous sections, and you see the following error message in the firmware update log:

**Component comparison stamp is lower than the firmware component comparison stamp in the FD.**

retry with a force firmware update but change the Targets value based on the tray you want to force update.

For example, to force update the BMC tray on the target:

1. Create a JSON file, like the ``force_BMC_Full.json`` file, in the example.

2. Run the tool.

Here is an example:

.. code-block::
    :emphasize-lines: 4

    $ cat force_BMC_Full.json

    {
        "ForceUpdate":true,
        "Targets":[]

    }

    $ nvfwupd.py -t ip=<BMC IP> user=*** password=**** servertype=GB200 update_fw -s force_BMC_Full.json -p nvfw_GB200-P4972_0004_240808.1.1_custom_prod-signed.fwpkg

    Updating ip address: ip=XXXX
    FW package: ['nvfw_GB200-P4972_0004_240808.1.1_custom_prod-signed.fwpkg']
    Ok to proceed with firmware update? <Y/N>
    y
    {"@odata.id": "/redfish/v1/TaskService/Tasks/0", "@odata.type": "#Task.v1_4_3.Task", "Id": "0", "TaskState": "Running", "TaskStatus": "OK"}
    FW update started, Task Id: 0
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
    Overall Time Taken: 0:10:38

    Refer to 'NVIDIA Firmware Update Document' on activation steps for new firmware to take effect.
    ---------------------------------------------------------------------------------------
    Error Code: 0

GB200 NVL Firmware Updates for Selected Components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To complete a firmware update of a component:

1. Identify the inventory name of the component.

   -  The ``show_version`` option can be used to list all the components in the inventory with their current versions.

   -  Components names that are prefixed with **HGX** can be updated using a compute tray package, and the rest of the components will need the BMC tray package.

.. note ::

    Ignore the HGX H100 System Model in the following output. The device under test had an incorrect FRU programming.

.. code-block ::

    $ nvfwupd.py -t ip=<BMC IP> user=*** password=*** servertype=GB200 show_version -p nvfw_GB200-P4972_0004_240808.1.1_custom_prod-signed.fwpkg nvfw_GB200-P4975_0004_240808.1.0_custom_prod-signed.fwpkg

    System Model: NVIDIA HGX H100
    Part number: $TRAY_PART_NUMBER
    Serial number: $TRAY_SERIAL_NUMBER
    Packages: ['GB200-P4972_0004_240808.1.1_custom', 'GB200-P4975_0004_240808.1.0_custom']
    Connection Status: Successful
    Firmware Devices:
    AP Name              Sys Version                 Pkg Version         Up-To-Date
    -------              -----------                 -----------         ---------
    FW_BMC_0             gb200nvl-24.08-2            GB200Nvl-24.08-2    Yes
    FW_CPLD_0            0.00                        N/A                 No
    FW_CPLD_1            0.00                        N/A                 No
    FW_CPLD_2            0.00                        N/A                 No
    FW_CPLD_3            0.00                        N/A                 No
    FW_ERoT_BMC_0        01.03.0183.0000_n04         01.03.0183.0000_n04 Yes
    NIC_0                28.98.9122                  N/A                 No
    UEFI                 buildbrain-gcid-37009178    N/A                 No
    HGX_FW_BMC_0         gb200nvl-24.08-2            GB200Nvl-24.08-2    Yes
    HGX_FW_CPLD_0        0.112                       0.1C                Yes
    HGX_FW_CPU_0         02.02.02                    02.02.02            Yes
    HGX_FW_CPU_1         02.02.02                    02.02.02            Yes
    HGX_FW_ERoT_BMC_0    01.03.0183.0000_n04         01.03.0183.0000_n04 Yes
    HGX_FW_ERoT_CPU_0    01.03.0183.0000_n04         01.03.0183.0000_n04 Yes
    HGX_FW_ERoT_CPU_1    01.03.0183.0000_n04         01.03.0183.0000_n04 Yes
    HGX_FW_ERoT_FPGA_0   01.03.0183.0000_n04         01.03.0183.0000_n04 Yes
    HGX_FW_ERoT_FPGA_1   01.03.0183.0000_n04         01.03.0183.0000_n04 Yes
    HGX_FW_FPGA_0        312e3041                    1.0A                Yes
    HGX_FW_FPGA_1        312e3041                    1.0A                Yes
    HGX_FW_GPU_0         97.00.0c.00.00              97.00.0D.00.00      No
    HGX_FW_GPU_1         97.00.0c.00.00              97.00.0D.00.00      No
    HGX_FW_GPU_2         97.00.0c.00.00              97.00.0D.00.00      No
    HGX_FW_GPU_3         97.00.0c.00.00              97.00.0D.00.00      No
    HGX_InfoROM_GPU_0    g548.0201.01.02             N/A                 No
    HGX_InfoROM_GPU_1    g548.0201.01.02             N/A                 No
    HGX_InfoROM_GPU_2    g548.0201.01.02             N/A                 No
    HGX_InfoROM_GPU_3    g548.0201.01.02             N/A                 No
    ------------------------------------------------------------------------------------
    Error Code: 0

2. After identifying the inventory name, create the JSON file with the Redfish inventory URI of that component (``/redfish/v1/UpdateService/FirmwareInventory/<component name>``).

   The example in step 4 shows a sample ``CPU.json`` file that is used to update only the ``HGX_FW_CPU_0`` component on the tray.

3.  Run the ``update_fw`` command with the ``CPU.json`` file and compute tray bundle as the inputs.

4.  To perform a downgrade, add the ``"ForceUpdate": true`` field to this JSON file.

.. code-block:: 

    $ cat CPU.json

    {
        "Targets":["/redfish/v1/UpdateService/FirmwareInventory/HGX_FW_CPU_0"]
    }

    $ nvfwupd.py --target ip=<BMC IP> user=*** password=*** servertype=GB200 update_fw -s CPU.json -p nvfw_GB200-P4975_0004_240717.1.0_custom_prod-signed.fwpkg

    Updating ip address: ip=XXXX
    FW package: ['nvfw_GB200-P4975_0004_240717.1.0_custom_prod-signed.fwpkg']
    Ok to proceed with firmware update? <Y/N>
    y
    {"@odata.id": "/redfish/v1/TaskService/Tasks/HGX_3", "@odata.type": "#Task.v1_4_3.Task", "Id": "HGX_3", "TaskState": Running", "TaskStatus": "OK"}
      FW update started, Task Id: HGX_3
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

    Overall Time Taken: 0:09:50

    Refer to 'NVIDIA Firmware Update Document' on activation steps for new firmware to take effect.
    ---------------------------------------------------------------------------------------
    Error Code: 0


Activating the Firmware
~~~~~~~~~~~~~~~~~~~~~~~

After performing firmware update of a component, or a full bundle, complete an AC power cycle to activate the new firmware. It can take up to five minutes for the BMC and Redfish service to come up after power cycle is complete. To check new system versions after the BMC Redfish service is back, run the show version command.

GB200 NVL Switch Tray Update
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

..  table:: GB200 NVL Switch Tray Packages
    :name: gb200_nvl_switch_tray_packages
    :widths: auto

    +------------------------+-------------------------------------+
    | **Package ID**         | **Components**                      |
    +------------------------+-------------------------------------+
    | nvfw_GB200-P4978_0004  | BMC, EROT, FPGA                     |
    +------------------------+-------------------------------------+
    | nvfw_GB200-P4978_0006  | SBIOS, EROT                         |
    +------------------------+-------------------------------------+
    | nvfw_GB200-P4978_0007  | CPLD                                |
    +------------------------+-------------------------------------+

Displaying the Current Versions of the Switch Tray Components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To display the current versions of switch tray components, run the show_version command. The **System Version** column shows the current firmware versions on the system and the **Package** version column shows the versions in the packages after you run the ``–p`` option.

.. code-block::

    $ nvfwupd.py -t ip=<NVOS IP> user=*** password=*** servertype=gb200switch show_version -p nvfw_GB200-P4978_0004_250213.1.0_prod-signed.fwpkg nvfw_GB200-P4978_0006_250205.1.0_prod-signed.fwpkg nvfw_GB200-P4978_0007_250121.1.2_custom_prod-signed.fwpkg
    
    System Model: N5110_LD
    Part number: 920-9K36F-00MV-QS1
    Serial number: MT2438X01107
    Packages: ['GB200-P4978_0004_250213.1.0', 'GB200-P4978_0006_250205.1.0', 'GB200-P4978_0007_250121.1.2_custom']
    Connection Status: Successful

    Firmware Devices:
    AP Name            Sys Version                Pkg Version                 Up-To-Date
    -------            -----------                -----------                 ----------
    ASIC               35.2014.1660               N/A                         No        
    BIOS               0ACTV_00.01.012            00.01.012                   Yes       
    BMC                88.0002.0930               88.0002.0930                Yes       
    CPLD1              CPLD000370_REV0500         CPLD000370_REV0500          Yes       
    CPLD2              CPLD000377_REV0600         CPLD000377_REV0600          Yes       
    CPLD3              CPLD000373_REV0500         CPLD000373_REV0500          Yes       
    CPLD4              CPLD000390_REV0200         CPLD000390_REV0200          Yes       
    EROT               01.04.0008.0000_n04        01.04.0008.0000_n04         Yes       
    EROT-ASIC1         01.04.0008.0000_n04        01.04.0008.0000_n04         Yes       
    EROT-ASIC2         01.04.0008.0000_n04        01.04.0008.0000_n04         Yes       
    EROT-BMC           01.04.0008.0000_n04        01.04.0008.0000_n04         Yes       
    EROT-CPU           01.04.0008.0000_n04        01.04.0008.0000_n04         Yes       
    EROT-FPGA          01.04.0008.0000_n04        01.04.0008.0000_n04         Yes       
    FPGA               0.1A                       0.1A                        Yes       
    SSD                CE00A400                   N/A                         No        
    transceiver        N/A                        N/A                         No        
    ------------------------------------------------------------------------------------
    Error Code: 0

.. note::
    The ``SSD``, ``transceiver``, and ``ASIC`` can only be updated using inband update methods. These components cannot be updated using open-nvfwupd.

Full Bundle Firmware Update for GB200 NVL Switch Components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To update all components of GB200 NVL Switch Tray for a bundle, the bundle can be passed without any specified targets. After the full update has finished, you must activate the firmware.

1. To update the ``BMC``, the ``FPGA``, and the ``ERoT`` use the ``fwpkg`` file with ``0004`` sub-string in the name.

2. Pass the .fwpkg file as input to the update_fw command as in the following example.

.. code-block::

    $ ./nvfwupd.py -t ip=<NVOS IP> user=**** password=**** servertype=gb200switch update_fw -p nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg

    Updating ip address: ip=XXXX
    FW package: ['nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg']
    Ok to proceed with firmware update? <Y/N>
    y
    The following targets will be updated ['BMC', 'EROT', 'FPGA']
    Update file nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg was uploaded successfully

    Starting FW update for: BMC

    FW update task was created with ID 2

    Status for Job Id 2:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 2:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 2:
    {'detail': 'Firmware nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'action_success',
    'status': 'Firmware nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Update file nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg was uploaded successfully

    Starting FW update for: EROT

    FW update task was created with ID 3

    Status for Job Id 3:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 3:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 3:
    {'detail': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 3:
    {'detail': 'Firmware nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'action_success',
    'status': 'Firmware nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Update file nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg was uploaded successfully

    Starting FW update for: FPGA

    FW update task was created with ID 4

    Status for Job Id 4:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 4:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 4:
    {'detail': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 4:
    {'detail': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 4:
    {'detail': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 4:
    {'detail': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 4:
    {'detail': 'Firmware nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'action_success',
    'status': 'Firmware nvfw_GB200-P4978_0004_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    ------------------------------------------------------------------------------------------------------------------------

    Error Code: 0

3.  Update the ``ERoT`` and ``BIOS`` using the ``fwpkg`` file with ``0006`` sub-string in the name.

.. code-block:: 

    $ ./nvfwupd.py -t ip=<NVOS IP> user=**** password=**** servertype=gb200switch -v update_fw -p nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg

    Updating ip address: ip=XXXX
    FW package: ['nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg']
    Ok to proceed with firmware update? <Y/N>
    y
    The following targets will be updated ['BIOS', 'EROT']
    Update file nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg was uploaded successfully
    Starting FW update for: BIOS
    FW update task was created with ID 2

    Status for Job Id 2:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 2:

    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 2:
    {'detail': 'Installing firmware: '
    'nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
    'nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 2:
    {'detail': 'Installing firmware: '
    'nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
    'nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 2:
    {'detail': 'Firmware nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'action_success',
    'status': 'Firmware nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Update file nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg was uploaded successfully

    Starting FW update for: EROT
    FW update task was created with ID 3

    Status for Job Id 3:

    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 3:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 3:
    {'detail': 'Firmware nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'action_success',
    'status': 'Firmware nvfw_GB200-P4978_0006_240926.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    ------------------------------------------------------------------------------------------------------------------------

    Error Code: 0

4. Update the ``CPLD`` using the ``fwpkg`` file with ``0007`` sub-string in the name.

.. code-block::

    $ ./nvfwupd.py -t ip=<NVOS IP> user=**** password=**** servertype=gb200switch update_fw -p nvfw_GB200-P4978_0007_241126.1.1_custom_dbg-signed.fwpkg

    Updating ip address: ip=XXXX
    FW package: ['nvfw_GB200-P4978_0007_241126.1.1_custom_dbg-signed.fwpkg']
    Ok to proceed with firmware update? <Y/N>
    y
    The following targets will be updated ['CPLD1']
    Update file /tmp/tmpyl1jpt65nvfwupd/CPLD_Debug_000370_REV0202_000377_REV0409_000373_REV0205_000390_REV0103_91605435_image.bin was uploaded successfully
    Starting FW update for: CPLD1
    FW update task was created with ID 35
    Status for Job Id 35:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 35:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': '',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 35:
    {'detail': 'Installing firmware: '
            'CPLD_Debug_000370_REV0202_000377_REV0409_000373_REV0205_000390_REV0103_91605435_image.vme',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
            'CPLD_Debug_000370_REV0202_000377_REV0409_000373_REV0205_000390_REV0103_91605435_image.vme',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 35:
    {'detail': 'Installing firmware: '
            'CPLD_Debug_000370_REV0202_000377_REV0409_000373_REV0205_000390_REV0103_91605435_image.vme',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
            'CPLD_Debug_000370_REV0202_000377_REV0409_000373_REV0205_000390_REV0103_91605435_image.vme',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 35:
    {'detail': 'Installing firmware: '
            'CPLD_Debug_000370_REV0202_000377_REV0409_000373_REV0205_000390_REV0103_91605435_image.vme',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
            'CPLD_Debug_000370_REV0202_000377_REV0409_000373_REV0205_000390_REV0103_91605435_image.vme',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    Status for Job Id 35:
    {'detail': 'Next reboot will perform a power cycle to load the new firmware',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'action_success',
    'status': 'Next reboot will perform a power cycle to load the new firmware',
    'timeout': 1800,
    'type': '',
    'warnings': []}

    ------------------------------------------------------------------------------------------------------------------------
    Error Code: 0

5. After the update for all packages is complete, to activate the installed versions, AC cycle the GB200 NVL Switch.

Targeted Firmware Updates for GB200 NVL Switch Components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To update a component in the GB200 NVL Switch Tray, use the ``–s`` or the ``--special`` option with the ``update_fw`` command shown in examples in step 2.

1. To update the ``BMC``, use the ``fwpkg`` file with ``0004`` sub-string in the name.

2. Create a JSON file, like ``targets.json`` in the following example, and pass these two files as input to the ``update_fw`` command as shown below.

.. code-block:: 

    $ cat targets.json
    {"Targets": ["BMC"]}

    $ ./nvfwupd.py -t ip=<NVOS IP> user=**** password=**** servertype=gb200switch update_fw -s targets.json -p nvfw_GB200-P4978_0004_240918.1.0_dbg-signed.fwpkg

    Updating ip address: ip=XXXX
    FW package: ['nvfw_GB200-P4978_0004_240918.1.0_dbg-signed.fwpkg']
    Ok to proceed with firmware update? <Y/N>
    y
    The following targets will be updated ['BMC']
    Update file nvfw_GB200-P4978_0004_240918.1.0_dbg-signed.fwpkg was uploaded successfully
    Starting FW update for: BMC
    FW update task was created with ID 10

    Status for Job Id 10:
    {'detail': '',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'start',
    'status': '',
    'timeout': 1200,
    'type': ''}

    Status for Job Id 10:
    {'detail': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240918.1.0_dbg-signed.fwpkg',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'running',
    'status': 'Installing firmware: '
    'nvfw_GB200-P4978_0004_240918.1.0_dbg-signed.fwpkg',
    'timeout': 1200,
    'type': ''}


    Status for Job Id 10:
    {'detail': 'Firmware nvfw_GB200-P4978_0004_240918.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'http_status': 200,
    'issue': [],
    'percentage': '',
    'state': 'action_success',
    'status': 'Firmware nvfw_GB200-P4978_0004_240918.1.0_dbg-signed.fwpkg '
    'installed successfully',
    'timeout': 1200,
    'type': ''}

    ---------------------------------------------------------------------------------------

    Error Code: 0

3. After the update for all desired components is complete, AC cycle the GB200 NVL Switch to activate the installed firmware.

4. To update any other component, replace the ``BMC`` in the ``targets.json`` file from the example above with the component name. To update the ``CPLD``, use a component name of ``CPLD1``.

5. Pass the ``targets.json`` and update package as in step 2.
