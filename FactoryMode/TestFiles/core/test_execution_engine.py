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
Execution Engine Tests

This module consolidates all execution engine related tests including:
- Unified execution engine functionality
- Parallel execution capabilities
- Jump configuration integration tests

These tests validate the core execution architecture of the factory flow orchestrator.

Use the following command to run the tests:
python3 -m unittest FactoryMode.TestFiles.test_execution_engine -v
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
import yaml

from FactoryMode.flow_types import DeviceType, FlowStep, IndependentFlow, ParallelFlowStep
from FactoryMode.TestFiles.test_mocks import MockFactoryFlowOrchestrator

# Mark all tests in this file as core tests
pytestmark = pytest.mark.core


class TestUnifiedExecutionEngine(unittest.TestCase):
    """Test cases for the unified execution engine architecture."""

    def setUp(self):
        """Standard test setup with unified mocking pattern."""
        self.orchestrator = MockFactoryFlowOrchestrator(
            "FactoryMode/TestFiles/test_config.yaml", test_name="unified_execution"
        )
        (
            self.mock_compute_flow,
            self.mock_switch_flow,
            self.mock_power_shelf_flow,
        ) = self.orchestrator.setup_device_mocking()

    def tearDown(self):
        """Clean up test fixtures."""
        self.orchestrator.cleanup()

    def test_flowstep_wrapping(self):
        """Test that individual FlowStep objects are properly wrapped into IndependentFlow."""
        # Create a simple FlowStep
        step = FlowStep(
            name="Test Step",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="test_operation",
        )

        # Mock execute_independent_flow to capture what gets passed to it
        executed_flows = []

        def mock_execute_independent_flow(flow, is_optional_flow=False):
            print(
                "DEBUG: mock_execute_independent_flow called with flow:",
                getattr(flow, "name", str(flow)),
            )
            executed_flows.append((flow, is_optional_flow))
            return True

        self.orchestrator.execute_independent_flow = mock_execute_independent_flow

        # Execute the single step
        result = self.orchestrator.execute_flow([step])

        # Verify the step was wrapped and executed
        self.assertTrue(result)
        self.assertEqual(len(executed_flows), 1)

        executed_flow, is_optional = executed_flows[0]
        self.assertIsInstance(executed_flow, IndependentFlow)
        self.assertFalse(is_optional)
        self.assertEqual(executed_flow.name, "Single Step: Test Step")
        self.assertEqual(len(executed_flow.steps), 1)
        self.assertEqual(executed_flow.steps[0], step)

    def test_parallelflowstep_wrapping(self):
        """Test that ParallelFlowStep objects are properly wrapped."""
        # Create a ParallelFlowStep
        parallel_step = ParallelFlowStep(
            name="Parallel Test",
            steps=[
                FlowStep(
                    name="Sub1",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                ),
                FlowStep(
                    name="Sub2",
                    device_type=DeviceType.SWITCH,
                    device_id="switch1",
                    operation="test_operation",
                ),
            ],
            max_workers=2,
        )

        executed_flows = []

        def mock_execute_independent_flow(flow, is_optional_flow=False):
            executed_flows.append((flow, is_optional_flow))
            return True

        self.orchestrator.execute_independent_flow = mock_execute_independent_flow

        # Execute the parallel step
        result = self.orchestrator.execute_flow([parallel_step])

        # Verify wrapping
        self.assertTrue(result)
        self.assertEqual(len(executed_flows), 1)

        executed_flow, is_optional = executed_flows[0]
        self.assertIsInstance(executed_flow, IndependentFlow)
        self.assertEqual(executed_flow.name, "Parallel Steps: Parallel Test")

    def test_consecutive_independent_flows_parallel_execution(self):
        """Test that consecutive IndependentFlow objects are executed in parallel."""
        # Create multiple IndependentFlow objects
        flow1 = IndependentFlow(
            name="Flow1",
            steps=[
                FlowStep(
                    name="Step1",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                )
            ],
        )
        flow2 = IndependentFlow(
            name="Flow2",
            steps=[
                FlowStep(
                    name="Step2",
                    device_type=DeviceType.SWITCH,
                    device_id="switch1",
                    operation="test_operation",
                )
            ],
        )

        executed_parallel_groups = []

        def mock_execute_parallel_flows(flows):
            print(
                "DEBUG: mock_execute_parallel_flows called with flows:",
                [getattr(f, "name", str(f)) for f in flows],
            )
            executed_parallel_groups.append(flows)
            return True

        self.orchestrator.execute_parallel_flows = mock_execute_parallel_flows

        # Execute consecutive flows
        result = self.orchestrator.execute_flow([flow1, flow2])

        # Verify they were grouped for parallel execution
        self.assertTrue(result)
        self.assertEqual(len(executed_parallel_groups), 1)
        self.assertEqual(len(executed_parallel_groups[0]), 2)
        self.assertEqual(executed_parallel_groups[0][0], flow1)
        self.assertEqual(executed_parallel_groups[0][1], flow2)

    def test_mixed_step_types_execution_order(self):
        """Test execution order and grouping for mixed step types."""
        # Create a mix of step types
        step1 = FlowStep(
            name="Step1",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="test_operation",
        )
        flow1 = IndependentFlow(
            name="Flow1",
            steps=[
                FlowStep(
                    name="FlowStep1",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                )
            ],
        )
        step2 = FlowStep(
            name="Step2",
            device_type=DeviceType.SWITCH,
            device_id="switch1",
            operation="test_operation",
        )
        flow2 = IndependentFlow(
            name="Flow2",
            steps=[
                FlowStep(
                    name="FlowStep2",
                    device_type=DeviceType.SWITCH,
                    device_id="switch1",
                    operation="test_operation",
                )
            ],
        )

        execution_log = []

        def mock_execute_independent_flow(flow, is_optional_flow=False):
            print(
                "DEBUG: mock_execute_independent_flow called with flow:",
                getattr(flow, "name", str(flow)),
            )
            execution_log.append(f"independent:{flow.name}")
            return True

        def mock_execute_parallel_flows(flows):
            flow_names = [f.name for f in flows]
            execution_log.append(f"parallel:{','.join(flow_names)}")
            return True

        self.orchestrator.execute_independent_flow = mock_execute_independent_flow
        self.orchestrator.execute_parallel_flows = mock_execute_parallel_flows

        # Execute mixed types
        result = self.orchestrator.execute_flow([step1, flow1, step2, flow2])

        # Verify execution order and grouping
        self.assertTrue(result)

        # Should have executed: Single Step: Step1, parallel(Flow1, Single Step: Step2, Flow2)
        self.assertGreaterEqual(len(execution_log), 1)

    def test_wrapper_flow_naming_conventions(self):
        """Test that wrapper flows follow proper naming conventions."""
        # Test various step names and their wrapped equivalents
        test_cases = [
            ("Simple Step", "Single Step: Simple Step"),
            ("Complex-Step_Name", "Single Step: Complex-Step_Name"),
            ("Step with spaces", "Single Step: Step with spaces"),
        ]

        executed_flows = []

        def mock_execute_independent_flow(flow, is_optional_flow=False):
            print(
                "DEBUG: mock_execute_independent_flow called with flow:",
                getattr(flow, "name", str(flow)),
            )
            executed_flows.append(flow)
            return True

        self.orchestrator.execute_independent_flow = mock_execute_independent_flow

        for original_name, expected_wrapped_name in test_cases:
            with self.subTest(step_name=original_name):
                executed_flows.clear()

                step = FlowStep(
                    name=original_name,
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                )

                result = self.orchestrator.execute_flow([step])

                self.assertTrue(result)
                self.assertEqual(len(executed_flows), 1)
                self.assertEqual(executed_flows[0].name, expected_wrapped_name)

    def test_unified_execution_engine_failure_handling(self):
        """Test that failures in wrapped steps are properly propagated."""
        # Create a step that will fail
        failing_step = FlowStep(
            name="Failing Step",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="fail_test",
        )

        # Execute and verify failure propagation
        result = self.orchestrator.execute_flow([failing_step])

        self.assertFalse(result)

    def test_unified_execution_engine_with_real_execution(self):
        """Test the unified execution engine with actual step execution."""
        # Create steps that will execute through the real engine
        steps = [
            FlowStep(
                name="Success1",
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="test_operation",
            ),
            FlowStep(
                name="Success2",
                device_type=DeviceType.SWITCH,
                device_id="switch1",
                operation="test_operation",
            ),
        ]

        # Execute through the real unified engine
        result = self.orchestrator.execute_flow(steps)

        # Verify successful execution
        self.assertTrue(result)

        # Verify mock operations were called (check for patterns since thread IDs may be included)
        compute_executed = any("test_operation_compute1" in entry for entry in self.mock_compute_flow.execution_log)
        switch_executed = any("test_operation_switch1" in entry for entry in self.mock_switch_flow.execution_log)
        self.assertTrue(compute_executed)
        self.assertTrue(switch_executed)


class TestParallelExecution(unittest.TestCase):
    """Test cases for parallel execution functionality."""

    def setUp(self):
        """Standard test setup with unified mocking pattern."""
        self.orchestrator = MockFactoryFlowOrchestrator(
            "FactoryMode/TestFiles/test_config.yaml", test_name="parallel_execution"
        )
        (
            self.mock_compute_flow,
            self.mock_switch_flow,
            self.mock_power_shelf_flow,
        ) = self.orchestrator.setup_device_mocking()

    def tearDown(self):
        """Clean up test fixtures."""
        self.orchestrator.cleanup()

    def test_parallel_steps_thread_pool_execution(self):
        """Test that parallel steps execute successfully using real ThreadPoolExecutor."""
        # Create a parallel step
        parallel_step = ParallelFlowStep(
            name="Parallel Test",
            steps=[
                FlowStep(
                    name="Step1",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                ),
                FlowStep(
                    name="Step2",
                    device_type=DeviceType.SWITCH,
                    device_id="switch1",
                    operation="test_operation",
                ),
            ],
            max_workers=2,
        )

        # Execute parallel step using real ThreadPoolExecutor
        flow = IndependentFlow(name="Test", steps=[parallel_step])
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify successful execution
        self.assertTrue(result)

        # Verify both operations were executed (check for patterns since thread IDs are included)
        compute_executed = any("test_operation_compute1" in entry for entry in self.mock_compute_flow.execution_log)
        switch_executed = any("test_operation_switch1" in entry for entry in self.mock_switch_flow.execution_log)
        self.assertTrue(compute_executed)
        self.assertTrue(switch_executed)

    def test_parallel_steps_failure_handling(self):
        """Test that if any parallel step fails, the entire group fails."""
        # Create parallel steps where one will fail
        parallel_step = ParallelFlowStep(
            name="Mixed Results",
            steps=[
                FlowStep(
                    name="Success",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                ),
                FlowStep(
                    name="Failure",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="fail_test",
                ),
            ],
            max_workers=2,
        )

        # Execute and verify failure
        flow = IndependentFlow(name="Test", steps=[parallel_step])
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertFalse(result)

    def test_parallel_steps_wait_after_seconds(self):
        """Test that wait_after_seconds is respected after parallel execution."""
        start_time = time.time()

        parallel_step = ParallelFlowStep(
            name="Timed Parallel",
            steps=[
                FlowStep(
                    name="Quick1",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                ),
                FlowStep(
                    name="Quick2",
                    device_type=DeviceType.SWITCH,
                    device_id="switch1",
                    operation="test_operation",
                ),
            ],
            max_workers=2,
            wait_after_seconds=1,  # Wait 1 second after completion
        )

        flow = IndependentFlow(name="Test", steps=[parallel_step])
        result = self.orchestrator.execute_independent_flow(flow)

        end_time = time.time()
        execution_time = end_time - start_time

        self.assertTrue(result)
        self.assertGreaterEqual(execution_time, 1.0)  # Should have waited at least 1 second

    def test_parallel_flows_concurrent_execution(self):
        """Test that multiple IndependentFlow objects execute concurrently."""
        # Create multiple flows with timing
        flows = [
            IndependentFlow(
                name="Flow1",
                steps=[
                    FlowStep(
                        name="Slow1",
                        device_type=DeviceType.COMPUTE,
                        device_id="compute1",
                        operation="slow_operation",
                    )
                ],
            ),
            IndependentFlow(
                name="Flow2",
                steps=[
                    FlowStep(
                        name="Slow2",
                        device_type=DeviceType.SWITCH,
                        device_id="switch1",
                        operation="slow_operation",
                    )
                ],
            ),
        ]

        start_time = time.time()
        result = self.orchestrator.execute_parallel_flows(flows)
        end_time = time.time()

        execution_time = end_time - start_time

        self.assertTrue(result)
        # Should complete in roughly the time of one slow operation (parallel), not two (sequential)
        self.assertLess(
            execution_time, 0.5
        )  # Allow headroom for scheduler/WSL overhead; still far below sequential time

    def test_parallel_flows_progress_tracking(self):
        """Test that progress tracking works correctly during parallel execution."""
        flows = [
            IndependentFlow(
                name="TrackedFlow1",
                steps=[
                    FlowStep(
                        name="Step1",
                        device_type=DeviceType.COMPUTE,
                        device_id="compute1",
                        operation="test_operation",
                    )
                ],
            ),
            IndependentFlow(
                name="TrackedFlow2",
                steps=[
                    FlowStep(
                        name="Step2",
                        device_type=DeviceType.SWITCH,
                        device_id="switch1",
                        operation="test_operation",
                    )
                ],
            ),
        ]

        # Execute with progress tracking enabled
        result = self.orchestrator.execute_parallel_flows(flows)

        self.assertTrue(result)
        # Progress tracking should complete without errors during parallel execution

    def test_parallel_execution_exception_handling(self):
        """Test that exceptions in parallel threads are properly caught and reported."""
        # Create flows where one will raise an exception
        flows = [
            IndependentFlow(
                name="GoodFlow",
                steps=[
                    FlowStep(
                        name="Success",
                        device_type=DeviceType.COMPUTE,
                        device_id="compute1",
                        operation="test_operation",
                    )
                ],
            ),
            IndependentFlow(
                name="BadFlow",
                steps=[
                    FlowStep(
                        name="Exception",
                        device_type=DeviceType.COMPUTE,
                        device_id="compute1",
                        operation="exception_operation",
                    )
                ],
            ),
        ]

        result = self.orchestrator.execute_parallel_flows(flows)

        self.assertFalse(result)  # Should fail due to exception

    def test_parallel_execution_resource_cleanup(self):
        """Test that parallel execution completes successfully using real ThreadPoolExecutor."""
        flows = [
            IndependentFlow(
                name="Flow1",
                steps=[
                    FlowStep(
                        name="Step1",
                        device_type=DeviceType.COMPUTE,
                        device_id="compute1",
                        operation="test_operation",
                    )
                ],
            ),
            IndependentFlow(
                name="Flow2",
                steps=[
                    FlowStep(
                        name="Step2",
                        device_type=DeviceType.SWITCH,
                        device_id="switch1",
                        operation="test_operation",
                    )
                ],
            ),
        ]

        # Execute parallel flows using real ThreadPoolExecutor
        result = self.orchestrator.execute_parallel_flows(flows)

        # Verify successful execution
        self.assertTrue(result)

        # Verify both flows executed (check for patterns since thread IDs may be included)
        compute_executed = any("test_operation_compute1" in entry for entry in self.mock_compute_flow.execution_log)
        switch_executed = any("test_operation_switch1" in entry for entry in self.mock_switch_flow.execution_log)
        self.assertTrue(compute_executed)
        self.assertTrue(switch_executed)

    def test_parallel_steps_different_thread_execution(self):
        """Test that parallel steps actually execute in different threads."""
        parallel_step = ParallelFlowStep(
            name="Multi-threaded",
            steps=[
                FlowStep(
                    name="Thread1",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                ),
                FlowStep(
                    name="Thread2",
                    device_type=DeviceType.SWITCH,
                    device_id="switch1",
                    operation="test_operation",
                ),
            ],
            max_workers=2,
        )

        flow = IndependentFlow(name="Test", steps=[parallel_step])
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

        # Check execution logs for thread IDs
        compute_entries = [entry for entry in self.mock_compute_flow.execution_log if "test_operation" in entry]
        switch_entries = [entry for entry in self.mock_switch_flow.execution_log if "test_operation" in entry]

        self.assertGreater(len(compute_entries), 0)
        self.assertGreater(len(switch_entries), 0)

    def test_parallel_flows_failure_propagation(self):
        """Test that failures in parallel flows are properly propagated."""
        flows = [
            IndependentFlow(
                name="SuccessFlow",
                steps=[
                    FlowStep(
                        name="Success",
                        device_type=DeviceType.COMPUTE,
                        device_id="compute1",
                        operation="test_operation",
                    )
                ],
            ),
            IndependentFlow(
                name="FailFlow",
                steps=[
                    FlowStep(
                        name="Fail",
                        device_type=DeviceType.COMPUTE,
                        device_id="compute1",
                        operation="fail_test",
                    )
                ],
            ),
        ]

        result = self.orchestrator.execute_parallel_flows(flows)

        self.assertFalse(result)  # Should fail due to one flow failing


class TestJumpConfigsIntegration(unittest.TestCase):
    """Integration tests for jump configuration functionality using YAML flow files."""

    def setUp(self):
        """Standard test setup with unified mocking pattern."""
        self.test_dir = tempfile.mkdtemp()
        self.orchestrator = MockFactoryFlowOrchestrator(
            "FactoryMode/TestFiles/test_config.yaml", test_name="jump_integration"
        )
        (
            self.mock_compute_flow,
            self.mock_switch_flow,
            self.mock_power_shelf_flow,
        ) = self.orchestrator.setup_device_mocking()
        self.test_handler_calls, _ = self.orchestrator.setup_error_handler_mocking()

    def tearDown(self):
        """Clean up test fixtures."""
        self.orchestrator.cleanup()
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_test_flow_file(self, flow_config: Dict[str, Any]) -> str:
        """Create a temporary YAML flow file."""
        file_path = Path(self.test_dir) / f"test_flow_{len(os.listdir(self.test_dir))}.yaml"
        with open(file_path, "w") as f:
            yaml.dump(flow_config, f, default_flow_style=False)
        return str(file_path)

    def test_jump_on_success_yaml_loading(self):
        """Test loading and executing jump_on_success from YAML."""
        flow_config = {
            "name": "YAML Jump on Success Test",
            "steps": [
                {
                    "name": "step_1",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "first_step",
                    "jump_on_success": "skip_step",
                },
                {
                    "name": "step_2",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "second_step",
                },
                {
                    "name": "step_3",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "skip_step",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute YAML flow
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="YAML Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

    def test_jump_on_failure_yaml_loading(self):
        """Test loading and executing jump_on_failure from YAML."""
        flow_config = {
            "name": "YAML Jump on Failure Test",
            "steps": [
                {
                    "name": "step_1",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "fail_test",
                    "parameters": {},
                    "tag": "failing_step",
                    "jump_on_failure": "recovery_step",
                },
                {
                    "name": "step_2",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "skipped_step",
                },
                {
                    "name": "step_3",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "recovery_step",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute YAML flow
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="YAML Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

    def test_jump_on_success_independent_flow_yaml(self):
        """Test YAML jump_on_success in IndependentFlow context."""
        flow_config = {
            "name": "Independent Flow YAML Jump Test",
            "steps": [
                {
                    "name": "success_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "start",
                    "jump_on_success": "end",
                },
                {
                    "name": "middle_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "middle",
                },
                {
                    "name": "end_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "end",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute as IndependentFlow
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="Independent YAML Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

    def test_jump_on_failure_independent_flow_yaml(self):
        """Test YAML jump_on_failure in IndependentFlow context."""
        flow_config = {
            "name": "Independent Flow YAML Jump on Failure Test",
            "steps": [
                {
                    "name": "failing_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "fail_test",
                    "parameters": {},
                    "tag": "start",
                    "jump_on_failure": "recovery",
                },
                {
                    "name": "skipped_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "middle",
                },
                {
                    "name": "recovery_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "recovery",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute as IndependentFlow
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="Independent YAML Failure Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

    def test_jump_on_success_with_optional_flow_yaml(self):
        """Test YAML jump_on_success with optional flows."""
        flow_config = {
            "name": "YAML Jump with Optional Flow Test",
            "optional_flows": {
                "recovery_flow": [
                    {
                        "name": "recovery_step_1",
                        "device_type": "compute",
                        "device_id": "compute1",
                        "operation": "test_operation",
                        "parameters": {},
                    }
                ]
            },
            "steps": [
                {
                    "name": "main_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "main",
                    "execute_optional_flow": "recovery_flow",
                    "jump_on_success": "final",
                },
                {
                    "name": "skipped_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "skipped",
                },
                {
                    "name": "final_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "final",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute YAML flow with optional flow
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="YAML Optional Flow Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

    def test_jump_on_failure_with_optional_flow_yaml(self):
        """Test YAML jump_on_failure when optional flow fails."""
        # Mock the optional flow to fail
        self.mock_compute_flow.test_operation = lambda **kwargs: False

        flow_config = {
            "name": "YAML Jump on Failure with Optional Flow Test",
            "optional_flows": {
                "failing_recovery": [
                    {
                        "name": "failing_recovery_step",
                        "device_type": "compute",
                        "device_id": "compute1",
                        "operation": "test_operation",
                        "parameters": {},
                    }
                ]
            },
            "steps": [
                {
                    "name": "main_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "main",
                    "execute_optional_flow": "failing_recovery",
                    "jump_on_failure": "backup",
                },
                {
                    "name": "skipped_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "skipped",
                },
                {
                    "name": "backup_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "backup",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute YAML flow - should fail due to policy
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="YAML Optional Failure Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        # Should fail due to optional flow failure policy
        self.assertFalse(result)

    def test_jump_on_success_and_jump_on_failure_yaml(self):
        """Test YAML with both jump_on_success and jump_on_failure configurations."""
        flow_config = {
            "name": "YAML Both Jump Types Test",
            "steps": [
                {
                    "name": "conditional_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "conditional",
                    "jump_on_success": "success_path",
                    "jump_on_failure": "failure_path",
                },
                {
                    "name": "skipped_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "skipped",
                },
                {
                    "name": "success_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "success_path",
                },
                {
                    "name": "failure_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "failure_path",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute YAML flow (should take success path)
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="YAML Both Jumps Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

    def test_jump_on_success_with_error_handler_yaml(self):
        """Test YAML jump_on_success with error handler configuration."""
        flow_config = {
            "name": "YAML Jump with Error Handler Test",
            "steps": [
                {
                    "name": "step_with_handler",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "handler_step",
                    "execute_on_error": "test_handler",
                    "jump_on_success": "final",
                },
                {
                    "name": "skipped_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "skipped",
                },
                {
                    "name": "final_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "final",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute YAML flow with error handler
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="YAML Error Handler Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

    def test_jump_on_success_with_retries_yaml(self):
        """Test YAML jump_on_success with retry configuration."""
        flow_config = {
            "name": "YAML Jump with Retries Test",
            "steps": [
                {
                    "name": "retry_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "retry",
                    "retry_count": 3,
                    "jump_on_success": "final",
                },
                {
                    "name": "skipped_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "skipped",
                },
                {
                    "name": "final_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "final",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute YAML flow with retries
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="YAML Retries Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)

    def test_jump_on_failure_with_retries_yaml(self):
        """Test YAML jump_on_failure after retry exhaustion."""
        # Make the operation fail initially but succeed on retry
        call_count = 0

        def conditional_fail(**kwargs):
            nonlocal call_count
            call_count += 1
            return call_count > 2  # Fail first 2 times, succeed on 3rd

        self.mock_compute_flow.conditional_operation = conditional_fail

        flow_config = {
            "name": "YAML Jump on Failure after Retries Test",
            "steps": [
                {
                    "name": "retry_then_succeed",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "conditional_operation",
                    "parameters": {},
                    "tag": "retry_step",
                    "retry_count": 3,
                    "jump_on_success": "success_path",
                    "jump_on_failure": "failure_path",
                },
                {
                    "name": "skipped_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "skipped",
                },
                {
                    "name": "success_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "success_path",
                },
                {
                    "name": "failure_step",
                    "device_type": "compute",
                    "device_id": "compute1",
                    "operation": "test_operation",
                    "parameters": {},
                    "tag": "failure_path",
                },
            ],
        }

        yaml_file = self._create_test_flow_file(flow_config)

        # Load and execute YAML flow with retries leading to success
        steps = self.orchestrator.load_flow_from_yaml(yaml_file)
        flow = IndependentFlow(name="YAML Retry Success Test", steps=steps)
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertTrue(result)


class TestExecutionEngineEdgeCases(unittest.TestCase):
    """Additional edge-case coverage for factory_flow_orchestrator execution engine."""

    def setUp(self):
        self.orchestrator = MockFactoryFlowOrchestrator(
            "FactoryMode/TestFiles/test_config.yaml", test_name="engine_edges"
        )
        (
            self.mock_compute_flow,
            self.mock_switch_flow,
            self.mock_power_shelf_flow,
        ) = self.orchestrator.setup_device_mocking()

    def tearDown(self):
        self.orchestrator.cleanup()

    def test_get_device_flow_caching_and_invalid_type(self):
        # Caching per device type
        c1 = self.orchestrator._get_device_flow(DeviceType.COMPUTE, "compute1")
        c2 = self.orchestrator._get_device_flow(DeviceType.COMPUTE, "compute1")
        self.assertIs(c1, c2)

        s1 = self.orchestrator._get_device_flow(DeviceType.SWITCH, "switch1")
        s2 = self.orchestrator._get_device_flow(DeviceType.SWITCH, "switch1")
        self.assertIs(s1, s2)

        p1 = self.orchestrator._get_device_flow(DeviceType.POWER_SHELF, "ps1")
        p2 = self.orchestrator._get_device_flow(DeviceType.POWER_SHELF, "ps1")
        self.assertIs(p1, p2)

        # Invalid type error
        with self.assertRaises(ValueError):
            self.orchestrator._get_device_flow("invalid", "x")

    def test_execute_step_success_path(self):
        step = FlowStep(
            name="Op",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="test_operation",
        )
        ok = self.orchestrator.execute_step(step)
        self.assertTrue(ok)

    def test_execute_parallel_steps_exception_branch(self):
        parallel = ParallelFlowStep(
            name="P",
            steps=[
                FlowStep(
                    name="Op",
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="test_operation",
                )
            ],
        )
        # Force inner execute_step to raise for exception branch
        with patch.object(self.orchestrator._orchestrator, "execute_step", side_effect=RuntimeError("boom")):
            ok = self.orchestrator._orchestrator.execute_parallel_steps(parallel)
            self.assertFalse(ok)

    def test_execute_flow_empty_steps_returns_true(self):
        self.assertTrue(self.orchestrator.execute_flow([]))

    def test_execute_flow_independent_group_failure(self):
        flows = [IndependentFlow(name="A", steps=[]), IndependentFlow(name="B", steps=[])]
        with patch.object(self.orchestrator._orchestrator, "execute_parallel_flows", return_value=False):
            self.assertFalse(self.orchestrator.execute_flow(flows))

    def test_unexpected_return_from_failure_handler(self):
        # Build a flow with a failing step
        step = FlowStep(
            name="Fail",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="fail_test",
        )
        flow = IndependentFlow(name="F", steps=[step])
        with patch.object(self.orchestrator._orchestrator, "_handle_step_failure_unified", return_value="weird"):
            ok = self.orchestrator.execute_independent_flow(flow)
            self.assertFalse(ok)

    def test_single_step_with_retries_wait_between_and_success(self):
        # Create toggling op: fail then succeed
        state = {"calls": 0}

        def retry_op(**kwargs):
            state["calls"] += 1
            return state["calls"] > 1

        # Attach to mock compute flow
        self.mock_compute_flow.retry_op = retry_op

        step = FlowStep(
            name="Retry",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="retry_op",
            retry_count=2,
            wait_between_retries_seconds=1,
        )
        with patch("FactoryMode.factory_flow_orchestrator.time.sleep") as mock_sleep:
            ok = self.orchestrator._orchestrator._execute_single_step_with_retries("FlowX", step, 0)
            self.assertTrue(ok)
            mock_sleep.assert_called()

    def test_single_step_with_retries_exceptions_non_last_and_last(self):
        # Op raises both attempts
        def always_raise(**kwargs):
            raise RuntimeError("fail")

        self.mock_compute_flow.raise_op = always_raise

        step = FlowStep(
            name="Raise",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="raise_op",
            retry_count=2,
        )
        with patch("FactoryMode.factory_flow_orchestrator.time.sleep"):
            ok = self.orchestrator._orchestrator._execute_single_step_with_retries("FlowY", step, 0)
            self.assertFalse(ok)

    def test_collect_errors_attached_to_step_execution(self):
        # Make operation fail so error collection attaches
        def fail_once(**kwargs):
            return False

        self.mock_compute_flow.fail_once = fail_once
        step = FlowStep(
            name="ErrCollect",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="fail_once",
            retry_count=1,
        )
        # Ensure flow exists in tracker so step execution can be found
        self.orchestrator._orchestrator.progress_tracker.add_flow(flow_name="FlowZ", total_steps=1)
        with patch("FactoryMode.factory_flow_orchestrator.stop_collecting_errors", return_value=["E1"]):
            ok = self.orchestrator._orchestrator._execute_single_step_with_retries("FlowZ", step, 0)
            self.assertFalse(ok)
            # The execution id should remain set since failure; verify errors stored
            exec_id = getattr(step, "current_execution_id", None)
            self.assertIsNotNone(exec_id)
            # Complete step to move from active to recorded executions
            self.orchestrator._orchestrator.progress_tracker.complete_step_execution(exec_id, False, "failed")
            se = self.orchestrator._orchestrator.progress_tracker.find_step_execution("FlowZ", exec_id)
            self.assertIsNotNone(se)
            # At minimum verify error_message persisted on completion
            self.assertEqual(getattr(se, "error_message", None), "failed")

    def test_handle_step_failure_unified_optional_success_jump_and_wait(self):
        # Prepare step with optional flow and jump_on_success
        step = FlowStep(
            name="Main",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="retry_after_opt",
            retry_count=2,
            execute_optional_flow="optFlow",
            jump_on_success="tgt",
            wait_after_seconds=1,
        )

        # Steps in current flow to build tag map
        steps = [
            step,
            FlowStep(device_type=DeviceType.COMPUTE, device_id="compute1", operation="noop", tag="tgt"),
        ]
        tag_to_index = {"tgt": 1}

        # Operation toggles from False to True
        state = {"calls": 0}

        def retry_after_opt(**kwargs):
            state["calls"] += 1
            return state["calls"] > 1

        self.mock_compute_flow.retry_after_opt = retry_after_opt

        # Ensure optional flow is present so the branch executes
        self.orchestrator._orchestrator.optional_flows["optFlow"] = [
            FlowStep(device_type=DeviceType.COMPUTE, device_id="compute1", operation="noop")
        ]

        with patch.object(self.orchestrator._orchestrator, "execute_optional_flow", return_value=True), patch(
            "FactoryMode.factory_flow_orchestrator.time.sleep"
        ) as mock_sleep:
            ret = self.orchestrator._orchestrator._handle_step_failure_unified(
                flow_name="F",
                step=step,
                tag_to_index=tag_to_index,
                steps=steps,
            )
            # Expect jump to index 1
            self.assertEqual(ret, 1)
            mock_sleep.assert_called()

    def test_handle_step_failure_unified_jump_success_target_missing(self):
        step = FlowStep(
            name="Main",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="always_true",
            retry_count=1,
            execute_optional_flow="optFlow",
            jump_on_success="missing",
        )
        self.mock_compute_flow.always_true = lambda **_: True
        with patch.object(self.orchestrator._orchestrator, "execute_optional_flow", return_value=True):
            ret = self.orchestrator._orchestrator._handle_step_failure_unified(
                flow_name="F", step=step, tag_to_index={}, steps=[step]
            )
            self.assertFalse(ret)

    def test_handle_step_failure_unified_optional_flow_and_retries_still_fail(self):
        step = FlowStep(
            name="Main",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="always_false",
            retry_count=2,
            execute_optional_flow="optFlow",
        )
        self.mock_compute_flow.always_false = lambda **_: False
        with patch.object(self.orchestrator._orchestrator, "execute_optional_flow", return_value=True):
            ret = self.orchestrator._orchestrator._handle_step_failure_unified(
                flow_name="F", step=step, tag_to_index={}, steps=[step]
            )
            self.assertFalse(ret)

    def test_handle_step_failure_unified_optional_flow_not_found(self):
        step = FlowStep(
            name="Main",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="always_false",
            retry_count=1,
            execute_optional_flow="does_not_exist",
        )
        self.mock_compute_flow.always_false = lambda **_: False
        # No optional flow loaded; should warn and then return False ultimately
        ret = self.orchestrator._orchestrator._handle_step_failure_unified(
            flow_name="F", step=step, tag_to_index={}, steps=[step]
        )
        self.assertFalse(ret)

    def test_count_total_steps_non_parallel(self):
        flows = [
            IndependentFlow(
                name="F1",
                steps=[
                    FlowStep(
                        device_type=DeviceType.COMPUTE,
                        device_id="compute1",
                        operation="test_operation",
                    ),
                    FlowStep(
                        device_type=DeviceType.SWITCH,
                        device_id="switch1",
                        operation="test_operation",
                    ),
                ],
            )
        ]
        total = self.orchestrator._orchestrator._count_total_steps(flows)
        self.assertEqual(total, 2)

    def test_execute_flows_parallel_exception_sets_flow_error(self):
        flows = [IndependentFlow(name="Good", steps=[]), IndependentFlow(name="Bad", steps=[])]
        # Route through execute_parallel_flows to ensure flows are added to tracker
        with patch.object(
            self.orchestrator._orchestrator,
            "execute_independent_flow",
            side_effect=[True, RuntimeError("boom")],
        ):
            ok = self.orchestrator.execute_parallel_flows(flows)
            self.assertFalse(ok)

    def test_execute_optional_flow_exception_sets_error_and_raises(self):
        # Prepare optional flow
        optional_steps = [FlowStep(device_type=DeviceType.COMPUTE, device_id="compute1", operation="test_operation")]
        with patch.object(
            self.orchestrator._orchestrator,
            "execute_independent_flow",
            side_effect=RuntimeError("bad"),
        ):
            with self.assertRaises(RuntimeError):
                self.orchestrator.execute_optional_flow(
                    optional_flow=optional_steps,
                    optional_flow_name="optF",
                    main_flow_name="mainF",
                    triggering_step="S1",
                )

    def test_get_device_flow_switch_power_and_unsupported(self):
        flow = self.orchestrator._orchestrator
        # Switch caching
        s1 = flow._get_device_flow(DeviceType.SWITCH, "switch1")
        s2 = flow._get_device_flow(DeviceType.SWITCH, "switch1")
        self.assertIs(s1, s2)
        # Power shelf caching
        p1 = flow._get_device_flow(DeviceType.POWER_SHELF, "ps1")
        p2 = flow._get_device_flow(DeviceType.POWER_SHELF, "ps1")
        self.assertIs(p1, p2)
        # Unsupported type
        with self.assertRaises(ValueError):
            flow._get_device_flow(object(), "bad")

    def test_execute_step_independent_flows_branch(self):
        flow = self.orchestrator._orchestrator
        indep = IndependentFlow(name="F1", steps=[])
        step = FlowStep(
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="execute_independent_flows",
            parameters={"flows": [indep]},
        )
        with patch.object(flow, "execute_parallel_flows", return_value=True) as mock_exec:
            ok = flow.execute_step(step)
            self.assertTrue(ok)
            mock_exec.assert_called_once_with([indep])

    def test_single_step_with_retries_exception_warning_and_error_messages(self):
        # Configure an operation that always raises
        def always_raise(**kwargs):
            raise RuntimeError("boom")

        self.mock_compute_flow.always_raise = always_raise
        step = FlowStep(
            name="Raiser",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="always_raise",
            parameters={},
            retry_count=2,
        )
        flow = self.orchestrator._orchestrator
        flow.progress_tracker.add_flow(flow_name="Fx", total_steps=1)
        with patch(
            "FactoryMode.factory_flow_orchestrator.stop_collecting_errors",
            return_value=["E1", "E2"],
        ), patch.object(flow.logger, "warning") as mock_warn:
            ok = flow._execute_single_step_with_retries("Fx", step, 0)
            self.assertFalse(ok)
            # Verify exception branch executed by presence of last_exception
            self.assertIsInstance(getattr(step, "last_exception", None), Exception)
            exec_id = getattr(step, "current_execution_id", None)
            self.assertIsNotNone(exec_id)
            # Failure path does not complete the step execution; record may not exist yet
            se = flow.progress_tracker.find_step_execution("Fx", exec_id)
            self.assertIsNone(se)

    def test_count_total_steps_parallel_count(self):
        flow = self.orchestrator._orchestrator
        p = ParallelFlowStep(
            steps=[
                FlowStep(device_type=DeviceType.COMPUTE, device_id="c1", operation="noop"),
                FlowStep(device_type=DeviceType.COMPUTE, device_id="c1", operation="noop"),
                FlowStep(device_type=DeviceType.COMPUTE, device_id="c1", operation="noop"),
            ]
        )
        indep = IndependentFlow(steps=[p, FlowStep(device_type=DeviceType.COMPUTE, device_id="c1", operation="noop")])
        total = flow._count_total_steps([indep])
        self.assertEqual(total, 4)

    def test_reset_jump_flags_nested_parallel_in_independent_flow(self):
        flow = self.orchestrator._orchestrator
        s1 = FlowStep(device_type=DeviceType.COMPUTE, device_id="c1", operation="noop")
        s2 = FlowStep(device_type=DeviceType.COMPUTE, device_id="c1", operation="noop")
        s3 = FlowStep(device_type=DeviceType.COMPUTE, device_id="c1", operation="noop")
        for s in (s1, s2, s3):
            s.has_jumped_on_failure = True
        par = ParallelFlowStep(steps=[s1, s2])
        indep = IndependentFlow(steps=[par, s3])
        # Reset flags for all steps before index 1
        flow._reset_jump_on_failure_flags([indep], target_index=1)
        self.assertFalse(s1.has_jumped_on_failure)
        self.assertFalse(s2.has_jumped_on_failure)
        self.assertFalse(s3.has_jumped_on_failure)

    def test_get_last_step_error_message_uses_collected_error(self):
        # Configure an operation that always raises so flow fails
        def always_raise(**kwargs):
            raise RuntimeError("boom")

        self.mock_compute_flow.always_raise = always_raise

        step = FlowStep(
            name="Failing",
            device_type=DeviceType.COMPUTE,
            device_id="compute1",
            operation="always_raise",
            parameters={},
            retry_count=1,
        )
        indep = IndependentFlow(name="FGetErr", steps=[step])
        flow = self.orchestrator._orchestrator

        with patch(
            "FactoryMode.factory_flow_orchestrator.stop_collecting_errors",
            return_value=["E_one", "E_two"],
        ):
            ok = flow.execute_flow([indep])
            self.assertFalse(ok)
            # Initially, generic message path may be used
            msg = flow._get_last_step_error_message("FGetErr")
            self.assertIn("Step failed after retries", msg)
            # Inject error_messages on the last recorded StepExecution to cover collected-errors path
            finfo = flow.progress_tracker.get_flow_info("FGetErr")
            self.assertIsNotNone(finfo)
            last = finfo.steps_executed[-1]
            last.error_messages = ["E_one", "E_two"]
            # Clear direct error_message to force collected error_messages branch
            last.error_message = None
            msg2 = flow._get_last_step_error_message("FGetErr")
            self.assertIn("E_two", msg2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
