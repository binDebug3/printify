"""Parsing utilities for extracting structured data from raw model output text."""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from schedule.logger_config import log_action


TRAILING_COMMA_PATTERN = re.compile(r",(\s*[}\]])")
UNQUOTED_KEY_PATTERN = re.compile(r"([\{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)")
SMART_QUOTES_TRANSLATION = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


@dataclass
class StructuredOutputParseError(ValueError):
    """Raised when model output cannot be parsed into the expected JSON shape."""

    message: str
    original_text: str
    candidate_text: str
    repaired_text: Optional[str] = None

    def __str__(self) -> str:
        """Return the human-readable parse failure message."""
        return self.message


def strip_code_fences(text: str) -> str:
    """Remove a surrounding markdown code fence from model output.

    Args:
        text: Raw model output.

    Returns:
        Text with a surrounding markdown code fence removed when present.
    """
    log_action("Removing markdown code fences from model output when present")
    stripped: str = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines: List[str] = stripped.splitlines()
    if len(lines) < 2:
        return stripped.replace("```", "").strip()
    if lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()


def extract_first_json_block(text: str, opening_char: str) -> Optional[str]:
    """Extract the first balanced JSON object or array from free-form text.

    Args:
        text: Raw model output.
        opening_char: Either "{" or "[".

    Returns:
        The first balanced JSON block, or None when no block is found.
    """
    log_action(f"Extracting first JSON block starting with '{opening_char}'")
    closing_char: str = "}" if opening_char == "{" else "]"
    start_index: int = text.find(opening_char)
    if start_index < 0:
        return None

    depth: int = 0
    in_string: bool = False
    is_escaped: bool = False
    for index in range(start_index, len(text)):
        current_char: str = text[index]
        if is_escaped:
            is_escaped = False
            continue
        if current_char == "\\":
            is_escaped = True
            continue
        if current_char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if current_char == opening_char:
            depth += 1
        elif current_char == closing_char:
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]
    return None


def repair_json_text(text: str) -> str:
    """Apply narrow, deterministic repairs to almost-valid JSON text.

    Args:
        text: Candidate JSON text.

    Returns:
        Repaired JSON candidate.
    """
    log_action("Attempting deterministic JSON repairs")
    repaired: str = text.translate(SMART_QUOTES_TRANSLATION)
    repaired = TRAILING_COMMA_PATTERN.sub(r"\1", repaired)
    repaired = UNQUOTED_KEY_PATTERN.sub(r'\1"\2"\3', repaired)
    return repaired


def _build_candidate_text(response_text: str, opening_char: str) -> str:
    """Build the best JSON candidate from a model response.

    Args:
        response_text: Raw model output.
        opening_char: Expected leading JSON delimiter.

    Returns:
        Candidate JSON text.
    """
    log_action("Building JSON candidate text from model output")
    stripped: str = strip_code_fences(response_text)
    extracted_block: Optional[str] = extract_first_json_block(stripped, opening_char)
    return extracted_block if extracted_block is not None else stripped


def _parse_candidate_json(candidate_text: str) -> Any:
    """Parse one candidate JSON string.

    Args:
        candidate_text: Candidate JSON text.

    Returns:
        Parsed JSON value.
    """
    log_action("Parsing candidate JSON text")
    return json.loads(candidate_text)


def parse_json_object_payload_strict(response_text: str) -> Dict[str, Any]:
    """Parse a required JSON object payload from model output text.

    Args:
        response_text: Raw Gemini output text.

    Returns:
        Parsed dictionary payload.

    Raises:
        StructuredOutputParseError: If no valid JSON object can be recovered.
    """
    log_action("Parsing JSON object payload from model output")
    candidate_text: str = _build_candidate_text(response_text, "{")
    repaired_text: Optional[str] = None
    last_error: Optional[Exception] = None
    for json_text in [candidate_text, repair_json_text(candidate_text)]:
        if repaired_text is not None and json_text == repaired_text:
            continue
        repaired_text = json_text
        try:
            parsed_value: Any = _parse_candidate_json(json_text)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed_value, dict):
            return parsed_value
        last_error = ValueError("Parsed JSON is not an object")

    error_message: str = "Invalid JSON object response"
    if last_error is not None:
        error_message = f"{error_message}: {last_error}"
    raise StructuredOutputParseError(
        message=error_message,
        original_text=response_text,
        candidate_text=candidate_text,
        repaired_text=repaired_text,
    )


def parse_json_object_payload(response_text: str) -> Dict[str, Any]:
    """Parse a JSON object payload from model output text.

    Args:
        response_text: Raw Gemini output text.

    Returns:
        Parsed dictionary payload, or an empty dict when parsing fails.
    """
    log_action("Parsing optional JSON object payload from model output")
    try:
        return parse_json_object_payload_strict(response_text)
    except StructuredOutputParseError:
        return {}


def parse_json_array(text: str) -> List[Dict[str, Any]]:
    """Parse a required JSON array from model text output.

    Args:
        text: Raw model response.

    Returns:
        Parsed list of dictionaries.

    Raises:
        StructuredOutputParseError: If no valid JSON array is found.
    """
    log_action("Parsing JSON array from model output")
    candidate_text: str = _build_candidate_text(text, "[")
    repaired_text: Optional[str] = None
    last_error: Optional[Exception] = None
    for json_text in [candidate_text, repair_json_text(candidate_text)]:
        if repaired_text is not None and json_text == repaired_text:
            continue
        repaired_text = json_text
        try:
            parsed_value: Any = _parse_candidate_json(json_text)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed_value, list):
            return [item for item in parsed_value if isinstance(item, dict)]
        last_error = ValueError("Parsed JSON is not a list")

    error_message: str = "Invalid JSON array response"
    if last_error is not None:
        error_message = f"{error_message}: {last_error}"
    raise StructuredOutputParseError(
        message=error_message,
        original_text=text,
        candidate_text=candidate_text,
        repaired_text=repaired_text,
    )
