"""
Logger configuration module for the Printify automation tool.

This module sets up a file-based logger that records all actions to an 'actions.log' file.
It provides a standardized logging interface for tracking application events throughout
the automation workflow.

The logger is configured with:
- INFO level logging
- UTF-8 encoded file output
- Formatted timestamps, log levels, function names, and messages

Functions:
    _log_action: Log a standardized action message to the actions log file.
"""

from pathlib import Path
import logging


LOG_PATH = Path(__file__).resolve().parent.parent.parent / "meta" / "actions.log"
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s: %(funcName)-20s - %(message)s")
    )
    logger.addHandler(file_handler)


def log_action(action: str) -> None:
    """
    Write a standardized action message to actions.log.
    
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
