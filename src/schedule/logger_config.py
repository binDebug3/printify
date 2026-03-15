"""
Logger configuration module for the Printify automation tool.

This module sets up a logger that records all actions to both the terminal and
the shared actions.log file. It provides a standardized logging interface for
tracking application events throughout the automation workflow.

The logger is configured with:
- INFO level logging
- UTF-8 encoded file output
- Real-time terminal output
- Formatted timestamps, log levels, function names, and messages

Functions:
    log_action: Log a standardized action message.
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_PATH = PROJECT_ROOT / "meta" / "actions.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s: %(funcName)-20s - %(message)s"
    )

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


def log_action(action: str) -> None:
    """
    Write a standardized action message to configured log handlers.

    This function logs the provided action message at the INFO level, including
    a timestamp and the name of the calling function for context. It is intended to
    be used throughout the application to record significant events and actions in a
    consistent format.

    Args:
        action (str): A descriptive message of the action being logged.

    Returns:
        None
    """
    logger.info(action, stacklevel=2)
