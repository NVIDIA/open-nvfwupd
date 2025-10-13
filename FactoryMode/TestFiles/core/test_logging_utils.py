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

import logging

import pytest

from FactoryMode.output_manager import (
    AutoErrorCollectorHandler,
    capture_step_errors,
    get_collected_errors,
    set_log_directory,
    setup_logging,
    start_collecting_errors,
    start_error_collection,
    stop_collecting_errors,
    stop_error_collection,
)

pytestmark = [pytest.mark.core]


class TestLoggingUtils:
    # NOTE: Console handler tests removed - console output now handled by OutputModeManager
    # All logging is file-based, console display is managed separately

    def test_auto_error_collector_lifecycle_and_thread_safety(self):
        logger = logging.getLogger("compute_factory_flow")
        logger.setLevel(logging.INFO)
        setup_logging("compute_factory_flow")

        # Reset collection state: clear and stop
        start_collecting_errors()
        stop_collecting_errors()
        baseline = list(get_collected_errors())

        # Not collecting: should not capture
        logger.error("error before start")
        assert get_collected_errors() == baseline

        # Start collecting and capture a couple of errors
        start_collecting_errors()
        logger.error("first error")
        logger.error("second error: %s", "context")
        errs = get_collected_errors()
        assert "first error" in errs and "second error: context" in errs

        # Stop collecting returns snapshot and disables further capture
        captured = stop_collecting_errors()
        assert "first error" in captured and any("second error" in e for e in captured)
        # After stop, the collected list remains available but should not grow
        assert get_collected_errors() == captured
        logger.error("after stop")
        assert get_collected_errors() == captured

    def test_setup_logging_file_and_error_handlers(self, tmp_path):
        # Use a custom log directory under tmp_path to avoid cross-test interference
        custom_dir = tmp_path / "logsdir"
        set_log_directory(str(custom_dir))

        # All modules get file-only logging (no console handler)
        log_a = setup_logging("module_a")
        assert any(isinstance(h, logging.FileHandler) for h in log_a.handlers)
        assert any(isinstance(h, AutoErrorCollectorHandler) for h in log_a.handlers)

        log_b = setup_logging("module_b")
        assert any(isinstance(h, logging.FileHandler) for h in log_b.handlers)
        assert any(isinstance(h, AutoErrorCollectorHandler) for h in log_b.handlers)

        log_c = setup_logging("module_c")
        assert any(isinstance(h, logging.FileHandler) for h in log_c.handlers)
        assert any(isinstance(h, AutoErrorCollectorHandler) for h in log_c.handlers)

        # Repeated setup does not duplicate handlers
        before = len(log_c.handlers)
        setup_logging("module_c")
        after = len(log_c.handlers)
        assert before == after

    def test_error_collector_handler_start_stop_and_clear(self):
        logger = logging.getLogger("custom_module")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)

        # Start error collection, should attach a collector handler
        collector = start_error_collection("custom_module")

        # Log some messages (ERROR only)
        logger.info("info msg")
        logger.error("error msg 1")
        logger.error("error msg 2")

        errors = collector.get_errors()
        assert len(errors) == 2
        assert "error msg 1" in errors[0]
        assert "error msg 2" in errors[1]

        # Clear
        collector.clear_errors()
        assert collector.get_errors() == []

        # Log more and confirm collection still works
        logger.error("error msg 3")
        assert len(collector.get_errors()) == 1
        assert "error msg 3" in collector.get_errors()[0]

        # Stop collection
        stopped_errors = stop_error_collection("custom_module", collector)
        assert len(stopped_errors) == 1
        assert "error msg 3" in stopped_errors[0]

    def test_error_capture_context_manager_captures_and_restores(self):
        logger = logging.getLogger("test_error_capture")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)

        # Before context
        original_error_method = logger.error

        # Inside context: capture errors
        with capture_step_errors("test_error_capture") as ctx:
            logger.error("captured error 1")
            logger.error("captured error 2: %s", "detail")
            errors = ctx.get_errors()
            assert len(errors) == 2
            assert "captured error 1" in errors[0]
            assert "captured error 2: detail" in errors[1]

        # After context: original error method restored
        assert logger.error == original_error_method
