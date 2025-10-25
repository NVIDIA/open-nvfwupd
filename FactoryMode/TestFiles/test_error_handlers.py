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


"""
Test error handlers for the factory flow framework.
This module demonstrates how to implement and use custom error handlers.
"""

import logging
from typing import Any, Dict

from FactoryMode.flow_types import FlowStep

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def cleanup_resources(device_id: str):
    """Example cleanup function."""
    logger.info(f"Cleaning up resources for device {device_id}")
    # Implement actual cleanup logic here


def update_device_status(device_id: str, status: str):
    """Example status update function."""
    logger.info(f"Updating device {device_id} status to {status}")
    # Implement actual status update logic here


def custom_error_handler(step: FlowStep, error: Exception, context: Dict[str, Any]) -> bool:
    """
    Example custom error handler.

    Args:
        step (FlowStep): The step that failed
        error (Exception): The error that occurred
        context (Dict[str, Any]): Additional context

    Returns:
        bool: True to continue flow, False to abort
    """
    # Log the error
    logger.error(f"Step {step.name} failed: {error}")

    # Perform cleanup
    cleanup_resources(step.device_id)

    # Update status
    update_device_status(step.device_id, "ERROR")

    # Return True to continue flow, False to abort
    return False


def retry_error_handler(step: FlowStep, error: Exception, context: Dict[str, Any]) -> bool:
    """
    Example error handler that retries the operation.

    Args:
        step (FlowStep): The step that failed
        error (Exception): The error that occurred
        context (Dict[str, Any]): Additional context

    Returns:
        bool: True to continue flow, False to abort
    """
    logger.error(f"Step {step.name} failed: {error}")

    # Check if we should retry based on error type
    if isinstance(error, ConnectionError):
        logger.info("Connection error occurred, retrying...")
        return True

    # For other errors, abort
    return False


# def main():
#     """Example usage of error handlers."""
#     # Create orchestrator instance
#     orchestrator = MockFactoryFlowOrchestrator()

#     # Register custom error handlers
#     orchestrator.register_error_handler('custom_error_handler', custom_error_handler)
#     orchestrator.register_error_handler('retry_error_handler', retry_error_handler)

#     # Example flow with error handlers
#     flow_path = "test_flow_with_error_handlers.yaml"

#     try:
#         # Load and execute flow
#         flow = orchestrator.load_flow_from_yaml(flow_path)
#         result = orchestrator.execute_flow(flow)

#         if result:
#             logger.info("Flow execution completed successfully")
#         else:
#             logger.error("Flow execution failed")

#     except Exception as e:
#         logger.error(f"Error during flow execution: {str(e)}")
#         raise

# if __name__ == "__main__":
#     main()
