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
Error handlers for the factory flow framework.
This module implements custom error handlers.
"""

import re
import subprocess
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from FactoryMode.flow_types import DeviceType, FlowStep
from FactoryMode.output_manager import get_log_directory, setup_logging

# Error Handler Registry
_ERROR_HANDLER_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_error_handler(name: Optional[str] = None, scope: str = "step"):
    """
    Decorator to register an error handler with metadata.

    Args:
        name (Optional[str]): Handler name (defaults to function name)
        scope (str): Handler scope - "step" for step-level, "flow" for flow-level

    Usage:
        @register_error_handler(scope="step")
        def my_error_handler(step, error, context):
            ...
    """

    def decorator(func: Callable) -> Callable:
        handler_name = name or func.__name__
        _ERROR_HANDLER_REGISTRY[handler_name] = {
            "function": func,
            "scope": scope,
            "name": handler_name,
        }

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_registered_handlers() -> Dict[str, Dict[str, Any]]:
    """
    Get all registered error handlers.

    Returns:
        Dict[str, Dict[str, Any]]: Dictionary mapping handler names to metadata
    """
    return _ERROR_HANDLER_REGISTRY.copy()


def get_handler_names() -> List[str]:
    """
    Get list of all registered error handler names.

    Returns:
        List[str]: List of handler names
    """
    return sorted(_ERROR_HANDLER_REGISTRY.keys())


@register_error_handler(scope="flow")
def error_handler_collect_nvdebug_logs(step: FlowStep, error: Exception, context: Dict[str, Any]) -> bool:
    """
    Collect NVDebug logs from the device.

    Args:
        step (FlowStep): The step that failed
        error (Exception): The error that occurred
        context (Dict[str, Any]): Additional context containing orchestrator

    Returns:
        bool: True to continue flow, False to abort
    """
    # Use orchestrator logger instead of creating a separate error_handlers.log
    orchestrator = context.get("orchestrator")
    logger = orchestrator.logger if orchestrator else setup_logging("error_handlers")

    # Log the error
    if step is None:
        # Flow-level error handler case
        logger.error(f"Flow-level error handler called: {error}")
        flow_name = context.get("flow_name", "Unknown Flow")
        logger.info(f"Collecting NVDebug logs for failed flow: {flow_name}")
    else:
        # Step-level error handler case
        logger.error(f"Step {step.name} failed: {error}")

    try:
        # Get orchestrator from context
        orchestrator = context.get("orchestrator")
        if not orchestrator:
            logger.error("Orchestrator not found in context")
            return False

        # For flow-level error handlers, we need to determine device info from context or use defaults
        if step is None:
            # This is a flow-level error handler, use default compute device configuration
            device_type = DeviceType.COMPUTE  # Default to compute for flow-level handlers
            device_id = "flow_level"  # Use a generic device ID for flow-level handlers
        else:
            device_type = step.device_type
            device_id = step.device_id

        # Get device credentials based on device type
        if device_type is None:
            logger.error("Device type is None, cannot determine credentials")
            return False

        if device_type == DeviceType.COMPUTE:
            credentials = orchestrator.compute_config.config.get("connection", {}).get("compute", {})
            platform = "arm64"
            baseboard = "GB200 NVL"
        elif device_type == DeviceType.SWITCH:
            credentials = orchestrator.switch_config.config.get("connection", {}).get("switch", {})
            platform = "NVSwitch"
            baseboard = "GB200 NVL NVSwitchTray"
        else:
            logger.error(f"Unsupported device type: {device_type}")
            return False

        bmc_creds = credentials.get("bmc", {})
        logger.info(f"Using BMC credentials for device {device_id}")

        os_creds = credentials.get("os", {})
        logger.info(f"Using OS credentials for device {device_id}")

        if not bmc_creds and not os_creds:
            operation = getattr(step, "operation", "flow_level_operation")
            logger.error(f"No credentials found for {device_type} {operation}")
            return False

        # Get nvdebug tool path from config (using variables loaded by orchestrator)
        nvdebug_path = orchestrator.compute_config.config.get("variables", {}).get(
            "nvdebug_path", "Error_Handler/nvdebug"
        )
        logger.info(f"Using nvdebug tool path: {nvdebug_path}")

        # Collect NVDebug logs using the credentials and tool path
        collect_nvdebug_logs(
            device_id=device_id,
            bmc_credentials=bmc_creds,
            os_credentials=os_creds,
            nvdebug_path=nvdebug_path,
            platform=platform,
            baseboard=baseboard,
            logger=logger,
        )

        return False  # Abort flow after collecting logs

    except Exception as e:
        logger.error(f"Failed to collect NVDebug logs: {str(e)}")
        return False


def collect_nvdebug_logs(
    *,
    device_id: str,
    bmc_credentials: Dict[str, Any],
    os_credentials: Dict[str, Any],
    nvdebug_path: str,
    platform: str,
    baseboard: str,
    logger,
) -> None:
    """
    Collect NVDebug logs from the device using provided credentials and tool path.

    Args:
        device_id (str): ID of the device
        bmc_credentials (Dict[str, Any]): BMC credentials containing ip, username, password
        os_credentials (Dict[str, Any]): OS credentials containing ip, username, password
        nvdebug_path (str): Path to the nvdebug tool
        platform (str): Platform identifier
        baseboard (str): Baseboard identifier
        logger: Logger instance to use for output
    """

    try:
        # Extract credentials
        bmc_ip = bmc_credentials.get("ip")
        bmc_username = bmc_credentials.get("username")
        bmc_password = bmc_credentials.get("password")
        # Port is available if needed: bmc_credentials.get("port", 22)

        if not all([bmc_ip, bmc_username, bmc_password]):
            logger.error("Missing required credentials for NVDEBUG run, BMC credentials are required")
            return

        logger.info(f"Collecting NVDebug logs from {device_id} at {bmc_ip}")

        log_dir = get_log_directory() / f"nvdebug_logs_{device_id}"

        # if log_dir already exists, don't collect logs again, return as an optional flow has failed
        if log_dir.exists():
            logger.info(f"Log directory {log_dir} already exists, skipping secondary NVDebug logs collection")
            return

        # Create the log directory if it doesn't exist
        log_dir.mkdir(exist_ok=True)

        if os_credentials:
            os_ip = os_credentials.get("ip")
            os_username = os_credentials.get("username")
            os_password = os_credentials.get("password")
            # Port is available if needed: os_credentials.get("port", 22)

            # Construct the nvdebug command
            cmd = [
                nvdebug_path,
                "-i",
                bmc_ip,
                "-u",
                bmc_username,
                "-p",
                bmc_password,
                "-I",
                os_ip,
                "-U",
                os_username,
                "-H",
                os_password,
                "-t",
                platform,
                "-b",
                baseboard,
                "-o",
                log_dir,
            ]
        else:
            # Construct the nvdebug command
            cmd = [
                nvdebug_path,
                "-i",
                bmc_ip,
                "-u",
                bmc_username,
                "-p",
                bmc_password,
                "-t",
                platform,
                "-b",
                baseboard,
                "-o",
                log_dir,
            ]

        # Execute the command
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"NVDebug logs collected successfully for {device_id}")
            logger.debug(f"Command output: {result.stdout}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to collect NVDebug logs: {e.stderr}")
            return
        except Exception as e:
            logger.error(f"Error executing nvdebug command: {str(e)}")
            return

    except Exception as e:
        logger.error(f"Error collecting NVDebug logs: {str(e)}")
        return


@register_error_handler(scope="step")
def error_handler_boot_failure_gb300(step: FlowStep, error: Exception, context: Dict[str, Any]) -> bool:
    """
    Analyze boot failures and check for SOCAMM memory errors (GB300 specific).

    This handler runs when wait_for_boot fails and:
    - Detects if there are 1 or 2 socket POST logs with matching timestamps
    - Selects the most recent log set to avoid analyzing old logs
    - Runs socamm_mapping.py to check for SOCAMM memory training errors
    - Provides clear diagnosis: SOCAMM error vs other boot issue
    - Hardcoded for GB300 product (gb300)

    Args:
        step (FlowStep): The step that failed (typically wait_for_boot)
        error (Exception): The error that occurred
        context (Dict[str, Any]): Additional context containing orchestrator

    Returns:
        bool: False to abort flow (since this analyzes a boot failure)
    """
    # Use orchestrator logger instead of creating a separate error_handlers.log
    orchestrator = context.get("orchestrator")
    logger = orchestrator.logger if orchestrator else setup_logging("error_handlers")

    if step is None:
        logger.error(f"Flow-level error handler called: {error}")
        flow_name = context.get("flow_name", "Unknown Flow")
        logger.info(f"Analyzing SOCAMM logs for failed flow: {flow_name}")
    else:
        logger.error(f"Step {step.name} failed: {error}")
        logger.info("Analyzing POST logs for SOCAMM errors")

    try:
        orchestrator = context.get("orchestrator")
        if not orchestrator:
            logger.error("Orchestrator not found in context")
            return False

        # Get device info
        if step is None:
            device_id = "flow_level"
        else:
            device_id = step.device_id

        # Hardcoded product for GB300
        product = "gb300"
        logger.info(f"Using hardcoded product: {product}")

        # Find POST logs in the log directory
        log_dir = get_log_directory()
        post_logs = find_recent_post_logs(log_dir, device_id)

        if not post_logs:
            logger.warning(f"No POST logs found in {log_dir} for device {device_id}")
            return False

        logger.info(f"Found {len(post_logs)} POST log(s) to analyze")

        # Get path to socamm_mapping.py
        socamm_script = find_socamm_script()
        if not socamm_script:
            logger.error("Could not find socamm_mapping.py script")
            return False

        logger.info(f"Using socamm_mapping.py script: {socamm_script}")

        # Check for common boot error conditions first
        logger.info("Checking for common boot error conditions...")
        common_errors_found = check_common_boot_errors(post_logs, logger)

        # Run socamm_mapping.py on each log
        logger.info("Running SOCAMM memory analysis...")
        socamm_errors_found = run_socamm_analysis(post_logs, socamm_script, product, logger)

        # Provide clear summary
        logger.info("=" * 80)
        logger.info("BOOT FAILURE ANALYSIS SUMMARY:")
        logger.info("-" * 80)

        if common_errors_found:
            logger.error("COMMON BOOT ERRORS DETECTED - Review error messages above")

        if socamm_errors_found:
            logger.error("SOCAMM MEMORY ERRORS DETECTED - Review analysis above for affected J-connectors")
        else:
            logger.info("SOCAMM: No memory training errors detected")

        if not common_errors_found and not socamm_errors_found:
            logger.info("No known error patterns detected in POST logs")
            logger.info("Boot failure may be due to other causes (timeout, unexpected reset, etc.)")

        logger.info("=" * 80)

        return False  # Abort flow after analyzing logs

    except Exception as e:
        logger.error(f"Failed to analyze SOCAMM logs: {str(e)}")
        return False


def find_recent_post_logs(log_dir: Path, _device_id: str) -> List[tuple]:
    """
    Find the most recent POST logs in the log directory with matching timestamps.

    Looks for files matching patterns:
    - post_log_TIMESTAMP.txt or post_log.txt (socket 0)
    - post_log_2_TIMESTAMP.txt or post_log_2.txt (socket 1)

    When timestamp-based logs are found, matches socket 0 and socket 1 logs
    by their embedded timestamp to ensure they're from the same boot attempt.

    Args:
        log_dir (Path): Directory containing log files
        _device_id (str): Device identifier (reserved for future use)

    Returns:
        List[tuple]: List of tuples (log_path, socket_id) from the same boot attempt
    """
    # Find all socket 0 logs with timestamps
    socket_0_logs = {}  # timestamp -> log_file
    socket_0_no_ts = None  # For logs without timestamps

    socket_0_patterns = ["post_log_*.txt", "post_log.txt"]
    for pattern in socket_0_patterns:
        for log_file in log_dir.glob(pattern):
            if log_file.is_file():
                # Extract timestamp from filename: post_log_YYYYMMDD_HHMMSS.txt
                match = re.search(r"post_log_(\d{8}_\d{6})\.txt", log_file.name)
                if match:
                    timestamp = match.group(1)
                    socket_0_logs[timestamp] = log_file
                elif log_file.name == "post_log.txt":
                    socket_0_no_ts = log_file

    # Find all socket 1 logs with timestamps
    socket_1_logs = {}  # timestamp -> log_file
    socket_1_no_ts = None  # For logs without timestamps

    socket_1_patterns = ["post_log_2_*.txt", "post_log_2.txt"]
    for pattern in socket_1_patterns:
        for log_file in log_dir.glob(pattern):
            if log_file.is_file():
                # Extract timestamp from filename: post_log_2_YYYYMMDD_HHMMSS.txt
                match = re.search(r"post_log_2_(\d{8}_\d{6})\.txt", log_file.name)
                if match:
                    timestamp = match.group(1)
                    socket_1_logs[timestamp] = log_file
                elif log_file.name == "post_log_2.txt":
                    socket_1_no_ts = log_file

    # Find matching timestamp pairs (most recent first)
    if socket_0_logs or socket_1_logs:
        # Get all timestamps sorted by most recent
        all_timestamps = sorted(set(socket_0_logs.keys()) | set(socket_1_logs.keys()), reverse=True)

        if all_timestamps:
            # Use the most recent timestamp
            most_recent_ts = all_timestamps[0]
            recent_logs = []

            if most_recent_ts in socket_0_logs:
                recent_logs.append((socket_0_logs[most_recent_ts], "socket_0"))

            if most_recent_ts in socket_1_logs:
                recent_logs.append((socket_1_logs[most_recent_ts], "socket_1"))

            return recent_logs

    # Fallback to non-timestamped logs
    recent_logs = []
    if socket_0_no_ts:
        recent_logs.append((socket_0_no_ts, "socket_0"))
    if socket_1_no_ts:
        recent_logs.append((socket_1_no_ts, "socket_1"))

    return recent_logs


def find_socamm_script() -> Optional[Path]:
    """
    Find the socamm_mapping.py script in the Utilities folder.

    Searches in:
    1. Current directory / FactoryMode/Utilities/
    2. Parent directory / FactoryMode/Utilities/
    3. Relative paths from common locations

    Returns:
        Optional[Path]: Path to socamm_mapping.py if found, None otherwise
    """
    # Try common paths relative to the current file
    current_file = Path(__file__).resolve()
    possible_paths = [
        # Same level as TrayFlowFunctions
        current_file.parent.parent / "Utilities" / "socamm_mapping.py",
        # From project root
        Path.cwd() / "FactoryMode" / "Utilities" / "socamm_mapping.py",
        Path.cwd() / "Utilities" / "socamm_mapping.py",
    ]

    for path in possible_paths:
        if path.exists() and path.is_file():
            return path

    return None


def check_common_boot_errors(post_logs: List[tuple], logger) -> bool:
    """
    Check POST logs for common boot error conditions.

    Args:
        post_logs (List[tuple]): List of (log_path, socket_id) tuples
        logger: Logger instance for output

    Returns:
        bool: True if any error conditions were found, False otherwise
    """
    errors_found = False

    for log_file, socket_id in post_logs:
        try:
            # Read the last 1000 lines of the log file (matching bash behavior)
            with open(log_file, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                # Get last 1000 lines or all if fewer
                last_lines = lines[-1000:] if len(lines) > 1000 else lines
                content = "".join(last_lines)

            # Check for UEFI Interactive Shell
            if re.search(r"UEFI Interactive Shell", content, re.IGNORECASE):
                logger.error(f"[{socket_id}] BIOS booted to UEFI Interactive Shell")
                errors_found = True

            # Check for PXE boot
            if re.search(r"Start PXE over IPv4", content, re.IGNORECASE):
                logger.error(f"[{socket_id}] System booted to PXE boot")
                errors_found = True

            # Check for UEFI Setup
            if re.search(r"UiApp\.dll", content, re.IGNORECASE):
                logger.error(f"[{socket_id}] System booted to UEFI Setup")
                errors_found = True

            # Check for SDRAM training failures (with bitmask)
            sdram_match = re.search(
                r"SDRAM training failed for channels.*bit mask (0x[0-9a-fA-F]+)", content, re.IGNORECASE
            )
            if sdram_match:
                bitmask = sdram_match.group(1)
                logger.error(f"[{socket_id}] SDRAM training failed with bitmask {bitmask}")
                errors_found = True

            # Check for socket channel mismatches
            socket_check_match = re.search(
                r"CROSS_SOCKET_CHECK: number of channels does not match.*socket ([0-9])", content, re.IGNORECASE
            )
            if socket_check_match:
                socket_num = socket_check_match.group(1)
                # Try to get detailed channel info
                channel_match = re.search(
                    rf"socket\[{socket_num}\] num disabled channels \(?([0-9]+)\)? mask \(?(0x[0-9a-fA-F]+)\)?",
                    content,
                    re.IGNORECASE,
                )
                if channel_match:
                    num_channels = channel_match.group(1)
                    mask = channel_match.group(2)
                    logger.error(
                        f"[{socket_id}] Socket {socket_num} channel mismatch - "
                        f"disabled channels: {num_channels}, mask: {mask}"
                    )
                else:
                    logger.error(
                        f"[{socket_id}] Socket {socket_num} channel mismatch detected " f"(details not found in log)"
                    )
                errors_found = True

        except Exception as e:
            logger.warning(f"Error checking common boot errors in {log_file.name}: {str(e)}")

    return errors_found


def run_socamm_analysis(post_logs: List[tuple], socamm_script: Path, product: str, logger) -> bool:
    """
    Run socamm_mapping.py on each POST log.

    Args:
        post_logs (List[tuple]): List of (log_path, socket_id) tuples
        socamm_script (Path): Path to socamm_mapping.py
        product (str): Product identifier (e.g., "gb300")
        logger: Logger instance for output

    Returns:
        bool: True if SOCAMM errors were found in any socket, False otherwise
    """
    errors_found = False

    for log_file, socket_id in post_logs:
        logger.info(f"Analyzing {log_file.name} for {socket_id}")

        try:
            # Construct command: python socamm_mapping.py <log_file> <socket_id> --product <product>
            cmd = [
                sys.executable,
                str(socamm_script),
                str(log_file),
                socket_id,
                "--product",
                product,
            ]

            # Run the command and capture output
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False
            )

            # Log the output (socamm_mapping.py prints results to stdout)
            if result.stdout:
                logger.info(f"SOCAMM Analysis Results for {socket_id}:")
                for line in result.stdout.strip().split("\n"):
                    logger.info(f"  {line}")
                    # Check if actual errors were found (not just "No matching log entry")
                    if "Extracted bit mask" in line or "CORE_ERROR_MSG" in line:
                        errors_found = True

            if result.stderr:
                logger.warning(f"SOCAMM Analysis Warnings for {socket_id}:")
                for line in result.stderr.strip().split("\n"):
                    logger.warning(f"  {line}")

            if result.returncode != 0:
                logger.error(f"SOCAMM analysis failed with return code {result.returncode}")

        except subprocess.TimeoutExpired:
            logger.error(f"SOCAMM analysis timed out for {log_file.name}")
        except Exception as e:
            logger.error(f"Error running SOCAMM analysis on {log_file.name}: {str(e)}")

    return errors_found
