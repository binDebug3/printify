"""
Parsing utilities for extracting structured data from raw model output text, 
such as JSON objects or arrays.
"""

import json
import re
from typing import Any

from schedule.logger_config import log_action


def parse_json_object_payload(response_text: str) -> dict[str, Any]:
    """Parse a JSON object payload from model output text.

    Args:
        response_text: Raw Gemini output text.

    Returns:
        Parsed dictionary payload, or an empty dict when parsing fails.
    """
    stripped: str = response_text.strip()
    try:
        parsed_direct: Any = json.loads(stripped)
        if isinstance(parsed_direct, dict):
            return parsed_direct
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        return {}
    try:
        parsed_block: Any = json.loads(match.group(0))
        if isinstance(parsed_block, dict):
            return parsed_block
    except json.JSONDecodeError:
        return {}
    return {}


def parse_json_array(text: str) -> list[dict]:
    """Parse a JSON array from model text output.

    Args:
        text: Raw model response.

    Returns:
        Parsed list of dictionaries.

    Raises:
        ValueError: If no valid JSON array is found.
    """
    log_action("Parsing JSON array from model output")
    stripped: str = text.strip()
    try:
        parsed: str = json.loads(stripped)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", stripped, re.DOTALL)
    if not match:
        raise ValueError("No JSON array found in response")

    parsed: str = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise ValueError("Parsed JSON is not a list")
    return [item for item in parsed if isinstance(item, dict)]
