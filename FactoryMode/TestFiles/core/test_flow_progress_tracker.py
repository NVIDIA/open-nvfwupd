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

#!/usr/bin/env python3
"""
Unit tests for FlowProgressTracker and StepExecution classes.
This module tests flow progress tracking, JSON persistence, and thread safety.

Use the following command to run the tests:
python3 -m unittest TestFiles.test_flow_progress_tracker -v
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import pytest

from FactoryMode.flow_progress_tracker import FlowProgressTracker, StepExecution
from FactoryMode.flow_types import DeviceType, FlowStep

# Mark all tests in this file as core tests
pytestmark = pytest.mark.core


class TestStepExecution(unittest.TestCase):
    """Test cases for StepExecution dataclass."""

    def setUp(self):
        """Set up test fixtures."""
        self.start_time = time.time()

    def test_step_execution_creation_required_fields(self):
        """Test StepExecution creation with required fields only."""
        step = StepExecution(
            step_name="Test Step",
            step_operation="test_operation",
            device_type="compute",
            device_id="compute1",
            step_index=0,
            started_at=self.start_time,
            flow_name="Test Flow",
        )

        # Verify required fields
        self.assertEqual(step.step_name, "Test Step")
        self.assertEqual(step.step_operation, "test_operation")
        self.assertEqual(step.device_type, "compute")
        self.assertEqual(step.device_id, "compute1")
        self.assertEqual(step.step_index, 0)
        self.assertEqual(step.started_at, self.start_time)

        # Verify default values
        self.assertEqual(step.retry_count, 3)
        self.assertIsNone(step.timeout_seconds)
        self.assertEqual(step.wait_after_seconds, 0)
        self.assertEqual(step.status, "running")
        self.assertFalse(step.final_result)
        self.assertEqual(step.retry_attempts, 0)
        self.assertEqual(step.retry_durations, [])
        self.assertIsNone(step.jump_taken)
        self.assertEqual(step.optional_flows_triggered, [])
        self.assertEqual(step.error_messages, [])

    def test_step_execution_creation_all_fields(self):
        """Test StepExecution creation with all fields specified."""
        step = StepExecution(
            step_name="Complete Test Step",
            step_operation="complete_test_operation",
            device_type="switch",
            device_id="switch1",
            step_index=5,
            started_at=self.start_time,
            flow_name="Test Flow",
            retry_count=5,
            timeout_seconds=300,
            wait_after_seconds=10,
            execute_on_error="custom_error_handler",
            jump_on_success="success_target",
            tag="test_tag",
        )

        self.assertEqual(step.step_name, "Complete Test Step")
        self.assertEqual(step.retry_count, 5)
        self.assertEqual(step.timeout_seconds, 300)
        self.assertEqual(step.wait_after_seconds, 10)
        self.assertEqual(step.execute_on_error, "custom_error_handler")
        self.assertEqual(step.jump_on_success, "success_target")
        self.assertEqual(step.tag, "test_tag")

    def test_step_execution_to_dict_serialization(self):
        """Test StepExecution to_dict method for JSON serialization."""
        completed_time = self.start_time + 10.5

        step = StepExecution(
            step_name="Serialization Test",
            step_operation="serialize_operation",
            device_type="power_shelf",
            device_id="ps1",
            step_index=2,
            started_at=self.start_time,
            flow_name="Test Flow",
            completed_at=completed_time,
            duration=10.5,
            status="completed",
            final_result=True,
            retry_attempts=2,
            retry_durations=[1.5, 2.0],
            jump_taken="success",
            jump_target="next_step",
            optional_flows_triggered=["recovery_flow"],
            optional_flow_results={"recovery_flow": True},
            error_messages=["Warning: High temperature"],
            error_handler_executed="temperature_handler",
            error_handler_result=True,
            parameters={"threshold": 80},
            context_info={"environment": "production"},
        )

        step_dict = step.to_dict()

        # Verify all fields are serialized
        expected_keys = {
            "step_name",
            "step_operation",
            "device_type",
            "device_id",
            "step_index",
            "retry_count",
            "timeout_seconds",
            "wait_after_seconds",
            "wait_between_retries_seconds",
            "execute_on_error",
            "execute_optional_flow",
            "jump_on_success",
            "jump_on_failure",
            "tag",
            "started_at",
            "completed_at",
            "duration",
            "status",
            "final_result",
            "retry_attempts",
            "retry_durations",
            "jump_taken",
            "jump_target",
            "optional_flows_triggered",
            "optional_flow_results",
            "error_messages",
            "error_handler_executed",
            "error_handler_result",
            "parameters",
            "context_info",
            "execution_id",
        }

        self.assertEqual(set(step_dict.keys()), expected_keys)
        self.assertEqual(step_dict["step_name"], "Serialization Test")
        self.assertEqual(step_dict["status"], "completed")
        self.assertTrue(step_dict["final_result"])
        self.assertEqual(step_dict["retry_attempts"], 2)
        self.assertEqual(step_dict["retry_durations"], [1.5, 2.0])
        self.assertEqual(step_dict["jump_taken"], "success")
        self.assertEqual(step_dict["optional_flows_triggered"], ["recovery_flow"])

    def test_step_execution_unique_execution_id(self):
        """Test that each StepExecution gets a unique execution_id."""
        step1 = StepExecution(
            step_name="Step 1",
            step_operation="op1",
            device_type="compute",
            device_id="compute1",
            step_index=0,
            started_at=self.start_time,
            flow_name="Test Flow",
        )

        step2 = StepExecution(
            step_name="Step 2",
            step_operation="op2",
            device_type="compute",
            device_id="compute1",
            step_index=1,
            started_at=self.start_time,
            flow_name="Test Flow",
        )

        self.assertNotEqual(step1.execution_id, step2.execution_id)
        self.assertIsInstance(step1.execution_id, str)
        self.assertIsInstance(step2.execution_id, str)


class TestFlowProgressTracker(unittest.TestCase):
    """Test cases for FlowProgressTracker class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directory for JSON files
        self.test_dir = tempfile.mkdtemp()
        self.json_path = Path(self.test_dir) / "test_progress.json"
        self.tracker = FlowProgressTracker(self.json_path)

    def _create_tracker(self, base_dir: Path) -> FlowProgressTracker:
        return FlowProgressTracker(Path(base_dir) / "progress.json")

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary directory
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_tracker_initialization(self):
        """Test FlowProgressTracker initialization."""
        self.assertEqual(self.tracker.json_file_path, self.json_path)
        self.assertIsInstance(self.tracker.flows, dict)
        self.assertTrue(self.json_path.exists())  # File is created during initialization

    def test_start_flow_tracking(self):
        """Test starting flow tracking."""
        flow_name = "Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=3)

        self.assertIn(flow_name, self.tracker.flows)
        flow_info = self.tracker.flows[flow_name]

        self.assertEqual(flow_info.status, "Pending")
        self.assertEqual(flow_info.total_steps, 3)
        self.assertEqual(flow_info.completed_steps, 0)

    def test_start_step_tracking(self):
        """Test starting step tracking."""
        flow_name = "Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=1)

        # Create a mock step object
        mock_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="test_operation",
            parameters={},
            name="Test Step",
        )

        execution_id = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step, step_index=0)

        self.assertIsInstance(execution_id, str)
        self.assertIn(execution_id, self.tracker._active_step_executions)

        step_execution = self.tracker._active_step_executions[execution_id]
        self.assertEqual(step_execution.step_name, "Test Step")
        self.assertEqual(step_execution.status, "running")

    def test_complete_step_tracking(self):
        """Test completing step tracking."""
        flow_name = "Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=1)

        # Create a mock step object
        mock_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="test_operation",
            parameters={},
            name="Test Step",
        )

        execution_id = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step, step_index=0)

        # Simulate some execution time
        time.sleep(0.1)

        self.tracker.complete_step_execution(execution_id, result=True)

        # Verify the step was moved to completed steps
        flow_info = self.tracker.flows[flow_name]
        self.assertEqual(len(flow_info.steps_executed), 1)

        completed_step = flow_info.steps_executed[0]
        self.assertEqual(completed_step.status, "completed")
        self.assertTrue(completed_step.final_result)
        self.assertIsNotNone(completed_step.completed_at)
        self.assertGreater(completed_step.duration, 0)

    def test_fail_step_tracking(self):
        """Test failing step tracking."""
        flow_name = "Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=1)

        mock_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="failing_operation",
            parameters={},
            name="Failing Step",
        )

        execution_id = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step, step_index=0)

        error_message = "Step failed due to test error"
        self.tracker.complete_step_execution(execution_id, result=False, error_message=error_message)

        # Verify the step was moved to completed steps with failure status
        flow_info = self.tracker.flows[flow_name]
        self.assertEqual(len(flow_info.steps_executed), 1)

        failed_step = flow_info.steps_executed[0]
        self.assertEqual(failed_step.status, "failed")
        self.assertFalse(failed_step.final_result)

    def test_step_retry_tracking(self):
        """Test step retry tracking."""
        flow_name = "Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=1)

        mock_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="retry_operation",
            parameters={},
            name="Retry Step",
        )

        execution_id = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step, step_index=0)

        # Simulate retry attempts
        for i in range(3):
            retry_start = time.time()
            time.sleep(0.05)  # Simulate work
            retry_duration = time.time() - retry_start
            self.tracker.add_step_retry(execution_id, attempt=i + 1, duration=retry_duration)

        step_execution = self.tracker._active_step_executions[execution_id]
        self.assertEqual(step_execution.retry_attempts, 3)
        self.assertEqual(len(step_execution.retry_durations), 3)
        for duration in step_execution.retry_durations:
            self.assertGreater(duration, 0)

    def test_flow_failure_current_step_tracking(self):
        """Test that current_step properly shows the failed step name and error when flow fails."""
        flow_name = "Test Flow with Failure"
        self.tracker.add_flow(flow_name=flow_name, total_steps=3)

        # Execute first step successfully
        step1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="power_on",
            parameters={},
            name="Power On System",
        )
        execution_id1 = self.tracker.start_step_execution(flow_name, step1, 0)
        self.tracker.complete_step_execution(execution_id1, result=True)

        # Execute second step successfully
        step2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="check_version",
            parameters={},
            name="Version Check",
        )
        execution_id2 = self.tracker.start_step_execution(flow_name, step2, 1)
        self.tracker.complete_step_execution(execution_id2, result=True)

        # Execute third step and fail
        step3 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="firmware_update",
            parameters={},
            name="Firmware Update",
        )
        execution_id3 = self.tracker.start_step_execution(flow_name, step3, 2)
        error_msg = "Firmware validation failed: checksum mismatch"
        self.tracker.complete_step_execution(execution_id3, result=False, error_message=error_msg)

        # Mark flow as failed
        self.tracker.set_flow_failed(flow_name)

        # Verify current_step contains the failed step name and error
        flow_info = self.tracker.flows[flow_name]
        self.assertEqual(flow_info.status, "Failed")

        # The current_step should contain the step name and error message
        expected_current_step = f"Step 'Firmware Update' failed: {error_msg}"
        self.assertEqual(flow_info.current_step, expected_current_step)

    def test_step_jump_tracking(self):
        """Test step jump tracking."""
        flow_name = "Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=1)

        mock_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="jump_operation",
            parameters={},
            name="Jump Step",
        )

        execution_id = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step, step_index=0)

        self.tracker.add_step_jump(execution_id, jump_type="success", target="target_step")

        step_execution = self.tracker._active_step_executions[execution_id]
        self.assertEqual(step_execution.jump_taken, "success")
        self.assertEqual(step_execution.jump_target, "target_step")

    def test_optional_flow_tracking(self):
        """Test optional flow tracking."""
        flow_name = "Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=1)

        mock_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="optional_operation",
            parameters={},
            name="Optional Flow Step",
        )

        execution_id = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step, step_index=0)

        self.tracker.add_optional_flow_trigger(execution_id, "recovery_flow", True)
        self.tracker.add_optional_flow_trigger(execution_id, "cleanup_flow", False)

        step_execution = self.tracker._active_step_executions[execution_id]
        self.assertEqual(step_execution.optional_flows_triggered, ["recovery_flow", "cleanup_flow"])
        self.assertEqual(step_execution.optional_flow_results["recovery_flow"], True)
        self.assertEqual(step_execution.optional_flow_results["cleanup_flow"], False)

    def test_complete_flow_tracking(self):
        """Test completing flow tracking."""
        flow_name = "Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=3)

        # Add some steps
        for i in range(3):
            mock_step = FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation=f"operation_{i+1}",
                parameters={},
                name=f"Step {i+1}",
            )
            execution_id = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step, step_index=i)
            self.tracker.complete_step_execution(execution_id, result=True)

        self.tracker.set_flow_completed(flow_name)

        flow_info = self.tracker.flows[flow_name]
        self.assertEqual(flow_info.status, "Completed")
        self.assertEqual(flow_info.completed_steps, 3)

    def test_json_persistence(self):
        """Test automatic JSON persistence."""
        flow_name = "Persistence Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=1)

        # Verify JSON file was created and contains expected data
        self.assertTrue(self.json_path.exists())

        with open(self.json_path) as f:
            saved_data = json.load(f)
        self.assertIn("flows", saved_data)
        self.assertIn(flow_name, saved_data["flows"])
        saved_flow = saved_data["flows"][flow_name]
        self.assertEqual(saved_flow["status"], "Pending")
        self.assertEqual(saved_flow["total_steps"], 1)

    def test_get_flow_summary(self):
        """Test getting flow summary."""
        flow_name = "Summary Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=2)

        # Add successful step
        mock_step1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="success_operation",
            parameters={},
            name="Success Step",
        )
        execution_id1 = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step1, step_index=0)
        self.tracker.complete_step_execution(execution_id1, result=True)

        # Add failed step
        mock_step2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="failed_operation",
            parameters={},
            name="Failed Step",
        )
        execution_id2 = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step2, step_index=1)
        self.tracker.complete_step_execution(execution_id2, result=False, error_message="Test error")

        flow_info = self.tracker.get_flow_info(flow_name)

        self.assertIsNotNone(flow_info)
        self.assertEqual(flow_info.total_steps, 2)
        self.assertEqual(len(flow_info.steps_executed), 2)

        # Check success and failure counts
        successful_steps = sum(1 for step in flow_info.steps_executed if step.final_result)
        failed_steps = sum(1 for step in flow_info.steps_executed if not step.final_result)
        self.assertEqual(successful_steps, 1)
        self.assertEqual(failed_steps, 1)

    def test_concurrent_access_thread_safety(self):
        """Test thread-safe concurrent access to progress tracker."""
        flow_name = "Concurrent Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=25)  # 5 threads * 5 steps each

        results = []
        errors = []

        def worker_thread(thread_id):
            """Worker function for concurrent testing."""
            try:
                for i in range(5):
                    mock_step = FlowStep(
                        device_type=DeviceType.COMPUTE,
                        device_id=f"compute{thread_id}",
                        operation=f"thread_{thread_id}_operation_{i+1}",
                        parameters={},
                        name=f"Thread {thread_id} Step {i+1}",
                    )
                    execution_id = self.tracker.start_step_execution(
                        flow_name=flow_name,
                        step=mock_step,
                        step_index=(thread_id * 5) + i,
                    )
                    time.sleep(0.01)  # Simulate work
                    self.tracker.complete_step_execution(execution_id, result=True)
                    results.append(f"Thread {thread_id} completed step {i+1}")
            except Exception as e:
                errors.append(f"Thread {thread_id} error: {str(e)}")

        # Create and start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker_thread, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")

        # Verify all operations completed
        self.assertEqual(len(results), 25)  # 5 threads * 5 steps each

        # Verify flow has all steps
        flow_info = self.tracker.flows[flow_name]
        self.assertEqual(len(flow_info.steps_executed), 25)

    def test_memory_cleanup(self):
        """Test memory cleanup for large flows."""
        flow_name = "Large Flow Test"
        self.tracker.add_flow(flow_name=flow_name, total_steps=100)

        # Add many steps to test memory handling
        for i in range(100):
            mock_step = FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation=f"operation_{i+1}",
                parameters={},
                name=f"Step {i+1}",
            )
            execution_id = self.tracker.start_step_execution(flow_name=flow_name, step=mock_step, step_index=i)
            self.tracker.complete_step_execution(execution_id, result=True)

        # Verify all steps are tracked
        flow_info = self.tracker.flows[flow_name]
        self.assertEqual(len(flow_info.steps_executed), 100)

        # Complete flow
        self.tracker.set_flow_completed(flow_name)

        # Verify flow completion
        self.assertEqual(flow_info.status, "Completed")
        self.assertEqual(flow_info.completed_steps, 100)

    # Enhanced JSON Hierarchy Validation Tests - High Priority Implementation Alignment

    def test_optional_flow_json_hierarchy_nesting(self):
        """Test that optional flows are nested under parent flows in JSON output."""
        main_flow_name = "Main Flow with Optional"
        self.tracker.add_flow(flow_name=main_flow_name, total_steps=2)

        # Add main step that triggers optional flow
        main_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="main_operation",
            parameters={},
            name="Main Step",
        )
        main_execution_id = self.tracker.start_step_execution(flow_name=main_flow_name, step=main_step, step_index=0)

        # Create optional flow triggered by main step (use add_flow with parent metadata)
        optional_flow_name = "Optional Recovery Flow"
        self.tracker.add_flow(
            flow_name=optional_flow_name,
            total_steps=1,
            parent_flow_name=main_flow_name,
            triggered_by_step="Main Step",
        )

        # Add optional flow step
        optional_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="recovery_operation",
            parameters={},
            name="Recovery Step",
        )
        optional_execution_id = self.tracker.start_step_execution(
            flow_name=optional_flow_name, step=optional_step, step_index=0
        )

        # Complete both steps
        self.tracker.complete_step_execution(optional_execution_id, result=True)
        self.tracker.complete_step_execution(main_execution_id, result=True)

        # Complete flows
        self.tracker.set_flow_completed(optional_flow_name)
        self.tracker.set_flow_completed(main_flow_name)

        # JSON is automatically saved, read from the file
        with open(self.json_path) as f:
            saved_data = json.load(f)

        # Verify hierarchical structure in JSON
        flows_data = saved_data["flows"]
        self.assertIn(main_flow_name, flows_data)

        # Verify optional flow is nested under main flow in 'optional_flows' section
        main_flow_data = flows_data[main_flow_name]
        self.assertIn("optional_flows", main_flow_data)
        self.assertIn(optional_flow_name, main_flow_data["optional_flows"])

        # Verify optional flow has the correct structure
        optional_flow_data = main_flow_data["optional_flows"][optional_flow_name]
        self.assertIn("caller", optional_flow_data)  # This appears to be how parent is tracked
        self.assertEqual(optional_flow_data["caller"], "Main Step")

    def test_parent_flow_metadata_relationships(self):
        """Test that parent_flow_name and triggered_by_step metadata correctly links optional flows to parents."""
        parent_flow = "Parent Flow"
        child_flow_1 = "Child Recovery Flow 1"
        child_flow_2 = "Child Recovery Flow 2"

        self.tracker.add_flow(flow_name=parent_flow, total_steps=3)
        self.tracker.add_flow(
            flow_name=child_flow_1,
            total_steps=1,
            parent_flow_name=parent_flow,
            triggered_by_step="Parent Step 1",
        )
        self.tracker.add_flow(
            flow_name=child_flow_2,
            total_steps=1,
            parent_flow_name=parent_flow,
            triggered_by_step="Parent Step 2",
        )

        # Parent flow steps
        parent_step_1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="parent_op_1",
            parameters={},
            name="Parent Step 1",
        )
        parent_step_2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="parent_op_2",
            parameters={},
            name="Parent Step 2",
        )

        # Execute parent steps
        parent_exec_1 = self.tracker.start_step_execution(parent_flow, parent_step_1, 0)
        parent_exec_2 = self.tracker.start_step_execution(parent_flow, parent_step_2, 1)

        # Child flow 1 steps
        child_step_1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="child_op_1",
            parameters={},
            name="Child Step 1",
        )
        child_exec_1 = self.tracker.start_step_execution(child_flow_1, child_step_1, 0)

        # Child flow 2 steps
        child_step_2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="child_op_2",
            parameters={},
            name="Child Step 2",
        )
        child_exec_2 = self.tracker.start_step_execution(child_flow_2, child_step_2, 0)

        # Complete all executions
        self.tracker.complete_step_execution(child_exec_1, result=True)
        self.tracker.complete_step_execution(child_exec_2, result=True)
        self.tracker.complete_step_execution(parent_exec_1, result=True)
        self.tracker.complete_step_execution(parent_exec_2, result=True)

        # Complete flows
        self.tracker.set_flow_completed(child_flow_1)
        self.tracker.set_flow_completed(child_flow_2)
        self.tracker.set_flow_completed(parent_flow)

        # Verify metadata relationships in memory
        child_1_info = self.tracker.flows[child_flow_1]
        child_2_info = self.tracker.flows[child_flow_2]

        # Verify parent flow metadata is correctly set
        self.assertEqual(child_1_info.parent_flow_name, parent_flow)
        self.assertEqual(child_2_info.parent_flow_name, parent_flow)

        # Verify triggered_by_step metadata
        self.assertEqual(child_1_info.triggered_by_step, "Parent Step 1")
        self.assertEqual(child_2_info.triggered_by_step, "Parent Step 2")

        # Verify different parent steps trigger different child flows
        self.assertNotEqual(child_1_info.triggered_by_step, child_2_info.triggered_by_step)

        # Verify JSON structure reflects the hierarchical relationships
        with open(self.json_path) as f:
            saved_data = json.load(f)
        flows_data = saved_data["flows"]

        # Check that child flows are nested under parent flow
        parent_data = flows_data[parent_flow]
        self.assertIn("optional_flows", parent_data)
        self.assertIn(child_flow_1, parent_data["optional_flows"])
        self.assertIn(child_flow_2, parent_data["optional_flows"])

    def test_json_output_metadata_driven_display(self):
        """Test that JSON structure is based on metadata relationships, not flow type."""
        main_flow = "Main Orchestration Flow"
        optional_flow_1 = "Optional Flow A"
        optional_flow_2 = "Optional Flow B"
        independent_flow = "Independent Validation Flow"

        # Add all flows with appropriate metadata
        self.tracker.add_flow(flow_name=main_flow, total_steps=2)
        self.tracker.add_flow(
            flow_name=optional_flow_1,
            total_steps=1,
            parent_flow_name=main_flow,
            triggered_by_step="Main Operation",
        )
        self.tracker.add_flow(
            flow_name=optional_flow_2,
            total_steps=1,
            parent_flow_name=main_flow,
            triggered_by_step="Main Operation",
        )
        self.tracker.add_flow(flow_name=independent_flow, total_steps=1)  # No parent metadata

        # Main flow step
        main_step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="main_operation",
            parameters={},
            name="Main Operation",
        )
        main_exec = self.tracker.start_step_execution(flow_name=main_flow, step=main_step, step_index=0)

        # Optional flow 1 steps
        optional_step_1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="optional_op_1",
            parameters={},
            name="Optional Step 1",
        )
        optional_exec_1 = self.tracker.start_step_execution(
            flow_name=optional_flow_1, step=optional_step_1, step_index=0
        )

        # Optional flow 2 steps
        optional_step_2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="optional_op_2",
            parameters={},
            name="Optional Step 2",
        )
        optional_exec_2 = self.tracker.start_step_execution(
            flow_name=optional_flow_2, step=optional_step_2, step_index=0
        )

        # Independent flow steps (no parent metadata)
        independent_step = FlowStep(
            device_type=DeviceType.SWITCH,
            device_id="switch1",
            operation="independent_validation",
            parameters={},
            name="Independent Validation",
        )
        independent_exec = self.tracker.start_step_execution(
            flow_name=independent_flow, step=independent_step, step_index=0
        )

        # Complete all executions
        self.tracker.complete_step_execution(optional_exec_1, result=True)
        self.tracker.complete_step_execution(optional_exec_2, result=True)
        self.tracker.complete_step_execution(independent_exec, result=True)
        self.tracker.complete_step_execution(main_exec, result=True)

        # Complete all flows
        self.tracker.set_flow_completed(flow_name=optional_flow_1)
        self.tracker.set_flow_completed(flow_name=optional_flow_2)
        self.tracker.set_flow_completed(flow_name=independent_flow)
        self.tracker.set_flow_completed(flow_name=main_flow)

        # JSON is automatically saved, read from the file
        with open(self.json_path) as f:
            saved_data = json.load(f)

        flows_data = saved_data["flows"]

        # Verify main flow is at top level (no parent metadata)
        main_data = flows_data[main_flow]
        self.assertNotIn("parent_flow_name", main_data)

        # Verify optional flows are nested under main flow
        self.assertIn("optional_flows", main_data)
        self.assertIn(optional_flow_1, main_data["optional_flows"])
        self.assertIn(optional_flow_2, main_data["optional_flows"])

        # Verify independent flow is at top level (no parent metadata)
        self.assertIn(independent_flow, flows_data)
        independent_data = flows_data[independent_flow]
        # Independent flow should have empty optional_flows (no child flows)
        self.assertIn("optional_flows", independent_data)
        self.assertEqual(len(independent_data["optional_flows"]), 0)

        # Verify structure is metadata-driven, not based on flow name patterns
        # Both main and independent flows should be top-level despite different names
        top_level_flows = list(flows_data.keys())
        self.assertIn(main_flow, top_level_flows)
        self.assertIn(independent_flow, top_level_flows)

        # Optional flows should NOT be top-level - they should be nested
        self.assertNotIn(optional_flow_1, top_level_flows)
        self.assertNotIn(optional_flow_2, top_level_flows)

        # Verify the main flow has populated optional flows while independent doesn't
        self.assertGreater(len(main_data["optional_flows"]), 0)  # Has child flows
        self.assertEqual(len(independent_data["optional_flows"]), 0)  # No child flows

    # Performance Metrics Auto-Calculation Tests - High Priority Implementation Alignment

    def test_automatic_performance_statistics_calculation(self):
        """Test auto-calculation of performance statistics from StepExecution objects."""
        import time

        flow_name = "Performance Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=5)

        # Create steps with varying durations
        step_durations = [0.1, 0.3, 0.05, 0.25, 0.15]  # seconds
        execution_ids = []

        for i, duration in enumerate(step_durations):
            step = FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation=f"performance_op_{i+1}",
                parameters={},
                name=f"Performance Step {i+1}",
            )

            exec_id = self.tracker.start_step_execution(flow_name=flow_name, step=step, step_index=i)
            execution_ids.append(exec_id)

            # Simulate step execution time
            time.sleep(duration)
            self.tracker.complete_step_execution(exec_id, result=True)

        self.tracker.set_flow_completed(flow_name)

        # Get flow info and verify auto-calculated statistics
        flow_info = self.tracker.flows[flow_name]

        # Verify average_step_duration is calculated correctly
        total_duration = sum(step_durations)
        expected_average = total_duration / len(step_durations)
        self.assertAlmostEqual(flow_info.average_step_duration, expected_average, delta=0.05)

        # Verify longest_step_duration identifies the longest step
        expected_longest = max(step_durations)
        self.assertAlmostEqual(flow_info.longest_step_duration, expected_longest, delta=0.05)

        # Verify total_step_duration includes all step durations
        self.assertAlmostEqual(flow_info.total_step_duration, total_duration, delta=0.1)

        # Verify performance statistics are automatically updated
        self.assertIsNotNone(flow_info.average_step_duration)
        self.assertIsNotNone(flow_info.longest_step_duration)
        self.assertGreater(flow_info.longest_step_duration, 0)
        self.assertGreater(flow_info.average_step_duration, 0)

    def test_step_with_most_retries_identification(self):
        """Test identification of step with highest retry count."""
        flow_name = "Retry Test Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=3)

        # Step 1: No retries (succeeds immediately)
        step_1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="reliable_operation",
            parameters={},
            name="Reliable Step",
        )
        exec_1 = self.tracker.start_step_execution(flow_name=flow_name, step=step_1, step_index=0)
        self.tracker.complete_step_execution(exec_1, result=True)

        # Step 2: 2 retries before success
        step_2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="somewhat_reliable_operation",
            parameters={},
            name="Somewhat Reliable Step",
        )
        exec_2 = self.tracker.start_step_execution(flow_name=flow_name, step=step_2, step_index=1)

        # Add retry attempts for step 2 (using correct API)
        self.tracker.add_step_retry(exec_2, attempt=1, duration=0.1)  # First retry
        self.tracker.add_step_retry(exec_2, attempt=2, duration=0.15)  # Second retry
        self.tracker.complete_step_execution(exec_2, result=True)

        # Step 3: 4 retries before success (highest)
        step_3 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="unreliable_operation",
            parameters={},
            name="Unreliable Step",
        )
        exec_3 = self.tracker.start_step_execution(flow_name=flow_name, step=step_3, step_index=2)

        # Add retry attempts for step 3 (most retries)
        self.tracker.add_step_retry(exec_3, attempt=1, duration=0.2)  # First retry
        self.tracker.add_step_retry(exec_3, attempt=2, duration=0.25)  # Second retry
        self.tracker.add_step_retry(exec_3, attempt=3, duration=0.3)  # Third retry
        self.tracker.add_step_retry(exec_3, attempt=4, duration=0.35)  # Fourth retry
        self.tracker.complete_step_execution(exec_3, result=True)

        self.tracker.set_flow_completed(flow_name)

        # Verify step_with_most_retries is correctly identified
        flow_info = self.tracker.flows[flow_name]
        self.assertEqual(flow_info.step_with_most_retries, "Unreliable Step")

        # Verify the step objects have correct retry counts
        step_1_exec = flow_info.steps_executed[0]
        step_2_exec = flow_info.steps_executed[1]
        step_3_exec = flow_info.steps_executed[2]

        self.assertEqual(step_1_exec.retry_attempts, 0)
        self.assertEqual(step_2_exec.retry_attempts, 2)
        self.assertEqual(step_3_exec.retry_attempts, 4)

        # Verify retry durations are tracked
        self.assertEqual(len(step_3_exec.retry_durations), 4)
        self.assertGreater(sum(step_3_exec.retry_durations), 1.0)  # Total retry time

    def test_timing_statistics_accuracy(self):
        """Test accuracy of wall clock timing calculations."""
        import time

        flow_name = "Timing Accuracy Test"
        self.tracker.add_flow(flow_name=flow_name, total_steps=3)

        # Step 1: Quick step
        step_1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="quick_operation",
            parameters={},
            name="Quick Step",
        )
        exec_1 = self.tracker.start_step_execution(flow_name=flow_name, step=step_1, step_index=0)
        time.sleep(0.1)
        self.tracker.complete_step_execution(exec_1, result=True)

        # Step 2: Medium step
        step_2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="medium_operation",
            parameters={},
            name="Medium Step",
        )
        exec_2 = self.tracker.start_step_execution(flow_name=flow_name, step=step_2, step_index=1)
        time.sleep(0.15)
        self.tracker.complete_step_execution(exec_2, result=True)

        # Step 3: Slow step
        step_3 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="slow_operation",
            parameters={},
            name="Slow Step",
        )
        exec_3 = self.tracker.start_step_execution(flow_name=flow_name, step=step_3, step_index=2)
        time.sleep(0.25)
        self.tracker.complete_step_execution(exec_3, result=True)

        # Complete flow
        self.tracker.set_flow_completed(flow_name)

        # Verify timing fields exist and are reasonable
        flow_info = self.tracker.flows[flow_name]

        # Check that timing fields exist
        self.assertTrue(hasattr(flow_info, "total_testtime"))
        self.assertTrue(hasattr(flow_info, "total_step_duration"))

        # Verify timing fields are numeric
        self.assertIsInstance(flow_info.total_testtime, (int, float))
        self.assertIsInstance(flow_info.total_step_duration, (int, float))

        # Verify timing fields are non-negative (basic sanity check)
        self.assertGreaterEqual(flow_info.total_testtime, 0)
        self.assertGreaterEqual(flow_info.total_step_duration, 0)

        # Verify steps were executed (basic functionality)
        self.assertEqual(len(flow_info.steps_executed), 3)
        self.assertEqual(flow_info.completed_steps, 3)

        # If timing is calculated, verify it's reasonable
        if flow_info.total_testtime > 0:
            self.assertLess(flow_info.total_testtime, 10.0)  # Should complete within 10 seconds
        if flow_info.total_step_duration > 0:
            self.assertLess(flow_info.total_step_duration, 10.0)  # Should complete within 10 seconds

    def test_optional_flow_timing_separation(self):
        """Test timing breakdown between optional and non-optional flows."""
        import time

        # Main flow (non-optional)
        main_flow = "Main Timing Flow"
        self.tracker.add_flow(flow_name=main_flow, total_steps=2)

        # Optional flows (created with parent metadata)
        optional_flow_1 = "Optional Flow 1"
        optional_flow_2 = "Optional Flow 2"
        self.tracker.add_flow(
            flow_name=optional_flow_1,
            total_steps=1,
            parent_flow_name=main_flow,
            triggered_by_step="Main Step 1",
        )
        self.tracker.add_flow(
            flow_name=optional_flow_2,
            total_steps=1,
            parent_flow_name=main_flow,
            triggered_by_step="Main Step 2",
        )

        # Main flow step 1
        main_step_1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="main_op_1",
            parameters={},
            name="Main Step 1",
        )
        main_exec_1 = self.tracker.start_step_execution(flow_name=main_flow, step=main_step_1, step_index=0)
        time.sleep(0.1)  # 100ms main execution
        self.tracker.complete_step_execution(main_exec_1, result=True)

        # Optional flow 1 steps
        optional_step_1 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="optional_op_1",
            parameters={},
            name="Optional Step 1",
        )
        optional_exec_1 = self.tracker.start_step_execution(
            flow_name=optional_flow_1, step=optional_step_1, step_index=0
        )
        time.sleep(0.15)  # 150ms optional execution
        self.tracker.complete_step_execution(optional_exec_1, result=True)

        # Main flow step 2
        main_step_2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="main_op_2",
            parameters={},
            name="Main Step 2",
        )
        main_exec_2 = self.tracker.start_step_execution(flow_name=main_flow, step=main_step_2, step_index=1)
        time.sleep(0.12)  # 120ms main execution
        self.tracker.complete_step_execution(main_exec_2, result=True)

        # Optional flow 2 steps
        optional_step_2 = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="optional_op_2",
            parameters={},
            name="Optional Step 2",
        )
        optional_exec_2 = self.tracker.start_step_execution(
            flow_name=optional_flow_2, step=optional_step_2, step_index=0
        )
        time.sleep(0.08)  # 80ms optional execution
        self.tracker.complete_step_execution(optional_exec_2, result=True)

        # Complete all flows
        self.tracker.set_flow_completed(flow_name=optional_flow_1)
        self.tracker.set_flow_completed(flow_name=optional_flow_2)
        self.tracker.set_flow_completed(flow_name=main_flow)

        # Calculate expected timing
        expected_main_time = 0.1 + 0.12  # 220ms
        expected_optional_time = 0.15 + 0.08  # 230ms

        # Verify timing separation
        main_flow_info = self.tracker.flows[main_flow]
        optional_1_info = self.tracker.flows[optional_flow_1]
        optional_2_info = self.tracker.flows[optional_flow_2]

        # Verify main flow timing is reasonable
        self.assertGreaterEqual(main_flow_info.total_step_duration, expected_main_time - 0.05)

        # Verify optional flow timing is reasonable
        self.assertGreaterEqual(optional_1_info.total_step_duration, 0.15 - 0.02)
        self.assertGreaterEqual(optional_2_info.total_step_duration, 0.08 - 0.02)

        # Test aggregate timing calculation capabilities
        # (This tests the framework's ability to calculate total_optional_flow_testtime
        # vs total_non_optional_flow_testtime if implemented)

        # Verify non-optional flows (main) vs optional flows are tracked separately
        self.assertIsNone(main_flow_info.parent_flow_name)  # Main is not optional
        self.assertEqual(optional_1_info.parent_flow_name, main_flow)  # Optional 1 has parent
        self.assertEqual(optional_2_info.parent_flow_name, main_flow)  # Optional 2 has parent

        # Verify timing separation allows for aggregate calculations
        total_optional_time = optional_1_info.total_step_duration + optional_2_info.total_step_duration
        total_main_time = main_flow_info.total_step_duration

        self.assertGreaterEqual(total_optional_time, expected_optional_time - 0.05)
        self.assertGreaterEqual(total_main_time, expected_main_time - 0.05)

        # Verify optional flows can be distinguished from main flows for reporting
        self.assertNotEqual(total_optional_time, total_main_time)

    def test_write_json_io_error_handling(self):
        tracker = self._create_tracker(Path(self.test_dir))
        # Patch open to raise to force warning path
        from unittest.mock import patch

        with patch("FactoryMode.flow_progress_tracker.open", side_effect=OSError("disk full")):
            # Trigger a write
            tracker.start_flow_timing("flow1")
            # Just ensure no exception is raised and warning is logged via logger
            self.assertTrue(True)

    def test_summary_fields_populated_in_json(self):
        tracker = self._create_tracker(Path(self.test_dir))
        # Add flows and simulated counters
        tracker.add_flow(flow_name="main", total_steps=2)
        tracker.add_flow(flow_name="opt1", total_steps=0, parent_flow_name="main", triggered_by_step="test")
        tracker.increment_retries("main")
        tracker.increment_jump_on_success("main")
        tracker.increment_jump_on_failure("main")
        tracker.start_flow_timing("main")
        tracker.complete_flow_timing("main")
        # Force write
        tracker._write_json()
        # Read file
        content = (Path(self.test_dir) / "progress.json").read_text()
        assert "total_retry_attempts" in content
        assert "optional_flows" in content

    def test_error_messages_propagate_on_flow_failed(self):
        flow_name = "Err Flow"
        self.tracker.add_flow(flow_name=flow_name, total_steps=1)
        step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="c1",
            operation="op",
            parameters={},
            name="S1",
        )
        exec_id = self.tracker.start_step_execution(flow_name=flow_name, step=step, step_index=0)
        # Simulate collected error messages on step
        with self.tracker._step_execution_lock:
            se = self.tracker._active_step_executions[exec_id]
            se.error_messages.append("BMC connection timeout")
            se.error_messages.append("Retry exceeded")
        self.tracker.complete_step_execution(exec_id, result=False, error_message="I/O error")
        self.tracker.set_flow_failed(flow_name, failure_reason="generic fail")
        flow_info = self.tracker.flows[flow_name]
        self.assertIn("Step 'S1' failed:", flow_info.current_step)
        self.assertEqual(flow_info.error_messages, ["BMC connection timeout", "Retry exceeded"])


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
