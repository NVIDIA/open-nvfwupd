Using the Tool When an Unknown Platform Error Occurs
==============================================================

When an unknown platform error occurs on a GB200 NVL system, to resolve the error, in the ``--target`` option, use the servertype suboption.

.. note::
    
    The suboption can be used with **all** commands that use ``--target`` option (see the sample output). 
    
    For GB200 NVL platforms use ``servertype=GB200``.                        

.. code-block::

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
