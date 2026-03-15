"""End-to-end mass production pipeline orchestration."""

import json
import os
import re
import time

# import random
from pathlib import Path
from typing import Any, List, Dict, Optional

from schedule.logger_config import log_action

import constants
from photoshop.design_crop import (
    crop_design_image_to_content,
    create_default_color_mockup,
)
from ui.design_review_ui import review_generated_designs
from clients.gemini_client import GeminiClient
from photoshop.io_utils import (
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
    cut,
)
from models import Idea
from clients.printify_client import PrintifyClient
from photoshop.remove_bg import RemoveBgClient
from schedule_updates import append_created_product_to_schedules


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
        "filter_design_descriptions": read_text(
            constants.FILTER_DESIGN_DESCRIPTIONS_PATH
        ),
    }


def _load_color_to_ids_map(path: Path) -> Dict[str, List[int]]:
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
        "mockup_color": str(raw.get("mockup_color", "")).strip(),
        "design_colors": [
            str(c).strip() for c in raw.get("design_colors", []) if str(c).strip()
        ],
        "shirt_colors": [
            str(c).strip() for c in raw.get("shirt_colors", []) if str(c).strip()
        ],
    }


def _build_idea_object(raw_idea: dict[str, Any], keyword: str) -> Idea:
    """Create Idea object with versioned title and output folder.

    Args:
        raw_idea: Model-generated idea payload.
        keyword: Keyword used to generate this idea.

    Returns:
        Idea model with derived storage fields.
    """
    keyword_products_dir: Path = _keyword_products_dir(keyword)
    normalized: Dict[str, Any] = _normalize_idea_payload(raw_idea, keyword)
    original_title: str = normalized["title"]
    title: str = unique_versioned_title(original_title, keyword_products_dir)
    folder_name: str = slugify_title(title)
    folder_path: Path = keyword_products_dir / folder_name
    normalized["title"] = title
    return Idea(
        keyword=keyword,
        original_title=original_title,
        title=title,
        folder_name=folder_name,
        folder_path=folder_path,
        payload=normalized,
    )


def _keyword_products_dir(keyword: str) -> Path:
    """Get the output directory for one keyword's products.

    Args:
        keyword: Source keyword value.

    Returns:
        Per-keyword products directory path.
    """
    return constants.PRODUCTS_DIR / slugify_title(keyword)


def _generate_ideas_for_keyword(
    gemini: GeminiClient,
    design_prompt: str,
    keyword: str,
    context: str,
    ideas_per_keyword: int,
) -> List[Dict[str, Any]]:
    """Generate normalized idea payloads for a keyword.

    Args:
        gemini: Gemini text/image client.
        design_prompt: Base design prompt template.
        keyword: Source keyword.
        context: Space-separated context words associated with the keyword.
        ideas_per_keyword: Number of ideas to generate.

    Returns:
        List of raw idea dictionaries.
    """

    prompt: str = (
        f"{design_prompt}\n\n"
        f"Keyword: {keyword}\n"
        f"Context: {context}\n"
        f"Generate exactly {ideas_per_keyword} ideas."
    )
    response_text: str = gemini.generate_text(prompt)
    ideas: List[Dict] = parse_json_array(response_text)
    log_action(f"Generated {len(ideas)} ideas for keyword '{keyword}'")
    return ideas[:ideas_per_keyword]


def _parse_filter_response_payload(response_text: str) -> dict[str, Any]:
    """Parse JSON object payload from filter model output.

    Args:
        response_text: Raw Gemini output text.

    Returns:
        Parsed dictionary payload.
    """
    return _parse_json_object_payload(response_text)


def _parse_json_object_payload(response_text: str) -> dict[str, Any]:
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


def _write_persona_files(folder_path: Path, payload: dict[str, Any]) -> None:
    """Write buyer and beneficiary persona text artifacts.

    Args:
        folder_path: Product output folder.
        payload: Parsed model payload containing persona fields.
    """
    log_action(f"Writing persona files for '{cut(folder_path)}'")
    buyer_persona_1: str = str(payload.get("buyer_persona_1", "")).strip()
    buyer_persona_2: str = str(payload.get("buyer_persona_2", "")).strip()
    beneficiary_persona_1: str = str(payload.get("beneficiary_persona_1", "")).strip()
    beneficiary_persona_2: str = str(payload.get("beneficiary_persona_2", "")).strip()

    buyer_personas_text: str = (
        f"Buyer Persona 1:\n{buyer_persona_1}\n\nBuyer Persona 2:\n{buyer_persona_2}"
    )
    beneficiary_personas_text: str = (
        "Beneficiary Persona 1:\n"
        f"{beneficiary_persona_1}\n\n"
        "Beneficiary Persona 2:\n"
        f"{beneficiary_persona_2}"
    )
    write_text(folder_path / "buyer_personas.txt", buyer_personas_text)
    write_text(folder_path / "beneficiary_personas.txt", beneficiary_personas_text)


def _filter_ideas_for_keyword(
    gemini: GeminiClient,
    filter_prompt: str,
    keyword: str,
    raw_ideas: list[dict[str, Any]],
    filtered_ideas_per_keyword: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter and rank generated ideas before expensive asset generation.

    Args:
        gemini: Gemini text client.
        filter_prompt: Prompt template for design filtering.
        keyword: Source keyword for generated ideas.
        raw_ideas: Raw generated ideas.
        filtered_ideas_per_keyword: Max number of selected ideas.

    Returns:
        Tuple of (filtered ideas list, filter metadata payload).
    """
    log_action(f"Filtering {len(raw_ideas)} generated ideas for keyword '{keyword}'")
    if not raw_ideas:
        return [], {"selected_designs": []}

    ideas_json: str = json.dumps(raw_ideas, indent=2)
    prompt: str = (
        f"Keyword: {keyword}\n"
        f"# Input ideas JSON:\n{ideas_json}\n\n"
        f"{filter_prompt}\n"
        f"Filter this list of {constants.IDEAS_PER_KEYWORD} ideas down to the best "
        f"{filtered_ideas_per_keyword} ideas for product creation. "
    )
    response_text: str = gemini.generate_text(prompt)
    parsed_payload: dict[str, Any] = _parse_filter_response_payload(response_text)
    raw_selected_designs: Any = parsed_payload.get("selected_designs", [])

    normalized_selected_designs: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    if isinstance(raw_selected_designs, list):
        for item in raw_selected_designs:
            if not isinstance(item, dict):
                continue
            index_value: Any = item.get("index")
            if not isinstance(index_value, int):
                continue
            if index_value < 0 or index_value >= len(raw_ideas):
                continue
            if index_value in seen_indexes:
                continue
            seen_indexes.add(index_value)

            pass_value_raw: Any = item.get("pass", False)
            rank_value_raw: Any = item.get("rank", len(raw_ideas) + index_value + 1)
            reason_value_raw: Any = item.get("reason", "")

            pass_value: bool = bool(pass_value_raw)
            rank_value: int = (
                rank_value_raw
                if isinstance(rank_value_raw, int)
                else len(raw_ideas) + index_value + 1
            )
            reason_value: str = str(reason_value_raw).strip()

            normalized_selected_designs.append(
                {
                    "index": index_value,
                    "pass": pass_value,
                    "rank": rank_value,
                    "reason": reason_value,
                }
            )

    for missing_index in range(len(raw_ideas)):
        if missing_index in seen_indexes:
            continue
        normalized_selected_designs.append(
            {
                "index": missing_index,
                "pass": False,
                "rank": len(raw_ideas) + missing_index + 1,
                "reason": "No filter response generated for this idea.",
            }
        )

    normalized_selected_designs.sort(
        key=lambda item: (int(item["rank"]), int(item["index"]))
    )

    passing_indexes: list[int] = [
        int(item["index"]) for item in normalized_selected_designs if bool(item["pass"])
    ]
    selected_indexes: list[int] = passing_indexes[:filtered_ideas_per_keyword]
    if not selected_indexes:
        selected_indexes = [
            int(item["index"])
            for item in normalized_selected_designs[:filtered_ideas_per_keyword]
        ]

    selected_ideas: list[dict[str, Any]] = [
        raw_ideas[index] for index in selected_indexes
    ]
    filter_metadata: dict[str, Any] = {"selected_designs": normalized_selected_designs}
    log_action(
        f"Filtered ideas for '{keyword}': selected {len(selected_ideas)} of {len(raw_ideas)}"
    )
    return selected_ideas, filter_metadata


def _save_idea_json(idea: Idea) -> None:
    """Save per-idea JSON output.

    Args:
        idea: Idea payload object.
    """
    write_json(idea.folder_path / "ideas.json", [idea.payload])
    log_action(
        f"Saved idea JSON for '{idea.title}' to '{cut(idea.folder_path / 'ideas.json')}'"
    )


def _generate_design_image(
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
    _safe_dashboard_call(dashboard, "update_image", "raw_design", design_path)
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
    _safe_dashboard_call(
        dashboard,
        "update_image",
        "transparent_design",
        transparent_path,
    )

    background_prompt: str = f"Design JSON:\n{idea_json}\n\n{prompts['background']}"
    log_action(f"Generating background text for '{idea.title}'")
    background_response_text: str = gemini.generate_text(background_prompt).strip()
    background_payload: dict[str, Any] = _parse_json_object_payload(
        background_response_text
    )
    _write_persona_files(idea.folder_path, background_payload)
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
    _safe_dashboard_call(
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
    _safe_dashboard_call(dashboard, "update_image", "generated_mockup", mockup_path)

    # cropped mockup
    log_action(f"Cropping mockup image for '{idea.title}'")
    mockup_cropped_path: Path = (
        idea.folder_path / f"mockup_({slugified_color})_cropped.png"
    )
    crop_center_percent(mockup_path, mockup_cropped_path, constants.CROP_CENTER_PERCENT)
    _safe_dashboard_call(
        dashboard, "update_image", "cropped_mockup", mockup_cropped_path
    )

    return transparent_path, mockup_path, mockup_cropped_path


def _run_manual_design_review(
    keyword: str,
    keyword_products_dir: Path,
    design_entries: list[dict[str, Any]],
    prompts: dict[str, str],
    gemini: GeminiClient,
    max_retries: int,
    dashboard: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Run manual keep/retry/reject review for generated designs.

    Args:
        keyword: Source keyword.
        keyword_products_dir: Directory for keyword-scoped artifacts.
        design_entries: Generated design entries and idea payloads.
        prompts: Prompt templates.
        gemini: Gemini client.
        max_retries: Maximum retries per design.

    Returns:
        List of design entries approved for downstream processing.
    """
    selected_entries: list[dict[str, Any]] = []
    rejected_indexes: set[int] = set()
    pending_indexes: list[int] = [entry["review_index"] for entry in design_entries]
    by_index: dict[int, dict[str, Any]] = {
        int(entry["review_index"]): entry for entry in design_entries
    }
    decision_log: list[dict[str, Any]] = []

    while pending_indexes:
        ui_payload: list[dict[str, Any]] = []
        for review_index in pending_indexes:
            entry = by_index[review_index]
            idea: Idea = entry["idea"]
            ui_payload.append(
                {
                    "index": review_index,
                    "idea_index": int(entry["idea_index"]),
                    "title": idea.title,
                    "retry_count": int(entry["retry_count"]),
                    "image_path": str(entry["design_path"]),
                }
            )

        decisions: dict[int, str] = review_generated_designs(
            keyword=keyword,
            designs=ui_payload,
        )

        next_pending_indexes: list[int] = []
        for review_index in pending_indexes:
            decision: str = decisions.get(review_index, "keep")
            entry = by_index[review_index]
            idea = entry["idea"]
            decision_log.append(
                {
                    "index": review_index,
                    "idea_index": int(entry["idea_index"]),
                    "title": idea.title,
                    "decision": decision,
                    "retry_count": int(entry["retry_count"]),
                }
            )

            if decision == "keep":
                selected_entries.append(entry)
                continue
            if decision == "reject":
                rejected_indexes.add(review_index)
                continue

            retry_count: int = int(entry["retry_count"])
            if retry_count >= max_retries:
                rejected_indexes.add(review_index)
                log_action(
                    f"Review retry limit reached for '{idea.title}' (max={max_retries}); rejecting"
                )
                continue

            _, design_bytes = _generate_design_image(
                idea=idea,
                prompts=prompts,
                gemini=gemini,
                dashboard=dashboard,
            )
            entry["design_bytes"] = design_bytes
            entry["retry_count"] = retry_count + 1
            next_pending_indexes.append(review_index)

        pending_indexes = next_pending_indexes

    review_summary: dict[str, Any] = {
        "keyword": keyword,
        "selected_indexes": [int(entry["review_index"]) for entry in selected_entries],
        "rejected_indexes": sorted(int(index) for index in rejected_indexes),
        "decisions": decision_log,
    }
    write_json(keyword_products_dir / "design_review.json", review_summary)
    return selected_entries


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
    generated_description: str = gemini.generate_text(description_prompt).strip()

    full_description: str = (
        f"{generated_description}\n\n{prompts['default_description']}"
    )

    # keywords
    log_action(f"Generating keywords for '{idea.title}'")
    keywords_prompt: str = f"{prompts['keywords']}\n\nDesign JSON:\n{idea_json}"
    keywords_csv: str = gemini.generate_text(keywords_prompt).strip()
    keywords: List[str] = normalize_keywords_csv_to_json_array(
        keywords_csv=keywords_csv,
        max_len=constants.KEYWORD_MAX_LENGTH,
    )[: constants.KEYWORDS_COUNT]

    write_text(idea.folder_path / "title.txt", generated_title)
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
    colors: List[str] = [
        c for c in idea.payload.get("shirt_colors", []) if c in color_to_ids
    ]
    if colors:
        return colors
    return list(color_to_ids.keys())


def _create_progress_dashboard() -> Optional[Any]:
    """Create the optional pipeline progress dashboard.

    Returns:
        Dashboard instance when enabled, else None.
    """
    if not constants.ENABLE_PROGRESS_UI:
        return None
    try:
        from ui.progress_dashboard import PipelineProgressDashboard

        return PipelineProgressDashboard(enabled=True)
    except Exception as exc:  # noqa: BLE001
        log_action(f"Progress dashboard is unavailable; continuing without UI: {exc}")
        return None


def _safe_dashboard_call(
    dashboard: Optional[Any],
    method_name: str,
    *args: Any,
) -> None:
    """Invoke one dashboard method and suppress UI errors.

    Args:
        dashboard: Dashboard object or None.
        method_name: Method to call.
        args: Positional args for the dashboard method.
    """
    if dashboard is None:
        return
    try:
        method = getattr(dashboard, method_name)
        method(*args)
    except Exception as exc:  # noqa: BLE001
        log_action(f"Dashboard update failed for method '{method_name}': {exc}")


def run_pipeline(
    dry_run: bool,
) -> None:
    """Run the full generation pipeline for ideas, assets, listings, and payloads.

    Args:
        dry_run: If true, skip real Printify product creation.
    """
    dashboard: Optional[Any] = _create_progress_dashboard()
    interrupted: bool = False
    _safe_dashboard_call(dashboard, "set_stage", "Loading prompts and input files")
    try:
        prompts: Dict[str, str] = _load_prompts()
        keywords, contexts = read_keywords_from_ideas_csv(
            constants.IDEAS_CSV_PATH, limit=constants.MAX_KEYWORDS_PER_RUN
        )
        color_to_ids: Dict[str, List[int]] = _load_color_to_ids_map(
            constants.VARIANT_MAP_PATH
        )

        if not keywords:
            message: str = "No ideas marked used=false found in ideas.csv"
            log_action(message)
            print(message)
            return

        _safe_dashboard_call(dashboard, "set_total_ideas", 0)
        _safe_dashboard_call(dashboard, "set_stage", "Initializing clients")

        gemini_key: str = _require_setting(
            "GEMINI_API_KEY", constants.GEMINI_API_KEY_PATH
        )
        background_removal_mode: str = constants.BACKGROUND_REMOVAL_MODE.strip().lower()
        removebg_key: str = ""
        if background_removal_mode == constants.REMOVE_BG_API:
            removebg_key = _require_setting(
                "REMOVEBG_API_KEY", constants.REMOVEBG_API_KEY_PATH
            )
        printify_token: str = _require_setting(
            "PRINTIFY_API_TOKEN", constants.PRINTIFY_API_TOKEN_PATH
        )
        printify_shop_id: str = _require_setting(
            "PRINTIFY_SHOP_ID", constants.PRINTIFY_SHOP_ID_PATH
        )

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
            removal_mode=background_removal_mode,
            smart_matte_start=constants.SMART_BG_MATTE_START,
            smart_matte_end=constants.SMART_BG_MATTE_END,
            smart_feather_radius=constants.SMART_BG_FEATHER_RADIUS,
            smart_edge_alpha_min=constants.SMART_BG_EDGE_ALPHA_MIN,
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

        total_ideas_scheduled: int = 0
        for idx, (keyword, context) in enumerate(zip(keywords, contexts), start=1):
            keyword_products_dir: Path = _keyword_products_dir(keyword)
            keyword_products_dir.mkdir(parents=True, exist_ok=True)
            _safe_dashboard_call(dashboard, "set_keyword", keyword, idx, len(keywords))
            _safe_dashboard_call(
                dashboard,
                "set_stage",
                "Generating and filtering ideas",
            )
            log_action(f"Processing keyword ({idx}/{len(keywords)}): '{keyword}'")
            successful_products_count: int = 0
            try:
                raw_ideas: List[Dict[str, Any]] = _generate_ideas_for_keyword(
                    gemini=gemini,
                    design_prompt=prompts["design"],
                    keyword=keyword,
                    context=context,
                    ideas_per_keyword=constants.IDEAS_PER_KEYWORD,
                )
                filtered_ideas, filter_metadata = _filter_ideas_for_keyword(
                    gemini=gemini,
                    filter_prompt=prompts["filter_design_descriptions"],
                    keyword=keyword,
                    raw_ideas=raw_ideas,
                    filtered_ideas_per_keyword=constants.FILTERED_IDEAS_PER_KEYWORD,
                )
                total_ideas_scheduled += len(filtered_ideas)
                _safe_dashboard_call(
                    dashboard,
                    "set_total_ideas",
                    total_ideas_scheduled,
                )
                write_json(keyword_products_dir / "filtering.json", filter_metadata)
            except Exception as exc:  # noqa: BLE001
                error_message: str = f"Failed to generate ideas for '{keyword}': {exc}"
                log_action(error_message)
                _safe_dashboard_call(dashboard, "add_error", error_message)
                continue

            generated_designs: list[dict[str, Any]] = []
            n_ideas: int = len(filtered_ideas)
            loop_start_time: float = time.monotonic()
            completed_iterations: int = 0
            for idea_index, raw_idea in enumerate(filtered_ideas):
                idea_number: int = idea_index + 1
                iteration_start_time: float = time.monotonic()
                iteration_status: str = "success"
                try:
                    _safe_dashboard_call(
                        dashboard, "set_stage", "Generating raw design"
                    )
                    log_action(f"Processing idea {idea_number}/{n_ideas}")
                    idea: Idea = _build_idea_object(raw_idea=raw_idea, keyword=keyword)
                    _safe_dashboard_call(
                        dashboard,
                        "set_idea_name",
                        idea.title,
                        idea_number,
                        n_ideas,
                    )
                    idea.folder_path.mkdir(parents=True, exist_ok=True)
                    _save_idea_json(idea)

                    design_path, design_bytes = _generate_design_image(
                        idea=idea,
                        prompts=prompts,
                        gemini=gemini,
                        dashboard=dashboard,
                    )

                    generated_designs.append(
                        {
                            "review_index": len(generated_designs),
                            "idea_index": idea_index,
                            "idea": idea,
                            "design_path": design_path,
                            "design_bytes": design_bytes,
                            "retry_count": 0,
                        }
                    )

                except Exception as exc:  # noqa: BLE001
                    iteration_status = f"failed: {exc}"
                    error_message = (
                        f"Failed processing idea for keyword '{keyword}': {exc}"
                    )
                    log_action(error_message)
                    _safe_dashboard_call(dashboard, "add_error", error_message)
                    _safe_dashboard_call(dashboard, "mark_idea_finished", False)
                    continue
                finally:
                    completed_iterations += 1
                    elapsed_time_seconds: float = time.monotonic() - loop_start_time
                    average_iteration_seconds: float = (
                        elapsed_time_seconds / completed_iterations
                    )
                    estimated_total_seconds: float = average_iteration_seconds * n_ideas
                    estimated_remaining_seconds: float = max(
                        estimated_total_seconds - elapsed_time_seconds,
                        0.0,
                    )
                    iteration_duration_seconds: float = (
                        time.monotonic() - iteration_start_time
                    )
                    log_action(
                        "Filtered-idea timing | "
                        f"keyword='{keyword}' | "
                        f"iteration={completed_iterations}/{n_ideas} | "
                        f"status='{iteration_status}' | "
                        f"iteration_seconds={iteration_duration_seconds:.1f} | "
                        f"elapsed_seconds={elapsed_time_seconds:.1f} | "
                        f"estimated_remaining_seconds={estimated_remaining_seconds:.1f} | "
                        f"estimated_total_seconds={estimated_total_seconds:.1f}"
                    )

            if not generated_designs:
                log_action(f"No designs generated for keyword '{keyword}'")
                continue

            approved_designs: list[dict[str, Any]] = generated_designs
            if constants.REVIEW_DESIGNS:
                _safe_dashboard_call(dashboard, "set_stage", "Manual design review")
                try:
                    approved_designs = _run_manual_design_review(
                        keyword=keyword,
                        keyword_products_dir=keyword_products_dir,
                        design_entries=generated_designs,
                        prompts=prompts,
                        gemini=gemini,
                        max_retries=constants.DESIGN_REVIEW_MAX_RETRIES,
                        dashboard=dashboard,
                    )
                    rejected_count: int = len(generated_designs) - len(approved_designs)
                    for _ in range(max(0, rejected_count)):
                        _safe_dashboard_call(dashboard, "mark_idea_finished", False)
                except Exception as exc:  # noqa: BLE001
                    error_message = (
                        f"Manual design review failed for '{keyword}': {exc}"
                    )
                    log_action(error_message)
                    _safe_dashboard_call(dashboard, "add_error", error_message)
                    for _ in range(len(generated_designs)):
                        _safe_dashboard_call(dashboard, "mark_idea_finished", False)
                    continue

            approved_ideas_count: int = len(approved_designs)
            for approved_index, design_entry in enumerate(approved_designs, start=1):
                try:
                    idea: Idea = design_entry["idea"]
                    design_path: Path = design_entry["design_path"]
                    design_bytes: bytes = design_entry["design_bytes"]
                    _safe_dashboard_call(
                        dashboard,
                        "set_idea_name",
                        idea.title,
                        approved_index,
                        approved_ideas_count,
                    )
                    _safe_dashboard_call(
                        dashboard,
                        "set_stage",
                        "Generating transparent image and mockups",
                    )
                    transparent_path, _, mockup_cropped_path = (
                        _generate_post_design_assets(
                            idea=idea,
                            prompts=prompts,
                            gemini=gemini,
                            remove_bg_client=remove_bg_client,
                            design_path=design_path,
                            design_bytes=design_bytes,
                            dashboard=dashboard,
                        )
                    )

                    _safe_dashboard_call(
                        dashboard, "set_stage", "Generating listing text"
                    )
                    listing_title, description, tags = _generate_listing_fields(
                        idea=idea,
                        prompts=prompts,
                        gemini=gemini,
                    )

                    _safe_dashboard_call(
                        dashboard,
                        "set_stage",
                        "Uploading assets and creating product",
                    )
                    selected_colors: List[str] = _select_colors(idea, color_to_ids)
                    sampled_price = printify_client.pick_base_price_usd(
                        base_usd=constants.BASE_PRICE_USD,
                        stdev_usd=constants.PRICE_STDEV_USD,
                    )
                    uploaded_image: Dict[str, Any] = printify_client.upload_image(
                        transparent_path
                    )
                    uploaded_mockup: Dict[str, Any] = printify_client.upload_image(
                        mockup_cropped_path
                    )
                    if uploaded_image or uploaded_mockup:
                        write_json(
                            idea.folder_path / "printify_upload.json",
                            {
                                "design_transparent_upload": uploaded_image,
                                "default_mockup_upload": uploaded_mockup,
                            },
                        )

                    payload: Dict[str, Any] = printify_client.build_payload(
                        title=unique_versioned_title(
                            listing_title,
                            keyword_products_dir,
                        ),
                        description=description,
                        tags=tags,
                        selected_colors=selected_colors,
                        color_to_ids=color_to_ids,
                        design_transparent_path=transparent_path,
                        uploaded_image_id=uploaded_image.get("id")
                        if uploaded_image
                        else None,
                        base_price_usd=sampled_price,
                    )
                    write_json(idea.folder_path / "printify_payload.json", payload)

                    result: Dict[str, Any] = printify_client.create_product(payload)
                    write_json(idea.folder_path / "printify_result.json", result)
                    created_product_id: str = str(result.get("id", "")).strip()
                    if created_product_id:
                        try:
                            schedule_added: bool = append_created_product_to_schedules(
                                product_title=str(payload.get("title", listing_title)),
                                product_id=created_product_id,
                            )
                            if schedule_added:
                                log_action(
                                    f"Scheduled product '{created_product_id}' for auto publish"
                                )
                        except Exception as exc:  # noqa: BLE001
                            log_action(
                                f"Schedule update failed for product '{created_product_id}': {exc}"
                            )
                    successful_products_count += 1
                    _safe_dashboard_call(dashboard, "mark_idea_finished", True)
                    log_action(f"Completed idea '{idea.title}'")
                except Exception as exc:  # noqa: BLE001
                    error_message = (
                        f"Failed processing idea for keyword '{keyword}': {exc}"
                    )
                    log_action(error_message)
                    _safe_dashboard_call(dashboard, "add_error", error_message)
                    _safe_dashboard_call(dashboard, "mark_idea_finished", False)
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
    except KeyboardInterrupt:
        interrupted = True
        message: str = "Pipeline interrupted by user (Ctrl+C)"
        log_action(message)
        _safe_dashboard_call(dashboard, "add_error", message)
    finally:
        final_stage: str = "Interrupted" if interrupted else "Completed"
        _safe_dashboard_call(dashboard, "set_stage", final_stage)
        if dashboard is not None:
            dashboard.close()
