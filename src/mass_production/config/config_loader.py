"""Config loader for mass production pipeline."""

import os
from pathlib import Path
from typing import Dict, List

from config import constants
from file_tools.io_utils import (
    read_json,
    read_text,
    slugify_title,
)
from schedule.logger_config import log_action


def append_response_format(
    prompt_text: str,
    response_format_text: str,
    *,
    expect_list_of_objects: bool = False,
) -> str:
    """Append authoritative response-shape instructions to a prompt.

    Args:
        prompt_text: Base prompt content.
        response_format_text: JSON example loaded from the response schema file.
        expect_list_of_objects: Whether the schema represents one object shape
            while the model must return a list of those objects.

    Returns:
        Prompt text with response-shape instructions appended.
    """
    if expect_list_of_objects:
        expectation_text: str = (
            "Return only valid JSON as an array of objects. "
            "Each object in the array must match this exact shape:\n"
        )
    else:
        expectation_text = (
            "Return only valid JSON as a single object matching this exact shape:\n"
        )
    return (
        f"{prompt_text.strip()}\n\n"
        "## Required Response Format\n"
        f"{expectation_text}{response_format_text.strip()}"
    )


def require_env(var_name: str) -> str:
    """Read a required environment variable.

    Args:
        var_name: Name of the environment variable.

    Returns:
        Variable value.

    Raises:
        EnvironmentError: If variable is missing.
    """
    value: str = os.getenv(var_name, "").strip()
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {var_name}")
    return value


def require_setting(var_name: str, fallback_path: Path) -> str:
    """Read a required setting from env first, then from a file.

    Args:
        var_name: Environment variable name.
        fallback_path: File path used when the env var is unset.

    Returns:
        Resolved non-empty setting value.

    Raises:
        EnvironmentError: If neither env nor file contains a value.
    """
    value: str = os.getenv(var_name, "").strip()
    if value:
        return value
    if fallback_path.exists():
        file_value: str = read_text(fallback_path).strip()
        if file_value:
            return file_value
    raise EnvironmentError(
        f"Missing required setting: {var_name} or file '{fallback_path}'"
    )


def load_prompts() -> Dict[str, str]:
    """Load all prompt templates from data/prompts.

    Returns:
        Mapping of prompt names to their text content.
    """
    log_action("Loading prompt templates from disk")
    design_prompt: str = append_response_format(
        read_text(constants.DESIGN_PROMPT_PATH),
        read_text(constants.DESIGN_RESPONSE_PATH),
        expect_list_of_objects=True,
    )
    background_prompt: str = append_response_format(
        read_text(constants.BACKGROUND_PROMPT_PATH),
        read_text(constants.BACKGROUND_RESPONSE_PATH),
    )
    filter_design_descriptions_prompt: str = append_response_format(
        read_text(constants.FILTER_DESIGN_DESCRIPTIONS_PATH),
        read_text(constants.FILTER_DESIGN_DESCRIPTIONS_RESPONSE_PATH),
    )
    return {
        "design": design_prompt,
        "image": read_text(constants.IMAGE_PROMPT_PATH),
        "background": background_prompt,
        "mockup": read_text(constants.MOCKUP_PROMPT_PATH),
        "title": read_text(constants.TITLE_PROMPT_PATH),
        "description": read_text(constants.DESCRIPTION_PROMPT_PATH),
        "keywords": read_text(constants.KEYWORDS_PROMPT_PATH),
        "default_description": read_text(constants.DEFAULT_DESCRIPTION_PATH),
        "filter_design_descriptions": filter_design_descriptions_prompt,
        "background_response": read_text(constants.BACKGROUND_RESPONSE_PATH),
        "design_response": read_text(constants.DESIGN_RESPONSE_PATH),
        "filter_design_descriptions_response": read_text(
            constants.FILTER_DESIGN_DESCRIPTIONS_RESPONSE_PATH
        ),
        "filter_design_images_response": read_text(
            constants.FILTER_DESIGN_IMAGES_RESPONSE_PATH
        ),
    }


def load_color_to_ids_map(path: Path) -> Dict[str, List[int]]:
    """Load the color to variant IDs mapping from variant_map.json.

    Args:
        path: Path to the variant map file.

    Returns:
        Mapping from color names to ordered variant IDs.
    """
    payload: Dict = read_json(path)
    variants: List[str] = (
        payload.get("variants", []) if isinstance(payload, dict) else []
    )
    color_to_ids: dict[str, list[int]] = {}
    for entry in variants:
        if not isinstance(entry, dict):
            continue
        color: str = str(entry.get("color", "")).strip()
        ids: List[str] = entry.get("ids", [])
        if not color or not isinstance(ids, list):
            continue
        color_to_ids[color] = [value for value in ids if isinstance(value, int)]
    return color_to_ids


def keyword_products_dir(keyword: str) -> Path:
    """Get the output directory for one keyword's products.

    Args:
        keyword: Source keyword value.

    Returns:
        Per-keyword products directory path.
    """
    return constants.PRODUCTS_DIR / slugify_title(keyword)
