.. _platform-agnostic-updates:

Platform-Agnostic Firmware Updates with nvfwupd Using the Config File
===============================================================================

open-nvfwupd supports input and platform-agnostic firmware updates through the YAML configuration file, which allows users to customize update methods and the Redfish URIs that used for the update.

Config File Parameters
----------------------

The tool supports various configuration parameters and ``BMC_IP``, ``RF_USERNAME`` and ``RF_PASSWORD`` are always mandatory. Here is a sample YAML file that explains each parameter:

.. code-block:: yaml

   # Define the target platform as one of HGX/DGX/GB200/GB300/HGXB100/MGX-NVL/GB200Switch.
   TargetPlatform: 'DGX'
   # Disable Sanitize Log, disabling Sanitize Log leads to print system IP and user credential to the logs and screen
   SANITIZE_LOG: False

   # Provide full path of firmware file(s) to be used for firmware update. Value is a list
   FWUpdateFilePath: 
   - "../packages/nvfw_DGX-H100_0005_231206.1.0_nightly.fwpkg"

   # Define URI for MultipartHttpPushUri (Optional override). 
   # Default value is taken from UpdateService
   MultipartHttpPushUri: '/redfish/v1/UpdateService/update-multipart'

   # HttpPushUri for PLDM Firmware Update (Optional override). 
   # Default value "/redfish/v1/UpdateService"
   HttpPushUri: '/redfish/v1/UpdateService'

   # Change if TaskServiceUri is different from default value below
   # Task id will always be taken from update response in update_fw or
   # from –i input in show_update_progress 
   TaskServiceUri: '/redfish/v1/TaskService/Tasks/'

   # Define differnt update methods. 
   # Valid values {'MultipartHttpPushUri', 'HttpPushUri'}
   FwUpdateMethod: "MultipartHttpPushUri"

   # Optional Parameter used with MultipartHttpPushUri update method
   # used to define dict of parameters for multipart FW update
   MultipartOptions:
   - ForceUpdate: True

   # Target IP address. BMC IP/NVOS Rest service IP/localhost for port forwarding
   BMC_IP: "1.1.1.1"
   RF_USERNAME: "user"
   RF_PASSWORD: "password"
   # Target port config if port forwarding is used.
   TUNNEL_TCP_PORT: "14443"

   # List of update targets. replaces -s/--special option input file. Value is list of target URIs
   # Use UpdateParametersTargets: {} for DGX empty JSON value used for full DGX update
   # Use UpdateParametersTargets: [] for GB200 NVL empty list used for BMC update
   UpdateParametersTargets:
   - "/redfish/v1/UpdateService/FirmwareInventory/CPLDMB_0"

   # Config for reset BMC parameters. Value is a dict.
   # Use ResetType: 'ResetAll' for DGX
   # Use ResetToDefaultsType: 'ResetAll' for HGX
   BMCResetParameters:
      ResetType: 'ResetAll'

   # Multi target input. Value is list of dicts.
   Targets:
   - BMC_IP: "1.1.1.1"
     RF_USERNAME: "user"
     RF_PASSWORD: "password"
     TUNNEL_TCP_PORT: "14443"
   - BMC_IP: "2.2.2.2"
     RF_USERNAME: "user"
     RF_PASSWORD: "password"
     TUNNEL_TCP_PORT: "14444"


Running nvfwupd Commands Using the Config File
----------------------------------------------

To use the tool and update a platform that supports MultipartHttpPushUri or HttpPushUri, but is not automatically identified by the tool or provide a platform that is not a supported error, a configuration file can be used to provide the input and customize the behavior.

Here is some additional information:

-  Support for ``show_version`` on an unknown platform is limited.

   If the TargetPlatform parameter is not in the config file, ``show_version`` will not match the firmware inventory to PLDM package contents. The **Pkg Version** and **Up-to-date** columns will be ``N/A`` and ``No`` respectively.

-  The make_upd_targets command is not supported with config file because the resulting JSON files cannot be used with the config file.

-  The config file takes update targets as a config file parameter, and because the tool is supposed to be used with a platform that is not known to the tool, the target list must be identified and verified by users **before** providing it as input.

Setting this parameter to another type can lead to unwanted issues on the platform.

.. code-block::

   $ cat config.yaml
   
   TargetPlatform: 'DGX'
   FWUpdateFilePath:
   - "../packages/nvfw_DGX-H100_0005_231206.1.0_nightly.fwpkg"
   # MultipartHttpPushUri: '/redfish/v1/UpdateService/update-multipart'
   FwUpdateMethod: "MultipartHttpPushUri"
   BMC_IP: "1.1.1.1"
   RF_USERNAME: "****"
   RF_PASSWORD: "******"
   BMCResetParameters:
   ResetToDefaultsType: 'ResetAll'
   
.. code-block::

   $ nvfwupd.py -c config.yaml update_fw
   Updating ip address: ip=1.1.1.1
   FW package: ['../packages/nvfw_DGX-H100_0005_231206.1.0_nightly.fwpkg']
   Ok to proceed with firmware update? <Y/N>
   y
   {"@odata.type": "#UpdateService.v1_11_0.UpdateService", "Messages": [{"@odata.type": "#Message.v1_0_8.Message", "Message": "A new task /redfish/v1/TaskService/Tasks/2 was created.", "MessageArgs": ["/redfish/v1/TaskService/Tasks/2"], "MessageId": "Task.1.0.New", "Resolution": "None", "Severity": "OK"}, {"@odata.type": "#Message.v1_0_8.Message", "Message": "The action UpdateService.MultipartPush was submitted to do firmware update.", "MessageArgs": ["UpdateService.MultipartPush"], "MessageId": "UpdateService.1.0.StartFirmwareUpdate", "Resolution": "None", "Severity": "OK"}]}
   FW update started, Task Id: 2
   Wait for Firmware Update to Start...
   TaskState: Running
   PercentComplete: 1
   TaskStatus: OK
   TaskState: Running
   PercentComplete: 20
   TaskStatus: OK
   TaskState: Running
   PercentComplete: 40
   TaskStatus: OK
   TaskState: Running
   PercentComplete: 61
   TaskStatus: OK
   TaskState: Running
   PercentComplete: 80
   TaskStatus: OK
   TaskState: Running
   PercentComplete: 99
   TaskStatus: OK
   TaskState: Completed
   PercentComplete: 100
   TaskStatus: OK
   Firmware update successful!
   Overall Time Taken: 0:24:38
   Refer to 'DGX H100 Firmware Update Document' on activation steps for new firmware to take effect.
   -------------------------------------------------------------------------------------------
   Error Code: 0

.. code-block::

   nvfwupd.py -c config.yaml show_update_progress -i 0 
   Task Info for Id: 0 
   StartTime: 2024-01-20T02:46:15+00:00 
   TaskState: Completed 
   PercentComplete: 100 
   TaskStatus: OK 
   EndTime: 2024-01-20T02:46:17+00:00 
   Overall Time Taken: 0:00:02 
   Overall Task Status: { 
      "@odata.id": "/redfish/v1/TaskService/Tasks/0", 
      "@odata.type": "#Task.v1_4_3.Task", 
      "EndTime": "2024-01-20T02:46:17+00:00", 
      "Id": "0", 
      "Messages": [ 
         { 
               "@odata.type": "#Message.v1_0_0.Message", 
               "Message": "The task with id 0 has started.", 
               "MessageArgs": [ 
                  "0" 
               ], 
               "MessageId": "TaskEvent.1.0.1.TaskStarted", 
               "Resolution": "None.", 
               "Severity": "OK" 
         }, 
         { 
               "@odata.type": "#Message.v1_0_0.Message", 
               "Message": "The task with id 0 has changed to progress 100 percent complete.", 
               "MessageArgs": [ 
                  "0", 
                  "100" 
               ], 
               "MessageId": "TaskEvent.1.0.1.TaskProgressChanged", 
               "Resolution": "None.", 
               "Severity": "OK" 
         }, 
         { 
               "@odata.type": "#Message.v1_0_0.Message", 
               "Message": "The task with id 0 has Completed.", 
               "MessageArgs": [ 
                  "0" 
               ], 
               "MessageId": "TaskEvent.1.0.1.TaskCompletedOK", 
               "Resolution": "None.", 
               "Severity": "OK" 
         } 
      ], 
      "Name": "Task 0", 
      "Payload": { 
         "HttpHeaders": [ 
               "Host: 1.1.1.1", 
               "User-Agent: python-requests/2.28.2", 
               "Accept-Encoding: gzip, deflate", 
               "Accept: */*", 
               "Connection: keep-alive", 
               "Content-Length: 109023143" 
         ], 
         "HttpOperation": "POST", 
         "JsonBody": "null", 
         "TargetUri": "/redfish/v1/UpdateService/update-multipart" 
      }, 
      "PercentComplete": 100, 
      "StartTime": "2024-01-20T02:46:15+00:00", 
      "TaskMonitor": "/redfish/v1/TaskService/Tasks/0/Monitor", 
      "TaskState": "Completed", 
      "TaskStatus": "OK" 
   } 
   Update is successful. 
   --------------------------------------------------------------------------------------- 