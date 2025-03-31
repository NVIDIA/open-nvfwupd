Getting the Verbose Logs
------------------------

To get verbose tool logs in a file, use the ``–v`` or the ``--verbose`` option with the file path. If file path is not provided, the logs will be created in the ``nvfwupd_log.txt`` file in the current working directory.

Here is an example:

.. code-block::

    $ nvfwupd.py –v ./mypath/mylogfile.log –t ip=<BMC IP> user=*** password=*** show_version -p nvfw_GB200-P4975_0004_240808.1.0_custom_prod-signed.fwpkg
