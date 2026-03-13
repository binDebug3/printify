"""End-to-end mass production pipeline orchestration."""

import json
import os
# import random
from pathlib import Path
from typing import Any, List, Dict

from logger_config import log_action

import constants
from gemini_client import GeminiClient
from io_utils import (
    crop_center_percent,
    mark_idea_as_published,
    normalize_keywords_csv_to_json_array,
    parse_json_array,
    read_json,
    read_keywords_from_ideas_csv,
    read_text,
    slugify_title,
    unique_versioned_title,
    write_bytes,
    write_json,
    write_text,
)
from models import Idea
from printify_client import PrintifyClient
from remove_bg import RemoveBgClient


def _require_env(var_name: str) -> str:
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


def _require_setting(var_name: str, fallback_path: Path) -> str:
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


def _load_prompts() -> Dict[str, str]:
    """Load all prompt templates from data/prompts.

    Returns:
        Mapping of prompt names to their text content.
    """
    log_action("Loading prompt templates from disk")
    return {
        "design": read_text(constants.DESIGN_PROMPT_PATH),
        "image": read_text(constants.IMAGE_PROMPT_PATH),
        "background": read_text(constants.BACKGROUND_PROMPT_PATH),
        "mockup": read_text(constants.MOCKUP_PROMPT_PATH),
        "title": read_text(constants.TITLE_PROMPT_PATH),
        "description": read_text(constants.DESCRIPTION_PROMPT_PATH),
        "keywords": read_text(constants.KEYWORDS_PROMPT_PATH),
        "default_description": read_text(constants.DEFAULT_DESCRIPTION_PATH),
    }


def _load_color_to_ids_map(path: Path) -> Dict[str, List[int]]:
    """Load the color to variant IDs mapping from variant_map.json.

    Args:
        path: Path to the variant map file.

    Returns:
        Mapping from color names to ordered variant IDs.
    """
    payload: Dict = read_json(path)
    variants: List[str] = payload.get("variants", []) if isinstance(payload, dict) else []
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


def _normalize_idea_payload(raw: dict[str, Any], keyword: str) -> dict[str, Any]:
    """Normalize and validate an idea payload from Gemini.

    Args:
        raw: Raw idea dictionary.
        keyword: Source keyword for fallback values.

    Returns:
        Normalized idea payload dictionary.
    """
    title: str = str(raw.get("title", "")).strip() or f"{keyword} shirt"
    return {
        "title": title,
        "graphic_style": str(raw.get("graphic_style", "")).strip(),
        "typography": str(raw.get("typography", "")).strip(),
        "composition": str(raw.get("composition", "")).strip(),
        "background": str(raw.get("background", "")).strip(),
        "design_colors": [str(c).strip() for c in raw.get("design_colors", []) if str(c).strip()],
        "shirt_colors": [str(c).strip() for c in raw.get("shirt_colors", []) if str(c).strip()],
    }


def _build_idea_object(raw_idea: dict[str, Any], keyword: str) -> Idea:
    """Create Idea object with versioned title and output folder.

    Args:
        raw_idea: Model-generated idea payload.
        keyword: Keyword used to generate this idea.

    Returns:
        Idea model with derived storage fields.
    """
    normalized: Dict[str, Any] = _normalize_idea_payload(raw_idea, keyword)
    original_title: str = normalized["title"]
    title: str = unique_versioned_title(original_title, constants.IMAGES_DIR)
    folder_name: str = slugify_title(title)
    folder_path: Path = constants.IMAGES_DIR / folder_name
    normalized["title"] = title
    return Idea(
        keyword=keyword,
        original_title=original_title,
        title=title,
        folder_name=folder_name,
        folder_path=folder_path,
        payload=normalized,
    )


def _generate_ideas_for_keyword(
    gemini: GeminiClient,
    design_prompt: str,
    keyword: str,
    ideas_per_keyword: int,
) -> List[Dict[str, Any]]:
    """Generate normalized idea payloads for a keyword.

    Args:
        gemini: Gemini text/image client.
        design_prompt: Base design prompt template.
        keyword: Source keyword.
        ideas_per_keyword: Number of ideas to generate.

    Returns:
        List of raw idea dictionaries.
    """
    
    prompt: str = (
        f"{design_prompt}\n\n"
        f"Keyword: {keyword}\n"
        f"Generate exactly {ideas_per_keyword} ideas."
    )
    response_text: str = gemini.generate_text(prompt)
    ideas: List[Dict] = parse_json_array(response_text)
    log_action(f"Generated {len(ideas)} ideas for keyword '{keyword}'")
    return ideas[:ideas_per_keyword]


def _save_idea_json(idea: Idea) -> None:
    """Save per-idea JSON output.

    Args:
        idea: Idea payload object.
    """
    write_json(idea.folder_path / "ideas.json", [idea.payload])
    log_action(f"Saved idea JSON for '{idea.title}' to '{idea.folder_path / 'ideas.json'}'")


def _generate_design_assets(
    idea: Idea,
    prompts: dict[str, str],
    gemini: GeminiClient,
    remove_bg_client: RemoveBgClient,
) -> tuple[Path, Path, Path, Path]:
    """Create design, transparent design, mockup, and cropped mockup assets.

    Args:
        idea: Idea model.
        prompts: Prompt templates.
        gemini: Gemini client.
        remove_bg_client: remove.bg client.

    Returns:
        Tuple of paths: design, transparent, mockup, mockup_cropped.
    """
    idea_json: str = json.dumps(idea.payload, indent=2)

    # design image
    design_prompt: str = f"{prompts['image']}\n\nIdea JSON:\n{idea_json}"
    log_action(f"Generating design image for '{idea.title}'")
    design_bytes = gemini.generate_image(design_prompt)
    design_path = idea.folder_path / "design.png"
    write_bytes(design_path, design_bytes)
    
    # remove background
    log_action(f"Removing background from design for '{idea.title}'")
    transparent_bytes: bytes = remove_bg_client.remove_background(design_bytes)
    transparent_path: Path = idea.folder_path / "design_transparent.png"
    write_bytes(transparent_path, transparent_bytes)

    # mockup background
    background_prompt: str = (
        f"{prompts['background']}\n\n"
        f"Design JSON:\n{idea_json}"
    )
    log_action(f"Generating background text for '{idea.title}'")
    background_text: str = gemini.generate_text(background_prompt).strip()
    write_text(idea.folder_path / "background.txt", background_text)

    # mock up
    shirt_color_mockup: str = idea.payload.get("shirt_colors", [constants.DEFAULT_SHIRT_COLOR])[0]
    model_gender: str = "male"
    mockup_prompt: str = (
        f"Make the t shirt color {shirt_color_mockup}"
        f"Use a {model_gender} model.\n"
        f"Background scene: {background_text}\n"
        f"{prompts['mockup']}\n\n"
    )
    log_action(f"Generating mockup image for '{idea.title}'")
    mockup_bytes: bytes = gemini.generate_image(mockup_prompt, image_bytes=transparent_bytes)
    slugified_color: str = slugify_title(shirt_color_mockup)
    mockup_path: Path = idea.folder_path / f"mockup_({slugified_color}).png"
    write_bytes(mockup_path, mockup_bytes)

    # cropped mockup
    log_action(f"Cropping mockup image for '{idea.title}'")
    mockup_cropped_path: Path = idea.folder_path / f"mockup_({slugified_color})_cropped.png"
    crop_center_percent(mockup_path, mockup_cropped_path, constants.CROP_CENTER_PERCENT)

    return design_path, transparent_path, mockup_path, mockup_cropped_path


def _generate_listing_fields(
    idea: Idea,
    prompts: dict[str, str],
    gemini: GeminiClient,
) -> tuple[str, str, list[str]]:
    """Generate listing title, description, and keyword tags.

    Args:
        idea: Idea model.
        prompts: Prompt templates.
        gemini: Gemini client.

    Returns:
        Tuple containing title, description, and keyword tags.
    """
    idea_json: str = json.dumps(idea.payload, indent=2)

    # title
    log_action(f"Generating title for '{idea.title}'")
    title_prompt: str = f"{prompts['title']}\n\nDesign JSON:\n{idea_json}"
    generated_title: str = gemini.generate_text(title_prompt).strip()

    # description and personas
    log_action(f"Generating description for '{idea.title}'")
    description_prompt: str = f"{prompts['description']}\n\nDesign JSON:\n{idea_json}"
    generated_description_raw: str = gemini.generate_text(description_prompt).strip()

    personas_text: str = ""
    generated_description: str = generated_description_raw
    if "$$$" in generated_description_raw:
        personas_text, generated_description = [
            part.strip() for part in generated_description_raw.split("$$$", maxsplit=1)
        ]

    full_description: str = f"{generated_description}\n\n{prompts['default_description']}"

    # keywords
    log_action(f"Generating keywords for '{idea.title}'")
    keywords_prompt: str = f"{prompts['keywords']}\n\nDesign JSON:\n{idea_json}"
    keywords_csv: str = gemini.generate_text(keywords_prompt).strip()
    keywords: List[str] = normalize_keywords_csv_to_json_array(
        keywords_csv=keywords_csv,
        max_len=constants.KEYWORD_MAX_LENGTH,
    )[: constants.KEYWORDS_COUNT]

    write_text(idea.folder_path / "title.txt", generated_title)
    write_text(idea.folder_path / "personas.txt", personas_text)
    write_text(idea.folder_path / "description.txt", full_description)
    write_text(idea.folder_path / "keywords.txt", json.dumps(keywords, indent=2))

    return generated_title, full_description, keywords


def _select_colors(idea: Idea, color_to_ids: Dict[str, List[int]]) -> List[str]:
    """Select colors from idea payload, falling back to all mapped colors.

    Args:
        idea: Idea payload object.
        color_to_ids: Available color map.

    Returns:
        List of color names to use for product variants.
    """
    log_action(f"Selecting colors for '{idea.title}' from idea payload and variant map")
    colors: List[str] = [c for c in idea.payload.get("shirt_colors", []) if c in color_to_ids]
    if colors:
        return colors
    return list(color_to_ids.keys())


def run_pipeline(
    dry_run: bool,
    keyword_limit: int,
    ideas_per_keyword: int,
) -> None:
    """Run the full generation pipeline for ideas, assets, listings, and payloads.

    Args:
        dry_run: If true, skip real Printify product creation.
        keyword_limit: Maximum keywords to process this run.
        ideas_per_keyword: Number of ideas to generate per keyword.
    """
    prompts: Dict[str, str] = _load_prompts()
    keywords: List[str] = read_keywords_from_ideas_csv(constants.IDEAS_CSV_PATH, 
                                                       limit=keyword_limit)
    color_to_ids: Dict[str, List[int]] = _load_color_to_ids_map(constants.VARIANT_MAP_PATH)

    if not keywords:
        message: str = "No ideas marked used=false found in ideas.csv"
        log_action(message)
        print(message)
        return

    gemini_key: str = _require_setting("GEMINI_API_KEY", constants.GEMINI_API_KEY_PATH)
    removebg_key: str = _require_setting("REMOVEBG_API_KEY", constants.REMOVEBG_API_KEY_PATH)
    printify_token: str = _require_setting("PRINTIFY_API_TOKEN", constants.PRINTIFY_API_TOKEN_PATH)
    printify_shop_id: str = _require_setting("PRINTIFY_SHOP_ID", constants.PRINTIFY_SHOP_ID_PATH)

    gemini: GeminiClient = GeminiClient(
        api_key=gemini_key,
        text_model=constants.TEXT_MODEL,
        image_model=constants.IMAGE_MODEL,
        retries=constants.MAX_GEMINI_RETRIES,
    )
    remove_bg_client: RemoveBgClient = RemoveBgClient(
        api_key=removebg_key,
        endpoint=constants.REMOVE_BG_URL,
        retries=constants.MAX_REMOVEBG_RETRIES,
    )
    printify_client: PrintifyClient = PrintifyClient(
        token=printify_token,
        shop_id=printify_shop_id,
        blueprint_id=constants.BLUEPRINT_ID,
        print_provider_id=constants.PRINT_PROVIDER_ID,
        size_order=constants.SIZE_ORDER,
        size_surcharge_usd=constants.SIZE_SURCHARGE_USD,
        print_x=constants.PRINT_POSITION_X,
        print_y=constants.PRINT_POSITION_Y,
        print_scale=constants.PRINT_SCALE,
        min_price_usd=constants.MIN_PRICE_USD,
        dry_run=dry_run,
        retries=constants.MAX_PRINTIFY_RETRIES,
    )

    for keyword in keywords:
        log_action(f"Processing keyword: {keyword}")
        successful_products_count: int = 0
        try:
            raw_ideas: List[Dict[str, Any]] = _generate_ideas_for_keyword(
                gemini=gemini,
                design_prompt=prompts["design"],
                keyword=keyword,
                ideas_per_keyword=ideas_per_keyword,
            )
        except Exception as exc:  # noqa: BLE001
            log_action(f"Failed to generate ideas for '{keyword}': {exc}")
            continue

        for raw_idea in raw_ideas:
            try:
                idea: Idea = _build_idea_object(raw_idea=raw_idea, keyword=keyword)
                idea.folder_path.mkdir(parents=True, exist_ok=True)
                _save_idea_json(idea)

                _, transparent_path, _, mockup_cropped_path = _generate_design_assets(
                    idea=idea,
                    prompts=prompts,
                    gemini=gemini,
                    remove_bg_client=remove_bg_client,
                )

                listing_title, description, tags = _generate_listing_fields(
                    idea=idea,
                    prompts=prompts,
                    gemini=gemini,
                )

                selected_colors: List[str] = _select_colors(idea, color_to_ids)
                sampled_price = printify_client.pick_base_price_usd(
                    base_usd=constants.BASE_PRICE_USD,
                    stdev_usd=constants.PRICE_STDEV_USD,
                )
                uploaded_image: Dict[str, Any] = printify_client.upload_image(transparent_path)
                uploaded_mockup: Dict[str, Any] = printify_client.upload_image(mockup_cropped_path)
                if uploaded_image or uploaded_mockup:
                    write_json(
                        idea.folder_path / "printify_upload.json",
                        {
                            "design_transparent_upload": uploaded_image,
                            "default_mockup_upload": uploaded_mockup,
                        },
                    )

                payload: Dict[str, Any] = printify_client.build_payload(
                    title=unique_versioned_title(listing_title, constants.IMAGES_DIR),
                    description=description,
                    tags=tags,
                    selected_colors=selected_colors,
                    color_to_ids=color_to_ids,
                    design_transparent_path=transparent_path,
                    uploaded_image_id=uploaded_image.get("id") if uploaded_image else None,
                    base_price_usd=sampled_price,
                )
                write_json(idea.folder_path / "printify_payload.json", payload)

                result: Dict[str, Any] = printify_client.create_product(payload)
                write_json(idea.folder_path / "printify_result.json", result)
                successful_products_count += 1
                log_action(f"Completed idea '{idea.title}'")
            except Exception as exc:  # noqa: BLE001
                log_action(f"Failed processing idea for keyword '{keyword}': {exc}")
                continue

        if successful_products_count > 0:
            updated: bool = mark_idea_as_published(
                path=constants.IDEAS_CSV_PATH,
                keyword=keyword,
                shirt_count=constants.IDEAS_PER_KEYWORD,
            )
            if not updated:
                log_action(
                    f"ideas.csv update skipped after publishing keyword '{keyword}'"
                )
