"""Shared pytest configuration for the Printify automation test suite.

This module adds the `src` directory to sys.path and pre-configures the logger
so that no tests write to the actions.log file on disk.
"""

import sys
import logging
from pathlib import Path


# Make all project modules importable without installation.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SRC_ROOT))

# Pre-register a NullHandler on the logger_config logger before any module
# imports logger_config.py.  The `if not logger.handlers:` guard inside
# logger_config means the FileHandler is never created during test runs, so
# tests never touch meta/actions.log.
logging.getLogger("logger_config").addHandler(logging.NullHandler())
logging.getLogger("src.logger_config").addHandler(logging.NullHandler())
