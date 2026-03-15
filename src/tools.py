"""Shared helpers for Printify API modules.

This module keeps authentication, shop-id loading, and shared constants used by
the specialized modules under src/printify_api_tools.
"""

from typing import Optional

from logger_config import log_action


def load_api_token(filepath: Optional[str] = None) -> str:
    """
    Load an API token from a file.

    This function reads the contents of a file and returns the API token
    as a string with leading and trailing whitespace removed.

    Args:
        filepath (str): The path to the file containing the API token.
    Returns:
        str: The API token read from the file, with whitespace stripped.
    Raises:
        FileNotFoundError: If the file at the specified filepath does not exist.
        IOError: If there is an error reading the file.
    """
    if filepath is None:
        filepath = "../meta/api_token.txt"
    log_action(f"reading token from '{filepath}'")

    with open(filepath, "r", encoding="utf-8") as file_handle:
        token = file_handle.read().strip()

    log_action("token loaded successfully")
    return token


def load_shop_id() -> str:
    """
    Load the Printify shop ID from a file.

    This function reads the contents of 'shop_id.txt' and returns the shop ID
    as a string with leading and trailing whitespace removed.

    Returns:
        str: The Printify shop ID read from 'shop_id.txt', with whitespace stripped.
    """
    file_path: str = "../meta/shop_id.txt"
    log_action(f"reading shop id from '{file_path}'")
    with open(file_path, "r", encoding="utf-8") as file_handle:
        shop_id = file_handle.read().strip()

    log_action("shop id loaded successfully")
    return shop_id
