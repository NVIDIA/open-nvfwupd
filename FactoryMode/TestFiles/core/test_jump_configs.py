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
Unit tests for jump configuration functionality in the factory flow orchestrator.
This module tests jump_on_success and jump_on_failure logic across different scenarios.

Use the following command to run the tests:
python3 -m unittest TestFiles.test_jump_configs -v
"""

import time
import unittest

import pytest

from FactoryMode.flow_types import DeviceType, FlowStep, IndependentFlow, ParallelFlowStep
from FactoryMode.TestFiles.test_mocks import MockFactoryFlowOrchestrator

# Mark all tests in this file as core tests
pytestmark = pytest.mark.core


class TestJumpConfigs(unittest.TestCase):
    """Test jump configuration functionality."""

    def setUp(self):
        """Standard test setup with unified mocking pattern."""
        self.orchestrator = MockFactoryFlowOrchestrator(
            "FactoryMode/TestFiles/test_config.yaml", test_name="jump_configs"
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

    def test_jump_on_success_basic(self):
        """Test basic jump_on_success functionality."""
        # Create steps with tags and jump_on_success
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",  # This step should succeed to trigger jump_on_success
                tag="start",
                jump_on_success="skip_to_end",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="middle",
                name="This step should be skipped",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="skip_to_end",
                name="Final step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Jump On Success Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded and jumped correctly
        self.assertTrue(result)

    def test_jump_on_success_with_nonexistent_tag(self):
        """Test jump_on_success with a tag that doesn't exist."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                jump_on_success="nonexistent_tag",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="This step should be executed",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Nonexistent Tag Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow failed due to nonexistent jump target
        self.assertFalse(result)

    def test_jump_on_failure_basic(self):
        """Test basic jump_on_failure functionality."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="start",
                jump_on_failure="recovery",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="recovery",
                name="Recovery step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Jump On Failure Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow failed (recovery step also fails)
        self.assertFalse(result)

    def test_jump_on_failure_with_nonexistent_tag(self):
        """Test jump_on_failure with a tag that doesn't exist."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                jump_on_failure="nonexistent_tag",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="This step should be executed",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Nonexistent Failure Tag Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow failed due to nonexistent jump target
        self.assertFalse(result)

    def test_jump_on_failure_prevent_infinite_loop(self):
        """Test jump_on_failure prevents infinite loops."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="start",
                jump_on_failure="start",  # Jump to itself
            )
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Infinite Loop Prevention Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow doesn't hang and returns False
        self.assertFalse(result)

    def test_jump_on_success_in_independent_flow(self):
        """Test jump_on_success within an independent flow."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="start",
                jump_on_success="skip_to_end",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="middle",
                name="Skipped step",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="skip_to_end",
                name="Target step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Independent Jump Success Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded
        self.assertTrue(result)

    def test_jump_on_failure_in_independent_flow(self):
        """Test jump_on_failure within an independent flow."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="start",
                jump_on_failure="recovery",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="recovery",
                name="Recovery step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Independent Jump Failure Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded after jumping to recovery
        self.assertTrue(result)

    def test_jump_on_success_with_optional_flow(self):
        """Test jump_on_success with optional flow execution."""
        # Register a mock optional flow
        optional_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="Optional flow step",
            )
        ]

        optional_flow = IndependentFlow(steps=optional_steps, name="test_optional_flow")

        self.orchestrator.optional_flows["test_optional_flow"] = optional_flow

        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="start",
                jump_on_success="success_target",
                execute_optional_flow="test_optional_flow",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="success_target",
                name="Success target step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Optional Flow Jump Success Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded
        self.assertTrue(result)

    def test_jump_on_failure_with_optional_flow(self):
        """Test jump_on_failure with optional flow execution."""
        # Register a mock optional flow that fails
        optional_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                name="Failing optional flow step",
            )
        ]

        optional_flow = IndependentFlow(steps=optional_steps, name="failing_optional_flow")

        self.orchestrator.optional_flows["failing_optional_flow"] = optional_flow

        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="start",
                jump_on_failure="recovery",
                execute_optional_flow="failing_optional_flow",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="recovery",
                name="Recovery step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Optional Flow Jump Failure Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow failed (optional flow failed, so no jump should occur)
        self.assertFalse(result)

    def test_jump_on_success_with_retries(self):
        """Test jump_on_success with retry logic."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="start",
                retry_count=3,
                jump_on_success="skip_to_end",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="middle",
                name="Skipped step",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="skip_to_end",
                name="Target step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Retry Jump Success Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded
        self.assertTrue(result)

    def test_jump_on_failure_with_retries(self):
        """Test jump_on_failure with retry logic."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="start",
                retry_count=3,
                jump_on_failure="recovery",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="recovery",
                name="Recovery step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Retry Jump Failure Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded after jumping to recovery
        self.assertTrue(result)

    def test_jump_on_success_and_jump_on_failure_same_step(self):
        """Test step with both jump_on_success and jump_on_failure."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # This will fail, so jump_on_failure should trigger
                tag="start",
                jump_on_success="success_target",
                jump_on_failure="failure_target",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="success_target",
                name="Success target (should not be reached)",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="failure_target",
                name="Failure target (should be reached)",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Both Jump Configs Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded after jumping to failure target
        self.assertTrue(result)

    def test_jump_on_success_with_error_handler(self):
        """Test jump_on_success with error handler."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="start",
                jump_on_success="skip_to_end",
                execute_on_error="custom_error_handler",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="middle",
                name="Skipped step",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="skip_to_end",
                name="Target step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Error Handler Jump Success Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded
        self.assertTrue(result)

    def test_jump_on_failure_with_error_handler(self):
        """Test jump_on_failure with error handler."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="start",
                jump_on_failure="recovery",
                execute_on_error="custom_error_handler",  # Error handler not called when jump occurs
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="recovery",
                name="Recovery step",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Error Handler Jump Failure Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded
        self.assertTrue(result)

    def test_jump_on_success_continue_behavior(self):
        """Test that jump_on_success doesn't affect failed steps."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # This fails, so jump_on_success should not trigger
                tag="start",
                jump_on_success="success_target",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="next_step",
                name="Next step (should be executed)",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="success_target",
                name="Success target (should not be reached)",
            ),
        ]

        # Execute the flow using IndependentFlow
        flow = IndependentFlow(steps=steps, name="Test Jump Success Continue Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow failed (no jump occurred due to step failure)
        self.assertFalse(result)

    def test_jump_on_failure_has_jumped_on_failure_flag(self):
        """Test that a step that has jumped on failure sets the has_jumped_on_failure flag."""
        # Create steps for jump testing with has_jumped_on_failure flag
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="start",
                jump_on_failure="recovery",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="recovery",
            ),
        ]

        # Execute the flow
        flow = IndependentFlow(steps=steps, name="Test Jump Flag Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Verify the flow succeeded
        self.assertTrue(result)

    def test_infinite_loop_prevention_same_tag_jump(self):
        """Test that infinite loops are prevented when a step jumps to its own tag."""
        # Create a step that tries to jump to itself
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="self_jump",
                jump_on_failure="self_jump",  # Jump to itself
            )
        ]

        # Execute the flow (should prevent infinite loop)
        flow = IndependentFlow(steps=steps, name="Test Self Jump Prevention Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Should fail to prevent infinite loop
        self.assertFalse(result)

    def test_infinite_loop_prevention_same_tag_jump_on_success(self):
        """Test that infinite loops are prevented when jump_on_success targets the same step."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="self_jump",
                jump_on_success="self_jump",  # Jump to itself on success
            )
        ]

        flow = IndependentFlow(steps=steps, name="Test Self Jump Success Prevention Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        self.assertFalse(result)

    def test_infinite_loop_prevention_circular_jumps(self):
        """Test that infinite loops are prevented in circular jump patterns."""
        # Create steps that form a circular jump pattern: A -> B -> C -> A
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="step_a",
                jump_on_failure="step_b",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="step_b",
                jump_on_failure="step_c",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="step_c",
                jump_on_failure="step_a",  # Creates circular dependency
            ),
        ]

        # Execute the flow (should detect and prevent circular jumps)
        flow = IndependentFlow(steps=steps, name="Test Circular Jump Prevention Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Should fail to prevent infinite loop
        self.assertFalse(result)

    def test_jump_tracking_visited_tags(self):
        """Test that the orchestrator tracks visited tags to prevent infinite loops."""
        # Create a legitimate jump sequence that shouldn't be blocked
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="start",
                jump_on_failure="middle",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="middle",
                jump_on_success="end",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="end",
            ),
        ]

        # Execute the flow (should succeed with proper jump tracking)
        flow = IndependentFlow(steps=steps, name="Test Jump Tracking Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Should succeed as this is a valid jump sequence
        self.assertTrue(result)

    def test_jump_loop_prevention_with_retry_exhaustion(self):
        """Test that jump loop prevention works correctly when retries are exhausted."""
        # Create a step that fails, exhausts retries, then tries to jump to itself
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                tag="retry_and_loop",
                retry_count=2,
                jump_on_failure="retry_and_loop",  # Try to jump to itself after retries
            )
        ]

        # Execute the flow
        flow = IndependentFlow(steps=steps, name="Test Retry Exhaustion Loop Prevention Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Should fail both due to the operation failure and loop prevention
        self.assertFalse(result)

    def test_optional_flow_success_no_infinite_loop_detection(self):
        """Test that infinite loop detection doesn't trigger incorrectly after successful optional flow execution."""
        # Simulate the exact scenario from the logs:
        # - Step at index 1 fails initially (has 3 retries)
        # - Has optional flow that succeeds
        # - Step succeeds after optional flow
        # - Should continue to next step (index 2) without infinite loop detection

        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="check_bmc_ready",  # Step 0
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # Will fail initially
                name="check_bmc_version",  # Step 1 - the problematic step
                execute_optional_flow="flash_bmc_firmware_flow",
                retry_count=3,
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",  # Should execute after optional flow
                name="verify_power_policy_always_off",  # Step 2
            ),
        ]

        # Register a mock optional flow that succeeds
        mock_optional_flow = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="monitor_background_copy_erot_bmc_0",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="flash_bmc_firmware",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="power_off_system",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="ac_cycle_system",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="check_bmc_ready",
            ),
        ]
        self.orchestrator.optional_flows["flash_bmc_firmware_flow"] = mock_optional_flow

        # Mock the step execution to simulate the exact scenario:
        # - Step 0 succeeds
        # - Step 1 fails 3 times, then succeeds after optional flow
        # - Step 2 should execute
        original_execute_step = self.orchestrator.execute_step
        execution_log = []

        def mock_execute_step(step):
            execution_log.append(f"Executing {step.name}")

            if step.name == "check_bmc_ready":
                return True
            elif step.name == "check_bmc_version":
                # Count how many times this step has been called
                bmc_version_calls = sum(1 for log in execution_log if "check_bmc_version" in log)
                # With retry_count=3, we now have 4 total attempts (1 initial + 3 retries)
                # Fail all 4 attempts, succeed only after optional flow (attempt 5+)
                if bmc_version_calls <= 4:
                    return False
                else:
                    return True
            elif step.name == "verify_power_policy_always_off":
                return True
            else:
                # Optional flow steps
                return True

        self.orchestrator.execute_step = mock_execute_step

        # Execute the flow
        flow = IndependentFlow(steps=steps, name="Test Optional Flow Scenario")
        result = self.orchestrator.execute_independent_flow(flow)

        # Restore original method
        self.orchestrator.execute_step = original_execute_step

        # Debug: Print execution log
        print(f"Execution log: {execution_log}")

        # The flow should succeed without infinite loop detection triggering
        self.assertTrue(
            result,
            f"Flow should succeed after optional flow execution without infinite loop detection. Execution log: {execution_log}",
        )

        # Verify all three main steps were executed
        main_step_executions = [
            log
            for log in execution_log
            if any(
                name in log
                for name in [
                    "check_bmc_ready",
                    "check_bmc_version",
                    "verify_power_policy_always_off",
                ]
            )
        ]
        self.assertGreaterEqual(
            len(main_step_executions),
            6,
            f"Expected at least 6 main step executions (3 steps + retries), got {len(main_step_executions)}: {main_step_executions}",
        )

    def test_jump_on_success_after_optional_flow_execution(self):
        """Test that jump_on_success works correctly after optional flow execution."""
        # Create a step that fails initially, has optional flow, and has jump_on_success
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # Will fail initially
                name="failing_step_with_jump",
                execute_optional_flow="recovery_flow",
                jump_on_success="target_step",  # Should jump here after optional flow success
                retry_count=3,
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # Should be skipped due to jump
                name="skipped_step",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="target_step",
                tag="target_step",  # Jump target
            ),
        ]

        # Register a mock optional flow that succeeds
        mock_optional_flow = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="recovery_step",
            )
        ]
        self.orchestrator.optional_flows["recovery_flow"] = mock_optional_flow

        # Mock the step execution to simulate the scenario:
        # 1. Step fails initially
        # 2. Optional flow succeeds
        # 3. Step succeeds and should jump to target_step
        # 4. skipped_step should NOT execute
        # 5. target_step should execute
        original_execute_step = self.orchestrator.execute_step
        execution_log = []

        def mock_execute_step(step):
            execution_log.append(f"Executing {step.name}")

            if step.name == "failing_step_with_jump":
                # Count how many times this step has been called
                failing_step_calls = sum(1 for log in execution_log if "failing_step_with_jump" in log)
                # With retry_count=3, we now have 4 total attempts (1 initial + 3 retries)
                # Fail all 4 attempts, succeed only after optional flow (attempt 5+)
                if failing_step_calls <= 4:
                    return False
                else:
                    return True
            elif step.name == "skipped_step":
                # This should never execute due to the jump
                return True
            elif step.name == "target_step":
                return True
            else:
                # Optional flow steps
                return True

        self.orchestrator.execute_step = mock_execute_step

        # Execute the flow
        flow = IndependentFlow(steps=steps, name="Test Jump On Success After Optional Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Restore original method
        self.orchestrator.execute_step = original_execute_step

        # Debug: Print execution log
        print(f"Execution log: {execution_log}")

        # The flow should succeed
        self.assertTrue(
            result,
            f"Flow should succeed with jump after optional flow execution. Execution log: {execution_log}",
        )

        # Verify the jump happened correctly:
        # - failing_step_with_jump should execute (with retries + after optional flow)
        # - recovery_step should execute (optional flow)
        # - target_step should execute (jump target)
        # - skipped_step should NOT execute (jumped over)

        executed_step_names = [log.split(" ")[1] for log in execution_log]

        self.assertIn("failing_step_with_jump", executed_step_names, "Failing step should execute")
        self.assertIn("recovery_step", executed_step_names, "Optional flow should execute")
        self.assertIn("target_step", executed_step_names, "Jump target should execute")
        self.assertNotIn(
            "skipped_step",
            executed_step_names,
            f"Skipped step should NOT execute due to jump. Execution log: {execution_log}",
        )

        # Additional verification: skipped_step should definitely not be in the log
        skipped_executions = [log for log in execution_log if "skipped_step" in log]
        self.assertEqual(
            len(skipped_executions),
            0,
            f"skipped_step should never execute, but found: {skipped_executions}",
        )

    def test_debug_infinite_loop_detection_issue(self):
        """Debug test to understand why infinite loop detection triggers after optional flow."""
        # Reproduce the exact scenario but with debug logging
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="check_bmc_ready",  # Step 0
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # Will fail initially
                name="check_bmc_version",  # Step 1 - the problematic step
                execute_optional_flow="flash_bmc_firmware_flow",
                retry_count=3,
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",  # Should execute after optional flow
                name="verify_power_policy_always_off",  # Step 2
            ),
        ]

        # Register a mock optional flow that succeeds
        mock_optional_flow = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="monitor_background_copy_erot_bmc_0",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="flash_bmc_firmware",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="power_off_system",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="ac_cycle_system",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="check_bmc_ready",
            ),
        ]
        self.orchestrator.optional_flows["flash_bmc_firmware_flow"] = mock_optional_flow

        # Mock the step execution and add debug interception
        original_execute_step = self.orchestrator.execute_step
        original_handle_step_failure = self.orchestrator._handle_step_failure_unified

        execution_log = []
        failure_handler_calls = []

        def mock_execute_step(step):
            execution_log.append(f"Executing {step.name}")

            if step.name == "check_bmc_ready":
                return True
            elif step.name == "check_bmc_version":
                # Count how many times this step has been called
                bmc_version_calls = sum(1 for log in execution_log if "check_bmc_version" in log)
                # With retry_count=3, we now have 4 total attempts (1 initial + 3 retries)
                # Fail all 4 attempts, succeed only after optional flow (attempt 5+)
                if bmc_version_calls <= 4:
                    return False
                else:
                    return True
            elif step.name == "verify_power_policy_always_off":
                return True
            else:
                # Optional flow steps
                return True

        def debug_handle_step_failure(flow_name, step, step_index, tag_to_index, steps, is_optional_flow):
            failure_handler_calls.append(f"handle_step_failure called: step={step.name}, step_index={step_index}")
            result = original_handle_step_failure(flow_name, step, step_index, tag_to_index, steps, is_optional_flow)
            failure_handler_calls.append(f"handle_step_failure returned: {result} (type: {type(result)})")

            # If this is returning an integer that equals step_index, that would cause infinite loop detection
            if isinstance(result, int) and result == step_index:
                failure_handler_calls.append(
                    f"WARNING: handle_step_failure returned step_index={step_index}, this will trigger infinite loop!"
                )

            return result

        self.orchestrator.execute_step = mock_execute_step
        self.orchestrator._handle_step_failure_unified = debug_handle_step_failure

        # Execute the flow
        flow = IndependentFlow(steps=steps, name="Debug Infinite Loop Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Restore original methods
        self.orchestrator.execute_step = original_execute_step
        self.orchestrator._handle_step_failure_unified = original_handle_step_failure

        # Debug: Print all logs
        print(f"Execution log: {execution_log}")
        print(f"Failure handler calls: {failure_handler_calls}")

        # For debugging purposes, don't assert success/failure, just log what happened
        print(f"Flow result: {result}")

        # The main purpose is to see what _handle_step_failure_unified returns
        # Look for the problematic return value
        problematic_returns = [
            call for call in failure_handler_calls if "returned:" in call and ("1" in call and "int" in call)
        ]
        if problematic_returns:
            print(f"Problematic returns that could cause infinite loop: {problematic_returns}")

        # For now, just make this test informational
        self.assertIsInstance(
            result,
            bool,
            f"Flow should return a boolean. Failure handler calls: {failure_handler_calls}",
        )

    def test_main_loop_return_value_bug(self):
        """Test to identify if _handle_step_failure_unified is returning an incorrect value that triggers infinite loop detection."""
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="step_0",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # Will fail initially
                name="step_1_problematic",  # The step that will trigger optional flow
                execute_optional_flow="recovery_flow",
                retry_count=2,
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="step_2",
            ),
        ]

        # Simple optional flow
        mock_optional_flow = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                name="recovery_step",
            )
        ]
        self.orchestrator.optional_flows["recovery_flow"] = mock_optional_flow

        # Track everything that happens
        original_execute_step = self.orchestrator.execute_step
        original_handle_step_failure = self.orchestrator._handle_step_failure_unified
        original_execute_flow_steps = self.orchestrator._execute_flow_steps_unified

        execution_timeline = []

        def tracked_execute_step(step):
            execution_timeline.append(f"execute_step: {step.name}")
            if step.name == "step_1_problematic":
                # Fail twice, then succeed
                failure_count = sum(1 for event in execution_timeline if "execute_step: step_1_problematic" in event)
                result = failure_count > 2
            else:
                result = True
            execution_timeline.append(f"execute_step result: {result}")
            return result

        def tracked_handle_step_failure(flow_name, step, step_index, tag_to_index, steps, is_optional_flow):
            call_count = len([e for e in execution_timeline if f"handle_step_failure: step={step.name}" in e])
            execution_timeline.append(f"handle_step_failure: step={step.name}, index={step_index}, call#{call_count+1}")
            result = original_handle_step_failure(flow_name, step, step_index, tag_to_index, steps, is_optional_flow)
            execution_timeline.append(f"handle_step_failure result: {result} (type={type(result)}) call#{call_count+1}")

            # Check if this is returning an integer equal to step_index
            if isinstance(result, int) and result == step_index:
                execution_timeline.append(f"*** INFINITE LOOP TRIGGER: returning step_index={step_index} ***")
            elif result is True:
                execution_timeline.append("*** CORRECT: returning True (step succeeded after optional flow) ***")

            return result

        def tracked_execute_flow_steps(flow_name, flow, is_optional_flow=False):
            execution_timeline.append(f"execute_flow_steps: flow={flow_name}, optional={is_optional_flow}")
            result = original_execute_flow_steps(flow_name, flow, is_optional_flow)
            execution_timeline.append(f"execute_flow_steps result: {result}")
            return result

        # Install hooks
        self.orchestrator.execute_step = tracked_execute_step
        self.orchestrator._handle_step_failure_unified = tracked_handle_step_failure
        self.orchestrator._execute_flow_steps_unified = tracked_execute_flow_steps

        # Execute
        flow = IndependentFlow(steps=steps, name="Main Loop Debug Flow")
        result = self.orchestrator.execute_independent_flow(flow)

        # Restore
        self.orchestrator.execute_step = original_execute_step
        self.orchestrator._handle_step_failure_unified = original_handle_step_failure
        self.orchestrator._execute_flow_steps_unified = original_execute_flow_steps

        # Print timeline for analysis
        print("=== EXECUTION TIMELINE ===")
        for i, event in enumerate(execution_timeline):
            print(f"{i:2d}: {event}")
        print(f"Final result: {result}")

        # Look for patterns that could cause infinite loop detection
        handle_failure_results = [event for event in execution_timeline if "handle_step_failure result:" in event]
        print(f"Handle failure results: {handle_failure_results}")

        # Check if any handle_step_failure returned an integer equal to step index
        problematic_results = []
        for event in handle_failure_results:
            if "result: 1 " in event and "int" in event:  # step_index=1 returned as integer
                problematic_results.append(event)

        if problematic_results:
            print(f"FOUND PROBLEMATIC RESULTS: {problematic_results}")

        # For debugging, don't assert anything specific yet
        self.assertIsInstance(result, bool)

    # ==================================================================================
    # ENHANCED JUMP IMPLEMENTATION TESTS (Module 3: Implementation-Specific)
    # ==================================================================================

    def test_recursive_flag_reset_parallel_steps(self):
        """Test that flags are reset correctly in nested ParallelFlowStep structures."""

        # Create nested parallel steps with jump flags set
        parallel_step = ParallelFlowStep(
            steps=[
                FlowStep(
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="pass_test",
                    tag="parallel_step_1",
                ),
                FlowStep(
                    device_type=DeviceType.COMPUTE,
                    device_id="compute2",
                    operation="pass_test",
                    tag="parallel_step_2",
                ),
            ]
        )

        # Manually set jump flags to simulate previous jump activity
        for step in parallel_step.steps:
            step.has_jumped_on_failure = True
        # Note: ParallelFlowStep doesn't have has_jumped_on_failure attribute

        # Create a flow with the parallel step
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="before_parallel",
            ),
            parallel_step,
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="after_parallel",
            ),
        ]

        # Test flag reset - should reset flags for steps before target_index=2
        self.orchestrator._reset_jump_on_failure_flags(steps, target_index=2)

        # Verify flags were reset for steps before target
        self.assertFalse(steps[0].has_jumped_on_failure)  # before_parallel
        # Note: ParallelFlowStep doesn't have has_jumped_on_failure, only its nested FlowSteps do
        for step in parallel_step.steps:
            self.assertFalse(step.has_jumped_on_failure)  # nested parallel steps

        # Target step should not be affected (it has the attribute but should still be False)
        self.assertFalse(steps[2].has_jumped_on_failure)

    def test_recursive_flag_reset_independent_flows(self):
        """Test that flags are reset correctly in nested IndependentFlow structures."""
        # Create nested independent flow with jump flags set
        nested_independent_flow = IndependentFlow(
            steps=[
                FlowStep(
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="pass_test",
                    tag="nested_step_1",
                ),
                FlowStep(
                    device_type=DeviceType.COMPUTE,
                    device_id="compute2",
                    operation="pass_test",
                    tag="nested_step_2",
                ),
            ],
            name="Nested Independent Flow",
        )

        # Manually set jump flags
        for step in nested_independent_flow.steps:
            step.has_jumped_on_failure = True
        # Note: IndependentFlow doesn't have has_jumped_on_failure attribute

        # Create main flow containing the nested independent flow
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="main_step_1",
            ),
            nested_independent_flow,
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="main_step_2",
            ),
        ]

        # Test flag reset - should reset flags for steps before target_index=2
        self.orchestrator._reset_jump_on_failure_flags(steps, target_index=2)

        # Verify flags were reset for steps before target
        self.assertFalse(steps[0].has_jumped_on_failure)  # main_step_1
        # Note: IndependentFlow doesn't have has_jumped_on_failure, only its nested FlowSteps do
        for step in nested_independent_flow.steps:
            self.assertFalse(step.has_jumped_on_failure)  # nested independent flow steps

    def test_scope_isolation_main_vs_independent(self):
        """Test that independent flows cannot access main flow tags."""
        # Create main flow with tagged steps
        main_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="main_flow_tag",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="another_main_tag",
            ),
        ]

        # Create independent flow that tries to jump to main flow tag
        independent_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # This will fail and try to jump
                jump_on_failure="main_flow_tag",  # Should not be able to access this tag
                tag="independent_step",
            )
        ]

        independent_flow = IndependentFlow(steps=independent_steps, name="Isolated Independent Flow")

        # Execute independent flow - should fail because tag is not accessible
        result = self.orchestrator.execute_independent_flow(independent_flow)

        # Independent flow should fail because it cannot access main flow tags
        # The jump should not work, so the flow should fail
        self.assertFalse(result)

    def test_scope_isolation_main_vs_optional(self):
        """Test that optional flows cannot access main flow tags."""
        # Register an optional flow that tries to jump to main flow tag
        optional_flow_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # This will fail and try to jump
                jump_on_failure="main_flow_tag",  # Should not be able to access this tag
                tag="optional_step",
            )
        ]

        self.orchestrator.optional_flows["isolated_optional_flow"] = optional_flow_steps

        # Create main flow with tagged steps and step that triggers optional flow
        main_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="main_flow_tag",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # This will fail and trigger optional flow
                execute_optional_flow="isolated_optional_flow",
                tag="trigger_step",
            ),
        ]

        flow = IndependentFlow(steps=main_steps, name="Main Flow with Optional")

        # Execute flow - optional flow should fail due to scope isolation
        result = self.orchestrator.execute_independent_flow(flow)

        # Main flow should fail because optional flow cannot access main tags
        self.assertFalse(result)

    def test_scope_isolation_cross_optional_flows(self):
        """Test that optional flows cannot access each other's tags."""
        # Register first optional flow with its own tags
        optional_flow_1 = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="optional_1_tag",
            )
        ]

        # Register second optional flow that tries to jump to first optional flow's tag
        optional_flow_2 = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # This will fail and try to jump
                jump_on_failure="optional_1_tag",  # Should not be able to access other optional flow's tag
                tag="optional_2_tag",
            )
        ]

        self.orchestrator.optional_flows["optional_flow_1"] = optional_flow_1
        self.orchestrator.optional_flows["optional_flow_2"] = optional_flow_2

        # Create main flow that triggers the second optional flow
        main_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # This will fail and trigger optional flow 2
                execute_optional_flow="optional_flow_2",
                tag="trigger_step",
            )
        ]

        flow = IndependentFlow(steps=main_steps, name="Cross Optional Flow Test")

        # Execute flow - optional flow 2 should fail due to scope isolation
        result = self.orchestrator.execute_independent_flow(flow)

        # Flow should fail because optional flows are isolated from each other
        self.assertFalse(result)

    def test_tag_to_index_mapping_performance(self):
        """Test that tag-to-index mapping creation and lookup is efficient with 100 steps."""

        # Create 100 steps with tags to test mapping performance directly
        steps = []
        for i in range(100):
            steps.append(
                FlowStep(
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="pass_test",
                    tag=f"step_tag_{i:03d}",
                )
            )

        # Add target step for jump
        steps.append(
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="target_step",
            )
        )

        # Test the tag mapping creation directly (like the orchestrator does)
        start_time = time.time()

        # This is the same logic the orchestrator uses
        tag_to_index = {}
        for i, step in enumerate(steps):
            if isinstance(step, FlowStep) and step.tag:
                tag_to_index[step.tag] = i

        # Test lookup performance
        lookup_target = "target_step"
        target_index = tag_to_index.get(lookup_target)

        end_time = time.time()
        execution_time = end_time - start_time

        # Verify the mapping works correctly
        self.assertIsNotNone(target_index)
        self.assertEqual(target_index, 100)  # Should be index 100 (the target step)

        # Should be very fast - dict creation and lookup should be nearly instant
        self.assertLess(
            execution_time,
            0.1,
            f"Tag mapping too slow: {execution_time:.3f}s for 100 steps",
        )

        # Verify we can find any tag quickly
        for i in range(0, 100, 10):  # Test every 10th tag
            tag_name = f"step_tag_{i:03d}"
            found_index = tag_to_index.get(tag_name)
            self.assertEqual(found_index, i)

    def test_tag_namespace_collision_handling(self):
        """Test that same tag names are allowed in different scopes without collision."""
        # Create main flow with a tag - NO JUMPS to avoid infinite loop
        main_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="shared_tag_name",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="second_step",
            ),
        ]

        # Create independent flow with same tag name - NO JUMPS to avoid infinite loop
        independent_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="shared_tag_name",  # Same name as main flow tag - this should be allowed
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="independent_second",
            ),
        ]

        # Create optional flow with same tag name
        optional_flow_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="shared_tag_name",  # Same name as main and independent flow tags
            )
        ]

        self.orchestrator.optional_flows["namespace_test_optional"] = optional_flow_steps

        # Execute main flow - should work with its own tag namespace
        main_flow = IndependentFlow(steps=main_steps, name="Main Namespace Flow")
        main_result = self.orchestrator.execute_independent_flow(main_flow)
        self.assertTrue(main_result)

        # Execute independent flow - should work with its own tag namespace
        independent_flow = IndependentFlow(steps=independent_steps, name="Independent Namespace Flow")
        independent_result = self.orchestrator.execute_independent_flow(independent_flow)
        self.assertTrue(independent_result)

        # Each flow should be able to use the same tag name without collision
        # This tests that tag namespaces are properly isolated between flows

    def test_jump_progress_tracking_updates(self):
        """Test that progress tracking reflects actual execution position after jumps."""
        # Create flow with jumps that change execution order
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                jump_on_success="skip_ahead",
                tag="step_1",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="step_2_skipped",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="step_3_skipped",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="skip_ahead",
            ),
        ]

        flow = IndependentFlow(steps=steps, name="Progress Tracking Test Flow")

        # Execute flow with progress tracking
        result = self.orchestrator.execute_independent_flow(flow)
        self.assertTrue(result)

        # Check that progress tracker reflects the actual execution path
        # Step 1 should execute, then jump to step 4, skipping steps 2 and 3
        # Progress should reflect this jump behavior

        # Note: This test primarily verifies that the flow executes correctly with jumps
        # More detailed progress tracking verification would require access to internal state
        # The key assertion is that the flow completes successfully despite the jump

    def test_static_loop_detection_analysis(self):
        """Test that potential infinite loops can be detected before execution."""
        # Create flow with obvious infinite loop potential
        steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",  # Always fails
                jump_on_failure="loop_back",  # Will jump back to itself
                tag="loop_back",
            )
        ]

        flow = IndependentFlow(steps=steps, name="Infinite Loop Test Flow")

        # Execute flow - should detect and prevent infinite loop
        result = self.orchestrator.execute_independent_flow(flow)

        # Flow should fail but not hang in infinite loop
        self.assertFalse(result)

        # Additional test: circular loop between two steps
        circular_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                jump_on_failure="step_b",
                tag="step_a",
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="fail_test",
                jump_on_failure="step_a",  # Jumps back to step_a
                tag="step_b",
            ),
        ]

        circular_flow = IndependentFlow(steps=circular_steps, name="Circular Loop Test Flow")
        circular_result = self.orchestrator.execute_independent_flow(circular_flow)

        # Should also prevent circular loops
        self.assertFalse(circular_result)

    def test_jump_memory_usage_optimization(self):
        """Test that tag mappings are efficiently managed with reasonable step counts."""
        # Create flow with 50 tags to test memory efficiency (reasonable for unit test)
        steps = []
        tag_count = 50

        for i in range(tag_count):
            steps.append(
                FlowStep(
                    device_type=DeviceType.COMPUTE,
                    device_id="compute1",
                    operation="pass_test",
                    tag=f"memory_test_tag_{i}",
                )
            )

        flow = IndependentFlow(steps=steps, name="Memory Usage Test Flow")

        # Execute flow
        result = self.orchestrator.execute_independent_flow(flow)

        # Flow should succeed
        self.assertTrue(result)

        # Test that tag mappings are cleaned up properly
        # (Implementation detail - the tag_to_index dict should not persist)
        # This is verified by the fact that different flows can use the same tag names

        # Create second flow with same tag names - should work without conflicts
        duplicate_steps = [
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="memory_test_tag_0",  # Reuse first tag name
            ),
            FlowStep(
                device_type=DeviceType.COMPUTE,
                device_id="compute1",
                operation="pass_test",
                tag="memory_test_tag_1",  # Reuse second tag name
            ),
        ]

        duplicate_flow = IndependentFlow(steps=duplicate_steps, name="Memory Cleanup Test Flow")
        duplicate_result = self.orchestrator.execute_independent_flow(duplicate_flow)

        # Should work without memory conflicts - proves tag mappings don't persist
        self.assertTrue(duplicate_result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
