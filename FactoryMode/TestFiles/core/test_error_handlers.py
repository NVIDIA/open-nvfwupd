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

import unittest
from unittest.mock import MagicMock, patch

import pytest

from FactoryMode.flow_types import DeviceType
from FactoryMode.TrayFlowFunctions import error_handlers

pytestmark = pytest.mark.core


class TestErrorHandlers(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock()
        patcher = patch(
            "FactoryMode.TrayFlowFunctions.error_handlers.setup_logging",
            return_value=self.mock_logger,
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def _make_step(self, device_type=DeviceType.COMPUTE):
        dt = device_type

        class S:
            name = "op"
            operation = "op"
            device_type = dt
            device_id = "compute1"

        return S()

    def test_error_handler_no_orchestrator_in_context(self):
        step = self._make_step(DeviceType.COMPUTE)
        ok = error_handlers.error_handler_collect_nvdebug_logs(step, Exception("boom"), context={})
        self.assertFalse(ok)

    def test_collect_nvdebug_logs_missing_bmc_creds(self):
        error_handlers.collect_nvdebug_logs(
            device_id="d1",
            bmc_credentials={},
            os_credentials={},
            nvdebug_path="nvdebug",
            platform="arm64",
            baseboard="GB200",
            logger=self.mock_logger,
        )
        # Should log error and return early; ensure no run invoked
        self.mock_logger.error.assert_any_call(
            "Missing required credentials for NVDEBUG run, BMC credentials are required"
        )

    def test_collect_nvdebug_logs_log_dir_exists(self):
        # Make get_log_directory return a path that already exists
        with patch("FactoryMode.TrayFlowFunctions.error_handlers.get_log_directory") as gld:
            import pathlib
            import tempfile

            tmp = pathlib.Path(tempfile.mkdtemp())
            (tmp / "nvdebug_logs_compute1").mkdir(exist_ok=True)
            gld.return_value = tmp
            error_handlers.collect_nvdebug_logs(
                device_id="compute1",
                bmc_credentials={"ip": "1.1.1.1", "username": "u", "password": "p"},
                os_credentials={},
                nvdebug_path="nvdebug",
                platform="arm64",
                baseboard="GB200",
                logger=self.mock_logger,
            )
            # No subprocess.run should be called; verify via no info about success
            self.assertTrue(any("already exists" in str(c) for c in self.mock_logger.info.call_args_list))

    def test_collect_nvdebug_logs_called_process_error(self):
        with patch("FactoryMode.TrayFlowFunctions.error_handlers.subprocess.run") as run:
            from subprocess import CalledProcessError

            run.side_effect = CalledProcessError(returncode=1, cmd=["nvdebug"], stderr="bad")
            error_handlers.collect_nvdebug_logs(
                device_id="compute1",
                bmc_credentials={"ip": "1.1.1.1", "username": "u", "password": "p"},
                os_credentials={},
                nvdebug_path="nvdebug",
                platform="arm64",
                baseboard="GB200",
                logger=self.mock_logger,
            )
            self.mock_logger.error.assert_any_call("Failed to collect NVDebug logs: bad")
