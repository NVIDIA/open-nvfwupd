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

import json
import os
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import paramiko
import pytest
import requests

from FactoryMode.TrayFlowFunctions.hmc_redfish_utils import HMCRedfishUtils
from FactoryMode.TrayFlowFunctions.utils import Utils

# Mark all tests in this file as core tests
pytestmark = pytest.mark.core


class TestCompareVersions(unittest.TestCase):
    """Test cases for the compare_versions method."""

    def test_equal_versions_dot_format(self):
        """Test equal versions with dot format."""
        result = Utils.compare_versions("40.44.3528", "40.44.3528", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("01.04.0008.0000", "01.04.0008.0000", "==")
        self.assertTrue(result)

    def test_equal_versions_dash_format(self):
        """Test equal versions with dash format."""
        result = Utils.compare_versions("GB2-CX8.25.05-09", "GB2-CX8.25.05-09", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("GB200Nvl-25.01-F", "GB200Nvl-25.01-F", "==")
        self.assertTrue(result)

    def test_equal_versions_underscore_format(self):
        """Test equal versions with underscore format."""
        result = Utils.compare_versions("01.04.0008.0000_n04", "01.04.0008.0000_n04", "==")
        self.assertTrue(result)

    def test_equal_versions_hex_format(self):
        """Test equal versions with hexadecimal format."""
        result = Utils.compare_versions("0.1D", "0.1D", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("01151024", "01151024", "==")
        self.assertTrue(result)

    def test_equal_versions_mixed_format(self):
        """Test equal versions with mixed format."""
        result = Utils.compare_versions("G548.0201.00.06", "G548.0201.00.06", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("97.00.82.00.88", "97.00.82.00.88", "==")
        self.assertTrue(result)

    def test_not_equal_versions(self):
        """Test not equal versions."""
        result = Utils.compare_versions("40.44.3528", "40.44.3529", "==")
        self.assertFalse(result)

        result = Utils.compare_versions("GB2-CX8.25.05-09", "GB2-CX8.25.05-10", "==")
        self.assertFalse(result)

    def test_not_equal_operator(self):
        """Test not equal operator."""
        result = Utils.compare_versions("40.44.3528", "40.44.3529", "!=")
        self.assertTrue(result)

        result = Utils.compare_versions("40.44.3528", "40.44.3528", "!=")
        self.assertFalse(result)

    def test_greater_than_operator(self):
        """Test greater than operator."""
        result = Utils.compare_versions("40.44.3529", "40.44.3528", ">")
        self.assertTrue(result)

        result = Utils.compare_versions("GB2-CX8.25.06-09", "GB2-CX8.25.05-09", ">")
        self.assertTrue(result)

        result = Utils.compare_versions("01.04.0008.0001", "01.04.0008.0000", ">")
        self.assertTrue(result)

    def test_less_than_operator(self):
        """Test less than operator."""
        result = Utils.compare_versions("40.44.3527", "40.44.3528", "<")
        self.assertTrue(result)

        result = Utils.compare_versions("GB2-CX8.25.04-09", "GB2-CX8.25.05-09", "<")
        self.assertTrue(result)

        result = Utils.compare_versions("01.04.0008.0000", "01.04.0008.0001", "<")
        self.assertTrue(result)

    def test_greater_equal_operator(self):
        """Test greater than or equal operator."""
        result = Utils.compare_versions("40.44.3529", "40.44.3528", ">=")
        self.assertTrue(result)

        result = Utils.compare_versions("40.44.3528", "40.44.3528", ">=")
        self.assertTrue(result)

        result = Utils.compare_versions("40.44.3527", "40.44.3528", ">=")
        self.assertFalse(result)

    def test_less_equal_operator(self):
        """Test less than or equal operator."""
        result = Utils.compare_versions("40.44.3527", "40.44.3528", "<=")
        self.assertTrue(result)

        result = Utils.compare_versions("40.44.3528", "40.44.3528", "<=")
        self.assertTrue(result)

        result = Utils.compare_versions("40.44.3529", "40.44.3528", "<=")
        self.assertFalse(result)

    def test_different_length_versions(self):
        """Test versions with different number of components."""
        result = Utils.compare_versions("40.44.3528", "40.44.3528.1", "==")
        self.assertFalse(result)

        result = Utils.compare_versions("GB2-CX8.25", "GB2-CX8.25.05-09", "==")
        self.assertFalse(result)

    def test_case_insensitive_comparison(self):
        """Test case insensitive comparison."""
        result = Utils.compare_versions("gb2-cx8.25.05-09", "GB2-CX8.25.05-09", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("GB200NVL-25.01-F", "GB200Nvl-25.01-F", "==")
        self.assertTrue(result)

    def test_hexadecimal_comparison(self):
        """Test hexadecimal version comparison."""
        result = Utils.compare_versions("0.1E", "0.1D", ">")
        self.assertTrue(result)

        result = Utils.compare_versions("0.1C", "0.1D", "<")
        self.assertTrue(result)

        result = Utils.compare_versions("01151025", "01151024", ">")
        self.assertTrue(result)

    def test_padding_comparison(self):
        """Test comparison with different length components that need padding."""
        result = Utils.compare_versions("1.2.3", "01.02.03", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("01.02.03", "1.2.3", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("A.1", "A.01", "==")
        self.assertTrue(result)

    def test_complex_version_formats(self):
        """Test complex version formats."""
        # Test with mixed alphanumeric and special characters
        result = Utils.compare_versions("G548.0201.00.06", "G548.0201.00.06", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("G548.0201.00.07", "G548.0201.00.06", ">")
        self.assertTrue(result)

        # Test with long version strings
        result = Utils.compare_versions("97.00.82.00.88", "97.00.82.00.88", "==")
        self.assertTrue(result)

        result = Utils.compare_versions("97.00.82.00.89", "97.00.82.00.88", ">")
        self.assertTrue(result)

    def test_edge_cases(self):
        """Test edge cases."""
        # Empty strings
        result = Utils.compare_versions("", "", "==")
        self.assertTrue(result)

        # Single component
        result = Utils.compare_versions("123", "123", "==")
        self.assertTrue(result)

        # Very long version strings
        result = Utils.compare_versions("A.B.C.D.E.F.G.H.I.J", "A.B.C.D.E.F.G.H.I.J", "==")
        self.assertTrue(result)

    def test_default_operator(self):
        """Test default operator (==)."""
        result = Utils.compare_versions("40.44.3528", "40.44.3528")
        self.assertTrue(result)

        result = Utils.compare_versions("40.44.3528", "40.44.3529")
        self.assertFalse(result)

    def test_invalid_operators(self):
        """Test behavior with invalid operators."""
        # The method should handle invalid operators gracefully
        result = Utils.compare_versions("40.44.3528", "40.44.3528", "invalid")
        self.assertFalse(result)

        result = Utils.compare_versions("40.44.3529", "40.44.3528", "invalid")
        self.assertFalse(result)


class TestUtilsHttp(unittest.TestCase):
    def setUp(self):
        self.utils = Utils(dut_ip="1.2.3.4", dut_username="u", dut_password="p")

    @patch("FactoryMode.TrayFlowFunctions.utils.requests.get")
    def test_get_request_success_and_empty_and_errors(self, mock_get):
        # 200 with JSON body
        resp_ok = MagicMock(status_code=200, text=json.dumps({"a": 1}))
        resp_ok.json.return_value = {"a": 1}
        # 204 with empty body
        resp_empty = MagicMock(status_code=204, text="")
        # 500 error
        resp_err = MagicMock(status_code=500, text="err")

        mock_get.side_effect = [resp_ok, resp_empty, resp_err]

        ok, data = self.utils.get_request("/x", timeout=5)
        self.assertTrue(ok)
        self.assertEqual(data, {"a": 1})

        ok, data = self.utils.get_request("/x", timeout=5)
        self.assertTrue(ok)
        self.assertEqual(data, "")

        ok, data = self.utils.get_request("/x", timeout=5)
        self.assertFalse(ok)
        self.assertEqual(data, "err")

        # Timeout exception
        mock_get.side_effect = requests.exceptions.Timeout("t")
        ok, data = self.utils.get_request("/x", timeout=1)
        self.assertFalse(ok)
        self.assertIn("Timeout", data)

        # Generic exception
        mock_get.side_effect = ValueError("boom")
        ok, data = self.utils.get_request("/x", timeout=1)
        self.assertFalse(ok)
        self.assertEqual(data, "boom")

    @patch("FactoryMode.TrayFlowFunctions.utils.requests.patch")
    def test_patch_request_success_and_400_and_errors(self, mock_patch):
        # 200 empty
        resp_200 = MagicMock(status_code=200, text="")
        # 204 empty
        resp_204 = MagicMock(status_code=204, text="")
        # 400 PatchValueAlreadyExists
        err_body_exists = {"error": {"code": "Base.1.0.PatchValueAlreadyExists"}}
        resp_400_exists = MagicMock(status_code=400, text=json.dumps(err_body_exists))
        # 400 other error
        err_body_other = {"error": {"code": "Base.1.0.Other"}}
        resp_400_other = MagicMock(status_code=400, text=json.dumps(err_body_other))
        # 500 error
        resp_500 = MagicMock(status_code=500, text="bad")

        mock_patch.side_effect = [resp_200, resp_204, resp_400_exists, resp_400_other, resp_500]

        ok, data = self.utils.patch_request("/y", data={})
        self.assertTrue(ok)
        self.assertEqual(data, {})

        ok, data = self.utils.patch_request("/y", data={})
        self.assertTrue(ok)
        self.assertEqual(data, {})

        ok, data = self.utils.patch_request("/y", data={})
        self.assertTrue(ok)
        self.assertEqual(data, err_body_exists)

        ok, data = self.utils.patch_request("/y", data={})
        self.assertFalse(ok)
        self.assertEqual(data, err_body_other)

        ok, data = self.utils.patch_request("/y", data={})
        self.assertFalse(ok)
        self.assertEqual(data, "bad")

        # Exception path
        mock_patch.side_effect = RuntimeError("boom")
        ok, data = self.utils.patch_request("/y", data={})
        self.assertFalse(ok)
        self.assertEqual(data, "boom")

    @patch("FactoryMode.TrayFlowFunctions.utils.requests.post")
    def test_post_request_with_and_without_json_and_errors(self, mock_post):
        # 200 with body
        resp_200 = MagicMock(status_code=200, text=json.dumps({"ok": True}))
        resp_200.json.return_value = {"ok": True}
        # 201 empty
        resp_201 = MagicMock(status_code=201, text="")
        # 500 error
        resp_500 = MagicMock(status_code=500, text="err")

        mock_post.side_effect = [resp_200, resp_201, resp_500]

        ok, data = self.utils.post_request("/z", json_data={"a": 1})
        self.assertTrue(ok)
        self.assertEqual(data, {"ok": True})

        ok, data = self.utils.post_request("/z")
        self.assertTrue(ok)
        self.assertEqual(data, {})

        ok, data = self.utils.post_request("/z")
        self.assertFalse(ok)
        self.assertEqual(data, "err")

        # Exception path
        mock_post.side_effect = Exception("boom")
        ok, data = self.utils.post_request("/z")
        self.assertFalse(ok)
        self.assertEqual(data, "boom")

    @patch("FactoryMode.TrayFlowFunctions.utils.requests.post")
    def test_post_upload_request_http_push_and_multipart_and_errors(self, mock_post):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"DATA")
            tf.flush()
            file_path = tf.name
        self.addCleanup(lambda: os.remove(file_path) if os.path.exists(file_path) else None)

        # HttpPushUpdate: 202 empty
        resp_202_empty = MagicMock(status_code=202, text="")
        # MultipartUpdate: 201 with JSON
        resp_201_json = MagicMock(status_code=201, text=json.dumps({"Task": "t", "@odata.id": "/task/0"}))
        resp_201_json.json.return_value = {"Task": "t", "@odata.id": "/task/0"}
        # 500 error
        resp_500 = MagicMock(status_code=500, text="bad")

        mock_post.side_effect = [resp_202_empty, resp_201_json, resp_500]

        ok, data = self.utils.post_upload_request(
            url_path="/up",
            file_path=file_path,
            update_method="HttpPushUpdate",
            upd_params=None,
            timeout=5,
        )
        self.assertTrue(ok)
        self.assertEqual(data, "")

        ok, data = self.utils.post_upload_request(
            url_path="/up",
            file_path=file_path,
            update_method="MultipartUpdate",
            upd_params="{}",
            timeout=5,
        )
        self.assertTrue(ok)
        self.assertEqual(data, {"Task": "t", "@odata.id": "/task/0"})

        ok, data = self.utils.post_upload_request(
            url_path="/up",
            file_path=file_path,
            update_method="MultipartUpdate",
            upd_params="{}",
            timeout=5,
        )
        self.assertFalse(ok)
        self.assertEqual(data, "bad")

        # Exception path
        mock_post.side_effect = Exception("boom")
        ok, data = self.utils.post_upload_request(
            url_path="/up",
            file_path=file_path,
            update_method="HttpPushUpdate",
            upd_params=None,
            timeout=5,
        )
        self.assertFalse(ok)
        self.assertEqual(data, "boom")

    def test_monitor_job_success_running_timeout_and_errors(self):
        # Success immediate
        with patch.object(self.utils, "get_request", return_value=(True, {"TaskState": "Completed"})) as mock_get:
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=10, check_interval=1)
            self.assertTrue(ok)
            self.assertEqual(resp.get("TaskState"), "Completed")
            mock_get.assert_called_once()

        # Running then complete
        with patch.object(
            self.utils,
            "get_request",
            side_effect=[(True, {"TaskState": "Running"}), (True, {"TaskState": "Completed"})],
        ) as mock_get, patch("time.sleep") as mock_sleep:
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=10, check_interval=1)
            self.assertTrue(ok)
            self.assertEqual(resp.get("TaskState"), "Completed")
            self.assertGreaterEqual(mock_get.call_count, 2)
            mock_sleep.assert_called()

        # Timeout reached immediately
        with patch.object(self.utils, "get_request") as mock_get, patch(
            "FactoryMode.TrayFlowFunctions.shared_utils.time.time"
        ) as mock_time:
            mock_time.side_effect = [0, 2, 2, 2, 2, 2]
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=1, check_interval=1)
            self.assertTrue(ok)
            self.assertEqual(resp.get("Message"), "Monitoring timeout reached")
            mock_get.assert_not_called()

        # Connection/timeout error then complete
        with patch.object(
            self.utils,
            "get_request",
            side_effect=[(False, "Timeout Error"), (True, {"TaskState": "Completed"})],
        ) as mock_get, patch("time.sleep"):
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=10, check_interval=1)
            self.assertTrue(ok)
            self.assertEqual(resp.get("TaskState"), "Completed")
            # Ensure 120s connection timeout used
            first_call = mock_get.call_args_list[0]
            # args: (url_path, timeout)
            self.assertEqual(first_call[0][0], "/task/0")
            self.assertIn("timeout", first_call[1])
            self.assertEqual(first_call[1]["timeout"], 120)

        # Non-connection error returns False immediately
        with patch.object(self.utils, "get_request", return_value=(False, "HTTP 500")):
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=10, check_interval=1)
            self.assertFalse(ok)
            self.assertEqual(resp, "HTTP 500")

    @patch("FactoryMode.TrayFlowFunctions.utils.subprocess.check_output")
    def test_ping_dut_success_and_failure(self, mock_co):
        mock_co.return_value = "ok"
        rc = self.utils.ping_dut()
        self.assertEqual(rc, 0)
        mock_co.side_effect = subprocess.CalledProcessError(1, "ping")
        rc = self.utils.ping_dut()
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()


class TestHMCRedfishUtils(unittest.TestCase):
    def setUp(self):
        self.bmc_connection = {"ip": "10.0.0.2", "username": "root", "password": "pass"}
        self.hmc_ip = "172.31.13.251"
        self.utils = HMCRedfishUtils(bmc_connection=self.bmc_connection, hmc_ip=self.hmc_ip)

    def _mock_ssh_exec_results(self, mock_ssh_client, results_queue):
        """
        Configure the mocked SSH client to return a sequence of (exit_status, stdout_text, stderr_text)
        for successive exec_command calls, and capture the command strings passed in.
        Returns list to which executed commands will be appended for assertions.
        """
        client_instance = MagicMock()
        mock_ssh_client.return_value = client_instance
        client_instance.set_missing_host_key_policy = MagicMock()
        client_instance.connect = MagicMock()
        client_instance.close = MagicMock()

        executed_commands = []

        def exec_side_effect(command, timeout=None):
            executed_commands.append(command)
            if not results_queue:
                raise AssertionError("No more queued SSH results for exec_command")
            exit_status, stdout_text, stderr_text = results_queue.pop(0)
            stdout = MagicMock()
            stderr = MagicMock()
            stdout.read.return_value = stdout_text.encode()
            stderr.read.return_value = stderr_text.encode()
            channel = MagicMock()
            channel.recv_exit_status.return_value = exit_status
            stdout.channel = channel
            return (MagicMock(), stdout, stderr)

        client_instance.exec_command.side_effect = exec_side_effect
        return executed_commands

    @patch("FactoryMode.TrayFlowFunctions.hmc_redfish_utils.paramiko.SSHClient")
    def test_get_request_success_json_and_empty_and_non_json_error(self, mock_ssh_client):
        # Success with JSON
        results = [
            (0, json.dumps({"ok": True}), ""),
            # Success with empty output
            (0, "", ""),
            # Non-JSON output considered error
            (1, "not json", ""),
        ]
        executed_cmds = self._mock_ssh_exec_results(mock_ssh_client, results)

        ok, data = self.utils.get_request("/redfish/v1/")
        self.assertTrue(ok)
        self.assertEqual(data, {"ok": True})

        ok, data = self.utils.get_request("/redfish/v1/")
        self.assertTrue(ok)
        self.assertEqual(data, {})

        ok, data = self.utils.get_request("/redfish/v1/")
        self.assertFalse(ok)
        self.assertEqual(data, "Command failed (exit 1): not json")

        # Verify curl GET constructed
        self.assertTrue(any(cmd.startswith("curl -s -X GET") for cmd in executed_cmds))
        self.assertTrue(
            all(
                f"http://{self.hmc_ip}/redfish/v1/" in cmd or f"http://{self.hmc_ip}/redfish/v1" in cmd
                for cmd in executed_cmds
            )
        )

    @patch("FactoryMode.TrayFlowFunctions.hmc_redfish_utils.paramiko.SSHClient")
    def test_error_categorization_in_execute_bmc_command(self, mock_ssh_client):
        results = [
            (1, "", "Connection timed out"),
            (1, "", "connection refused by host"),
            (1, "", "Authentication failed for user"),
            (1, "", "404 Not Found"),
            (2, "generic failure", ""),
        ]
        self._mock_ssh_exec_results(mock_ssh_client, results)

        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertIn("Connection timeout", msg)

        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertIn("Connection refused", msg)

        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertIn("Authentication error", msg)

        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertIn("Endpoint not found", msg)

        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertIn("Command failed (exit", msg)

    @patch("FactoryMode.TrayFlowFunctions.hmc_redfish_utils.paramiko.SSHClient")
    def test_execute_bmc_command_exception_paths(self, mock_ssh_client):
        client_instance = MagicMock()
        mock_ssh_client.return_value = client_instance
        client_instance.set_missing_host_key_policy = MagicMock()

        # AuthenticationException
        client_instance.connect.side_effect = paramiko.AuthenticationException()
        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertIn("Authentication failed - check BMC credentials", msg)

        # SSHException
        client_instance.connect.side_effect = paramiko.SSHException("boom")
        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertIn("SSH error: boom", msg)

        # socket.timeout
        client_instance.connect.side_effect = socket.timeout()
        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertEqual(msg, "SSH connection timeout")

        # Generic Exception
        client_instance.connect.side_effect = RuntimeError("oops")
        ok, msg = self.utils.get_request("/x")
        self.assertFalse(ok)
        self.assertIn("SSH connection error: oops", msg)

    @patch("FactoryMode.TrayFlowFunctions.hmc_redfish_utils.paramiko.SSHClient")
    def test_parse_curl_response_unsupported_action_error(self, mock_ssh_client):
        body = {"error": {"message": "Action XYZ is not supported by the resource"}}
        results = [(0, json.dumps(body), "")]
        self._mock_ssh_exec_results(mock_ssh_client, results)

        ok, data = self.utils.post_request("/x")
        self.assertFalse(ok)
        self.assertEqual(data, body)

    @patch("FactoryMode.TrayFlowFunctions.hmc_redfish_utils.paramiko.SSHClient")
    def test_post_request_with_and_without_json_and_errors(self, mock_ssh_client):
        results = [
            (0, json.dumps({"ok": True}), ""),
            (0, "", ""),
            (1, "bad", ""),
        ]
        executed_cmds = self._mock_ssh_exec_results(mock_ssh_client, results)

        ok, data = self.utils.post_request("/z", json_data={"k": 'va"l"'})
        self.assertTrue(ok)
        self.assertEqual(data, {"ok": True})

        # Verify JSON was embedded and escaped in curl
        expected_json_str = json.dumps({"k": 'va"l"'}).replace('"', '\\"')
        self.assertTrue(any(expected_json_str in cmd for cmd in executed_cmds))
        self.assertTrue(any('-H "Content-Type: application/json"' in cmd for cmd in executed_cmds))

        ok, data = self.utils.post_request("/z")
        self.assertTrue(ok)
        self.assertEqual(data, {})

        ok, data = self.utils.post_request("/z")
        self.assertFalse(ok)
        self.assertEqual(data, "Command failed (exit 1): bad")

    @patch("FactoryMode.TrayFlowFunctions.hmc_redfish_utils.paramiko.SSHClient")
    def test_patch_request_success_and_error(self, mock_ssh_client):
        results = [
            (0, json.dumps({"ok": 1}), ""),
            (1, "oops", ""),
        ]
        self._mock_ssh_exec_results(mock_ssh_client, results)

        ok, data = self.utils.patch_request("/y", data={"a": 1})
        self.assertTrue(ok)
        self.assertEqual(data, {"ok": 1})

        ok, data = self.utils.patch_request("/y", data={"a": 1})
        self.assertFalse(ok)
        self.assertEqual(data, "Command failed (exit 1): oops")

    @patch("FactoryMode.TrayFlowFunctions.hmc_redfish_utils.paramiko.SSHClient")
    def test_post_upload_http_push_and_multipart_and_errors(self, mock_ssh_client):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"DATA")
            tf.flush()
            file_path = tf.name
        self.addCleanup(lambda: os.remove(file_path) if os.path.exists(file_path) else None)

        results = [
            # HttpPushUpdate success (empty output)
            (0, "", ""),
            # MultipartUpdate success (JSON)
            (0, json.dumps({"Task": "t", "@odata.id": "/task/0"}), ""),
            # Error
            (1, "bad", ""),
        ]
        executed_cmds = self._mock_ssh_exec_results(mock_ssh_client, results)

        ok, data = self.utils.post_upload_request(
            url_path="/up",
            file_path=file_path,
            update_method="HttpPushUpdate",
            upd_params=None,
            timeout=5,
        )
        self.assertTrue(ok)
        self.assertEqual(data, {})
        self.assertTrue(any(f"-T {file_path}" in cmd for cmd in executed_cmds))

        ok, data = self.utils.post_upload_request(
            url_path="/up",
            file_path=file_path,
            update_method="MultipartUpdate",
            upd_params="{}",
            timeout=5,
        )
        self.assertTrue(ok)
        self.assertEqual(data, {"Task": "t", "@odata.id": "/task/0"})
        self.assertTrue(any(' -F "UpdateFile=@' in cmd for cmd in executed_cmds))
        self.assertTrue(any(' -F "UpdateParameters={};type=application/json"' in cmd for cmd in executed_cmds))

        ok, data = self.utils.post_upload_request(
            url_path="/up",
            file_path=file_path,
            update_method="MultipartUpdate",
            upd_params="{}",
            timeout=5,
        )
        self.assertFalse(ok)
        self.assertEqual(data, "Command failed (exit 1): bad")

        ok, msg = self.utils.post_upload_request(
            url_path="/up",
            file_path=file_path,
            update_method="Unsupported",
            upd_params=None,
            timeout=5,
        )
        self.assertFalse(ok)
        self.assertIn("Unsupported update method", msg)

    def test_monitor_job_paths(self):
        # Immediate complete
        with patch.object(self.utils, "get_request", return_value=(True, {"TaskState": "Completed"})) as mock_get:
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=10, check_interval=1)
            self.assertTrue(ok)
            self.assertEqual(resp.get("TaskState"), "Completed")
            mock_get.assert_called_once()

        # Running then complete
        with patch.object(
            self.utils,
            "get_request",
            side_effect=[(True, {"TaskState": "Running"}), (True, {"TaskState": "Completed"})],
        ) as mock_get, patch("time.sleep") as mock_sleep:
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=10, check_interval=1)
            self.assertTrue(ok)
            self.assertEqual(resp.get("TaskState"), "Completed")
            self.assertGreaterEqual(mock_get.call_count, 2)
            mock_sleep.assert_called()

        # Timeout before any request
        with patch.object(self.utils, "get_request") as mock_get, patch(
            "FactoryMode.TrayFlowFunctions.shared_utils.time.time"
        ) as mock_time:
            mock_time.side_effect = [0, 2, 2, 2]
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=1, check_interval=1)
            self.assertTrue(ok)
            self.assertEqual(resp.get("Message"), "Monitoring timeout reached")
            mock_get.assert_not_called()

        # Connection/timeout error then success
        with patch.object(
            self.utils,
            "get_request",
            side_effect=[(False, "Timeout Error"), (True, {"TaskState": "Completed"})],
        ):
            with patch("time.sleep"):
                ok, resp = self.utils.monitor_job(uri="/task/0", timeout=10, check_interval=1)
                self.assertTrue(ok)
                self.assertEqual(resp.get("TaskState"), "Completed")

        # Non-connection error returns False
        with patch.object(self.utils, "get_request", return_value=(False, "HTTP 500")):
            ok, resp = self.utils.monitor_job(uri="/task/0", timeout=10, check_interval=1)
            self.assertFalse(ok)
            self.assertEqual(resp, "HTTP 500")

    def test_ping_dut_success_and_failure(self):
        with patch.object(self.utils, "get_request", return_value=(True, {})):
            self.assertEqual(self.utils.ping_dut(), 0)
        with patch.object(self.utils, "get_request", return_value=(False, "bad")):
            self.assertEqual(self.utils.ping_dut(), 1)
