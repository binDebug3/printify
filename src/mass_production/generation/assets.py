"""
Functions for generating and saving design and mockup assets for an idea.
"""

import json
from pathlib import Path
from typing import Optional, Any

from config import constants
from photoshop.remove_bg import RemoveBgClient
from photoshop.design_crop import (
    crop_design_image_to_content, 
    crop_center_percent,
    create_default_color_mockup,
)
from clients.gemini_client import GeminiClient
from file_tools.io_utils import (
    write_bytes, 
    write_text,
    slugify_title,
)
from generation.idea_processing import write_persona_files
from product.models import Idea
from file_tools.parsing import parse_json_object_payload
from schedule.logger_config import log_action


def generate_design_image(
    idea: Idea,
    prompts: dict[str, str],
    gemini: GeminiClient,
    dashboard: Optional[Any] = None,
) -> tuple[Path, bytes]:
    """Generate and save the primary design image for an idea.

    Args:
        idea: Idea model.
        prompts: Prompt templates.
        gemini: Gemini client.

    Returns:
        Tuple containing the design path and image bytes.
    """
    idea_json: str = json.dumps(idea.payload, indent=2)
    design_prompt: str = f"{prompts['image']}\n\nIdea JSON:\n{idea_json}"
    log_action(f"Generating design image for '{idea.title}'")
    generated_design_bytes: bytes = gemini.generate_image(design_prompt)
    design_bytes: bytes = crop_design_image_to_content(
        image_bytes=generated_design_bytes,
        padding_percent=constants.DESIGN_CROP_PADDING_PERCENT,
    )
    design_path: Path = idea.folder_path / "design.png"
    write_bytes(design_path, design_bytes)
    safe_dashboard_call(dashboard, "update_image", "raw_design", design_path)
    return design_path, design_bytes


def _generate_post_design_assets(
    idea: Idea,
    prompts: dict[str, str],
    gemini: GeminiClient,
    remove_bg_client: RemoveBgClient,
    design_path: Path,
    design_bytes: bytes,
    dashboard: Optional[Any] = None,
) -> tuple[Path, Path, Path]:
    """Create transparent design, mockup, and cropped mockup assets.

    Args:
        idea: Idea model.
        prompts: Prompt templates.
        gemini: Gemini client.
        remove_bg_client: remove.bg client.
        design_path: Path to the generated design image.
        design_bytes: Generated design bytes.

    Returns:
        Tuple of paths: transparent, mockup, mockup_cropped.
    """
    idea_json: str = json.dumps(idea.payload, indent=2)
    mockup_color: str = str(idea.payload.get("mockup_color", "")).strip()
    if not mockup_color:
        raise ValueError(
            f"Missing required idea payload field 'mockup_color' for '{idea.title}'"
        )

    # remove background
    log_action(f"Removing background from design for '{idea.title}'")
    transparent_bytes: bytes = remove_bg_client.remove_background(design_bytes)
    transparent_path: Path = idea.folder_path / "design_transparent.png"
    write_bytes(transparent_path, transparent_bytes)
    safe_dashboard_call(
        dashboard,
        "update_image",
        "transparent_design",
        transparent_path,
    )

    background_prompt: str = f"Design JSON:\n{idea_json}\n\n{prompts['background']}"
    log_action(f"Generating background text for '{idea.title}'")
    background_response_text: str = gemini.generate_text(background_prompt).strip()
    background_payload: dict[str, Any] = parse_json_object_payload(
        background_response_text
    )
    write_persona_files(idea.folder_path, background_payload)
    mockup_scene: str = str(
        background_payload.get("mockup_scene", background_response_text)
    ).strip()
    write_text(idea.folder_path / "background.txt", mockup_scene)

    # mock up
    default_mockup_path: Path = create_default_color_mockup(
        design_path=transparent_path,
        color=mockup_color,
        output_dir=idea.folder_path,
    )
    safe_dashboard_call(
        dashboard, "update_image", "default_mockup", default_mockup_path
    )
    default_mockup_bytes: bytes = default_mockup_path.read_bytes()

    shirt_color_mockup: str = mockup_color
    mockup_prompt: str = (
        f"Make the t shirt color {shirt_color_mockup}\n"
        f"Model description and background scene: {mockup_scene}\n"
        f"{prompts['mockup']}\n\n"
    )
    log_action(f"Generating mockup image for '{idea.title}'")
    mockup_bytes: bytes = gemini.generate_image(
        mockup_prompt,
        image_bytes=default_mockup_bytes,
    )
    slugified_color: str = slugify_title(shirt_color_mockup)
    mockup_path: Path = idea.folder_path / f"mockup_({slugified_color}).png"
    write_bytes(mockup_path, mockup_bytes)
    safe_dashboard_call(dashboard, "update_image", "generated_mockup", mockup_path)

    # cropped mockup
    log_action(f"Cropping mockup image for '{idea.title}'")
    mockup_cropped_path: Path = (
        idea.folder_path / f"mockup_({slugified_color})_cropped.png"
    )
    crop_center_percent(mockup_path, mockup_cropped_path, constants.CROP_CENTER_PERCENT)
    safe_dashboard_call(
        dashboard, "update_image", "cropped_mockup", mockup_cropped_path
    )

    return transparent_path, mockup_path, mockup_cropped_path


def safe_dashboard_call(
    dashboard: Optional[Any],
    method_name: str,
    *args,
    **kwargs,
) -> Optional[Any]:
    """Safely call a method on the dashboard, if it exists.

    Args:
        dashboard: The dashboard instance or None.
        method_name: The name of the method to call.
        *args: Positional arguments for the method.
        **kwargs: Keyword arguments for the method.
    Returns:
        The result of the dashboard method call, or None if the dashboard or method does not exist
    """
    if dashboard is not None:
        method = getattr(dashboard, method_name, None)
        if callable(method):
            try:
                return method(*args, **kwargs)
            except Exception as e:
                log_action(f"Error calling dashboard method '{method_name}': {e}")
        else:
            log_action(f"Dashboard method '{method_name}' not found or not callable.")
    return None
