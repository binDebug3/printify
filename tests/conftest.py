"""Shared pytest configuration for the Printify automation test suite.

This module adds the printify package directory to sys.path and pre-configures
the logger so that no tests write to the actions.log file on disk.
"""

import sys
import logging
from pathlib import Path


# Make all project modules importable without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pre-register a NullHandler on the logger_config logger before any module
# imports logger_config.py.  The `if not logger.handlers:` guard inside
# logger_config means the FileHandler is never created during test runs, so
# tests never touch meta/actions.log.
logging.getLogger("logger_config").addHandler(logging.NullHandler())
