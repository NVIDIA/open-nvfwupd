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
Output Mode Manager and Logging Utilities - Centralized output/logging control

This module provides a unified interface for all output and logging operations in the
factory flow system. It combines output mode management with file-based logging utilities.

Key Features:
    - Four distinct output modes (none, gui, log, json)
    - File-only logging with thread-safe error collection
    - Rich GUI progress tracking
    - Real-time log streaming
    - JSON pretty-printing on stage completion
    - Log directory management

Output Modes:
    - none: No console/GUI output, only file logging
    - gui: Rich GUI with progress bars and live updates
    - log: Stream full log file content to console in real-time
    - json: Pretty-print flow_summary.json updates as stages complete

Architecture:
    The OutputModeManager serves as the single source of truth for output behavior,
    coordinating between logging (file), console (stdout), GUI (Rich), and JSON display.

Usage:
    >>> from pathlib import Path
    >>> manager = OutputModeManager(
    ...     mode=OutputMode.GUI,
    ...     log_directory=Path("logs"),
    ...     json_file_path=Path("logs/flow_progress.json"),
    ...     logger=logging.getLogger(__name__)
    ... )
    >>> manager.on_flow_started("main_flow", total_steps=10)
    >>> manager.on_step_completed("main_flow", step_execution_obj)
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import BarColumn, Progress, ProgressColumn, TextColumn
from rich.table import Table
from rich.text import Text

from FactoryMode.flow_types import OutputMode

# Disable paramiko logging except for errors
logging.getLogger("paramiko").setLevel(logging.ERROR)


# ==============================================================================
# LOGGING UTILITIES - File-based logging with thread-safe error collection
# ==============================================================================


class _LoggingState:
    """Internal class to encapsulate logging state without global variables."""

    def __init__(self):
        self.current_log_dir = None
        self.custom_log_dir = None
        self.lock = threading.Lock()


# Module-level instance to store logging state
_logging_state = _LoggingState()

# Thread-local storage for error messages
_thread_local = threading.local()


def _get_thread_errors():
    """Get the error list for the current thread."""
    if not hasattr(_thread_local, "error_messages"):
        _thread_local.error_messages = []
    return _thread_local.error_messages


def _get_thread_collecting():
    """Check if the current thread is collecting errors."""
    return getattr(_thread_local, "collecting_errors", False)


def _set_thread_collecting(collecting):
    """Set whether the current thread is collecting errors."""
    _thread_local.collecting_errors = collecting


class AutoErrorCollectorHandler(logging.Handler):
    """Handler that automatically collects ERROR messages when thread-local collection is enabled."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        """Capture ERROR level log messages if collection is enabled for this thread."""
        if record.levelno >= logging.ERROR and _get_thread_collecting():
            formatted_message = record.getMessage()
            _get_thread_errors().append(formatted_message)


def start_collecting_errors():
    """Start collecting ERROR messages for the current thread."""
    _set_thread_collecting(True)
    _get_thread_errors().clear()


def stop_collecting_errors():
    """Stop collecting ERROR messages for the current thread and return collected errors."""
    _set_thread_collecting(False)
    return _get_thread_errors().copy()


def get_collected_errors():
    """Get currently collected error messages for the current thread."""
    return _get_thread_errors().copy()


class ErrorCollectorHandler(logging.Handler):
    """Handler that collects ERROR level messages into a list."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.error_messages = []

    def emit(self, record):
        """Capture ERROR level log messages."""
        if record.levelno >= logging.ERROR:
            formatted_message = self.format(record)
            self.error_messages.append(formatted_message)

    def get_errors(self):
        """Get collected error messages."""
        return self.error_messages.copy()

    def clear_errors(self):
        """Clear collected error messages."""
        self.error_messages.clear()


class ErrorCapture:
    """Context manager for capturing ERROR messages without interfering with existing logging setup."""

    def __init__(self, logger_name: str):
        self.logger_name = logger_name
        self.logger = logging.getLogger(logger_name)
        self.error_collector = ErrorCollectorHandler()
        self.original_error_method = None
        self.captured_errors = []

    def __enter__(self):
        """Start capturing ERROR messages by temporarily intercepting the logger's error method."""
        self.original_error_method = self.logger.error

        def capture_error(msg, *args, **kwargs):
            # Call the original error method first (maintains existing behavior)
            self.original_error_method(msg, *args, **kwargs)
            # Then capture the formatted message
            if args:
                formatted_msg = msg % args
            else:
                formatted_msg = str(msg)
            self.captured_errors.append(formatted_msg)

        # Temporarily replace the error method
        self.logger.error = capture_error
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore the original error method."""
        if self.original_error_method:
            self.logger.error = self.original_error_method

    def get_errors(self):
        """Get captured error messages."""
        return self.captured_errors.copy()


def start_error_collection(logger_name: str) -> ErrorCollectorHandler:
    """
    Start collecting ERROR messages for a specific logger.

    Args:
        logger_name (str): Name of the logger to monitor

    Returns:
        ErrorCollectorHandler: Handler instance that can be used to retrieve errors
    """
    logger = logging.getLogger(logger_name)
    error_collector = ErrorCollectorHandler()
    logger.addHandler(error_collector)
    return error_collector


def stop_error_collection(logger_name: str, error_collector: ErrorCollectorHandler) -> list:
    """
    Stop collecting ERROR messages and return collected errors.

    Args:
        logger_name (str): Name of the logger being monitored
        error_collector (ErrorCollectorHandler): Handler instance to remove

    Returns:
        list: List of collected error messages
    """
    logger = logging.getLogger(logger_name)

    # Only try to remove if the handler was actually added
    if error_collector in logger.handlers:
        logger.removeHandler(error_collector)

    return error_collector.get_errors()


def capture_step_errors(logger_name: str):
    """
    Create an ErrorCapture context manager for a specific logger.

    Args:
        logger_name (str): Name of the logger to monitor

    Returns:
        ErrorCapture: Context manager for capturing errors
    """
    return ErrorCapture(logger_name)


def set_log_directory(log_dir_path: str) -> None:
    """
    Set a custom log directory path.
    This function should be called before any logging operations begin.

    Args:
        log_dir_path (str): Path to the custom log directory
    """
    with _logging_state.lock:
        _logging_state.custom_log_dir = Path(log_dir_path)
        # Reset current log dir to force recreation with new base
        _logging_state.current_log_dir = None


def get_log_directory() -> Path:
    """
    Get or create a new log directory for the current run.
    All modules will use the same log directory for a given run.
    This function is thread-safe.

    Returns:
        Path: Path to the current log directory
    """
    with _logging_state.lock:
        if _logging_state.current_log_dir is None:
            # Use custom log directory if set, otherwise use default
            if _logging_state.custom_log_dir is not None:
                base_log_dir = _logging_state.custom_log_dir
            else:
                base_log_dir = Path("logs")

            # Create base logs directory if it doesn't exist
            base_log_dir.mkdir(exist_ok=True)

            if _logging_state.custom_log_dir is None:
                # Create timestamped directory for this run
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                _logging_state.current_log_dir = base_log_dir / f"logs_{timestamp}"
            else:
                _logging_state.current_log_dir = base_log_dir
            _logging_state.current_log_dir.mkdir(exist_ok=True)

    return _logging_state.current_log_dir


def setup_logging(module_name: str, console_output: bool = False) -> logging.Logger:
    """
    Set up file-based logging for a specific module, optionally with console output.

    This function is thread-safe and creates file handlers for the specified module.
    If console_output is True, adds a StreamHandler for real-time console output.

    Args:
        module_name (str): Name of the module (e.g., 'factory_flow_orchestrator', 'compute_factory_flow')
        console_output (bool): If True, add console handler for LOG mode output

    Returns:
        logging.Logger: Configured logger instance
    """
    # Get the current log directory
    log_dir = get_log_directory()

    # Create a logger for the module
    logger = logging.getLogger(module_name)

    # Use lock to prevent race conditions when setting up handlers
    with _logging_state.lock:
        # Only set up handlers if they haven't been set up yet
        if not logger.handlers:
            logger.setLevel(logging.INFO)

            # Create formatter
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

            # Always add file handler for persistent logs
            log_file = log_dir / f"{module_name}.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

            # Add console handler if requested (for LOG mode)
            if console_output:
                # Create a console with no width limit for LOG mode
                log_console = Console(width=200, force_terminal=True)
                console_handler = RichHandler(
                    console=log_console,
                    rich_tracebacks=True,
                    markup=True,  # Enable markup for colors
                    show_time=True,  # Show timestamp (time only, no date)
                    show_level=True,  # Show level with colors
                    show_path=False,  # Don't show file paths
                    omit_repeated_times=False,  # Always show time
                    log_time_format="[%X]",  # Time only format (HH:MM:SS)
                )
                console_handler.setLevel(logging.INFO)
                # Use a simpler formatter for RichHandler (it adds its own formatting)
                console_handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))
                logger.addHandler(console_handler)

            # Automatically add error collection handler to all loggers
            auto_error_collector = AutoErrorCollectorHandler()
            logger.addHandler(auto_error_collector)

            # Prevent propagation to root logger to avoid duplicate output
            logger.propagate = False

    return logger


# ==============================================================================
# OUTPUT MODE MANAGER - GUI, log streaming, and JSON output
# ==============================================================================


class RealTimeElapsedColumn(ProgressColumn):
    """A custom column that shows real elapsed time independent of progress bar state."""

    def __init__(self):
        super().__init__()
        self.start_time = time.time()
        self.completed_tasks = {}
        self.error_handler_running = {}

    def render(self, task):
        """Render the elapsed time."""
        if (
            task.completed >= task.total
            and task.id not in self.completed_tasks
            and not self.error_handler_running.get(task.id, False)
        ):
            final_elapsed = time.time() - self.start_time
            self.completed_tasks[task.id] = final_elapsed

        if task.id in self.completed_tasks:
            elapsed = self.completed_tasks[task.id]
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            return Text(f"{hours:02d}:{minutes:02d}:{seconds:02d}", style="green")

        elapsed = time.time() - self.start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        return Text(f"{hours:02d}:{minutes:02d}:{seconds:02d}", style="cyan")

    def set_error_handler_running(self, task_id: int, running: bool):
        """Set whether an error handler is running for a task."""
        self.error_handler_running[task_id] = running


class JSONPrinter:
    """Pretty-print JSON summaries on stage completion."""

    def __init__(self, console: Console):
        self.console = console

    def print_stage_summary(self, stage_name: str, stage_data: Dict[str, Any]):
        """Print a pretty summary of a completed stage."""
        self.console.print("\n" + "=" * 80)
        self.console.print(f"[bold cyan]Stage Completed: {stage_name}[/bold cyan]")
        self.console.print("=" * 80)
        self.console.print(json.dumps(stage_data, indent=2))
        self.console.print("=" * 80 + "\n")

    def print_flow_summary(self, flow_name: str, flow_data: Dict[str, Any]):
        """Print a pretty summary of a completed flow."""
        self.console.print("\n" + "=" * 80)
        self.console.print(f"[bold green]Flow Completed: {flow_name}[/bold green]")
        self.console.print("=" * 80)
        self.console.print(json.dumps(flow_data, indent=2))
        self.console.print("=" * 80 + "\n")

    def print_flow_failure(self, flow_name: str, error_message: str, flow_data: Dict[str, Any]):
        """Print a pretty summary of a failed flow."""
        self.console.print("\n" + "=" * 80)
        self.console.print(f"[bold red]Flow Failed: {flow_name}[/bold red]")
        self.console.print(f"[red]Error: {error_message}[/red]")
        self.console.print("=" * 80)
        self.console.print(json.dumps(flow_data, indent=2))
        self.console.print("=" * 80 + "\n")


class OutputModeManager:
    """
    Centralized output management for factory flow orchestrator.

    Manages all output operations (console, GUI, JSON) through a single interface.
    Coordinates between file logging, Rich GUI displays, log streaming, and
    JSON pretty-printing based on the configured output mode.

    Attributes:
        mode: Current output mode (none, gui, log, json)
        console: Rich Console instance for output
        logger: Logger instance for this manager
        gui_components: GUI components (Live, Progress) if in GUI mode
        json_printer: JSON printing component if in JSON mode
    """

    def __init__(
        self,
        mode: OutputMode,
        log_directory: Path,
        json_file_path: Path,
        logger: logging.Logger,
    ):
        """
        Initialize the output mode manager.

        Args:
            mode: Output mode to use
            log_directory: Directory containing log files
            json_file_path: Path to JSON progress file
            logger: Logger instance for this manager
        """
        self.mode = mode
        self.log_directory = log_directory
        self.json_file_path = json_file_path
        self.logger = logger
        self.console = Console()

        self.gui_components = None
        self.json_printer = None

        self._lock = threading.RLock()
        self._flow_tables = {}

        self._initialize_mode()

    def _initialize_mode(self):
        """Initialize output components based on mode."""
        if self.mode == OutputMode.GUI:
            self._setup_gui_mode()
        elif self.mode == OutputMode.JSON:
            self._setup_json_printing()
        # LOG mode and NONE mode don't need special initialization
        # Rich Console handles output naturally in all modes

    def _setup_gui_mode(self):
        """Set up Rich GUI components."""
        elapsed_column = RealTimeElapsedColumn()
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            elapsed_column,
            console=self.console,
            refresh_per_second=1,
        )

        self.gui_components = {
            "progress": progress,
            "elapsed_column": elapsed_column,
            "live_display": None,
            "update_callback": None,
        }

    def _setup_json_printing(self):
        """Set up JSON pretty-printing."""
        self.json_printer = JSONPrinter(self.console)

    def set_gui_live_display(self, live_display: Live, update_callback: Optional[Callable] = None):
        """Set the Rich Live display for GUI mode (called by orchestrator)."""
        if self.mode == OutputMode.GUI and self.gui_components:
            self.gui_components["live_display"] = live_display
            self.gui_components["update_callback"] = update_callback

    def get_progress_component(self):
        """Get the Rich Progress component for GUI mode."""
        if self.mode == OutputMode.GUI and self.gui_components:
            return self.gui_components["progress"]
        return None

    def get_elapsed_column(self):
        """Get the elapsed time column for GUI mode."""
        if self.mode == OutputMode.GUI and self.gui_components:
            return self.gui_components["elapsed_column"]
        return None

    def on_step_completed(
        self, _flow_name: str, step_name: str, success: bool, duration: float, step_data: Dict[str, Any] = None
    ):
        """
        Called when a step completes execution.

        Args:
            _flow_name: Name of the flow (unused in current implementation)
            step_name: Name of the step that completed
            success: Whether the step succeeded
            duration: Duration of step execution in seconds
            step_data: Full step execution data dictionary
        """
        if self.mode == OutputMode.JSON:
            status = "[green]SUCCESS[/green]" if success else "[red]FAILED[/red]"
            self.console.print(f"{status} - {step_name} ({duration:.2f}s)")
            if step_data:
                self.console.print(json.dumps(step_data, indent=2))

    def on_flow_completed(self, flow_name: str, flow_data: Dict[str, Any]):
        """
        Called when a flow completes successfully.

        Args:
            flow_name: Name of the flow that completed
            flow_data: Flow summary data
        """
        if self.mode == OutputMode.JSON and self.json_printer:
            self.json_printer.print_flow_summary(flow_name, flow_data)

    def on_flow_failed(self, flow_name: str, error_message: str, flow_data: Dict[str, Any]):
        """
        Called when a flow fails.

        Args:
            flow_name: Name of the flow that failed
            error_message: Error message describing the failure
            flow_data: Flow summary data
        """
        if self.mode == OutputMode.JSON and self.json_printer:
            self.json_printer.print_flow_failure(flow_name, error_message, flow_data)

    def build_progress_table_from_tracker(self, flow_status_dict: Dict[str, Dict[str, str]]) -> Table:
        """
        Build a progress table from flow status dictionary.

        Args:
            flow_status_dict: Dictionary of flow statuses

        Returns:
            Rich Table with flow progress information
        """
        table = Table(title="Independent Flows Progress")
        table.add_column("Flow Name", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Current Step", style="yellow")
        table.add_column("Progress", style="blue")

        for name, status_info in flow_status_dict.items():
            table.add_row(
                name,
                status_info["status"],
                status_info["current_step"],
                status_info["progress"],
            )

        return table

    def update_live_display(self, flow_status_dict: Dict[str, Dict[str, str]]):
        """
        Update the live GUI display with current progress.

        Args:
            flow_status_dict: Dictionary of flow statuses
        """
        if self.mode != OutputMode.GUI or not self.gui_components:
            return

        live_display = self.gui_components.get("live_display")
        progress = self.gui_components.get("progress")

        if live_display and progress:
            new_table = self.build_progress_table_from_tracker(flow_status_dict)
            new_group = Group(
                Panel(new_table, title="Independent Flows Progress", border_style="blue"),
                "\n",
                Panel(progress, title="Progress", border_style="green"),
            )
            live_display.update(new_group)

    def display_initial_table(self, flow_status_dict: Dict[str, Dict[str, str]]):
        """
        Display initial progress table (non-GUI modes).

        Args:
            flow_status_dict: Dictionary of flow statuses
        """
        if self.mode == OutputMode.NONE:
            return

        if self.mode != OutputMode.GUI:
            table = self.build_progress_table_from_tracker(flow_status_dict)
            self.console.print(table)

    def cleanup(self):
        """Clean up resources when shutting down."""
        # No cleanup needed - console logging is handled by Python's logging module

    def is_gui_mode(self) -> bool:
        """Check if currently in GUI mode."""
        return self.mode == OutputMode.GUI
