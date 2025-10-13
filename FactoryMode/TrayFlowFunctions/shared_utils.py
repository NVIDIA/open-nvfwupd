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
Shared utilities module for common functionality across TrayFlowFunctions.

This module provides shared functions to eliminate code duplication
between different utility classes and factory flow functions.
"""

import logging
import time
from typing import Any, Optional, Tuple


def monitor_job_common(
    uri: str,
    timeout: int,
    check_interval: int,
    start_time: Optional[float],
    *,
    logger: logging.Logger,
    get_request_func: callable,
    monitor_job_func: callable,
    connection_timeout: int = 120,
) -> Tuple[bool, Any]:
    """
    Common job monitoring logic shared between HMCRedfishUtils and Utils.

    Args:
        uri (str): Job URI to monitor
        timeout (int): Maximum total monitoring time in seconds
        check_interval (int): Check interval in seconds
        start_time (Optional[float]): Start time for monitoring (used internally)
        logger (logging.Logger): Logger instance
        get_request_func (callable): Function to make GET requests
        monitor_job_func (callable): Function to recursively call for monitoring
        connection_timeout (int): Connection timeout for individual requests

    Returns:
        Tuple[bool, Any]: Success status and response data
    """
    # Initialize start_time on first call
    if start_time is None:
        start_time = time.time()

    if uri:
        # Check if we've exceeded the total monitoring time
        elapsed_time = time.time() - start_time
        if elapsed_time >= timeout:
            logger.warning(f"Task monitoring timeout of {timeout} seconds reached")
            logger.warning(f"Continuing as task {uri} may have completed in background")
            return True, {
                "TaskState": "Unknown",
                "Message": "Monitoring timeout reached",
            }

        status, response = get_request_func(uri, timeout=connection_timeout)

        # If get request is successful, check if task is completed
        if status:
            if isinstance(response, dict) and response.get("TaskState") in (
                "Cancelled",
                "Aborted",
                "Exception",
                "Completed",
            ):
                logger.info(f"Task {uri} completed with status: {response['TaskState']}")
                return True, response
            logger.info(f"Task {uri} is still running...")
        else:
            logger.error(f"Failed to monitor task {uri}: {response}")

            # For connection/timeout errors, continue monitoring until total timeout
            if is_connection_error(response):
                remaining_time = timeout - elapsed_time
                logger.warning(
                    f"Connection timeout, but continuing to monitor task {uri} (remaining time: {remaining_time:.0f}s)"
                )
            else:
                # For non-connection errors, return immediately
                return False, response

        time.sleep(check_interval)
        return monitor_job_func(uri=uri, timeout=timeout, check_interval=check_interval, start_time=start_time)
    return False, None


def is_connection_error(response: Any) -> bool:
    """
    Check if a response indicates a connection error.

    Args:
        response (Any): Response object or string to check

    Returns:
        bool: True if response indicates connection error, False otherwise
    """
    return any(
        error_type in str(response)
        for error_type in [
            "Timeout",
            "Connection",
            "ConnectTimeoutError",
            "Max retries exceeded",
        ]
    )


def validate_firmware_version_input(component: str, expected_version: Any, logger: logging.Logger) -> bool:
    """
    Validate firmware version input and log appropriate messages.

    Args:
        component (str): Component name
        expected_version (Any): Expected version value to validate
        logger (logging.Logger): Logger instance

    Returns:
        bool: True if version should be processed, False if should be skipped
    """
    if expected_version is None or expected_version == "" or expected_version == "None":
        logger.info(f"Skipping firmware version check for {component} because expected version is None or empty")
        return False
    return True


def get_completed_task_states() -> Tuple[str, ...]:
    """
    Get tuple of task states that indicate completion.

    Returns:
        Tuple[str, ...]: Task states indicating completion
    """
    return (
        "Cancelled",
        "Aborted",
        "Exception",
        "Completed",
    )


class JobMonitorMixin:
    """
    Mixin class that provides common job monitoring functionality.

    Classes using this mixin must implement get_request() method and have a logger attribute.
    """

    def monitor_job(
        self,
        *,
        uri: str,
        timeout: int = 500,
        check_interval: int = 30,
        start_time: Optional[float] = None,
    ) -> Tuple[bool, Any]:
        """
        Monitor redfish job until completion.

        Args:
            uri (str): Job URI to monitor
            timeout (int): Maximum total monitoring time in seconds
            check_interval (int): Check interval in seconds
            start_time (Optional[float]): Start time for monitoring (used internally)

        Returns:
            Tuple[bool, Any]: Success status and response data
        """
        return monitor_job_common(
            uri,
            timeout,
            check_interval,
            start_time,
            logger=self.logger,
            get_request_func=self.get_request,
            monitor_job_func=self.monitor_job,
            connection_timeout=120,
        )
