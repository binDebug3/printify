"""
End-to-end mass production pipeline orchestration.

"""

import time
from pathlib import Path
from typing import Any, List, Dict, Optional

import config.constants as constants
from config.config_loader import (
    load_prompts,
    load_color_to_ids_map,
    require_setting,
    keyword_products_dir,
)
from clients.gemini_client import GeminiClient
from clients.printify_client import PrintifyClient
from file_tools.io_utils import (
    unique_versioned_title,
    write_json,
    save_idea_json,
    save_final_mockup_image,
)
from file_tools.ideas_manager import (
    read_keywords_from_ideas_csv,
    mark_idea_as_published,
)
from generation.idea_processing import (
    build_idea_object,
    generate_ideas_for_keyword,
    filter_ideas_for_keyword,
)
from generation.assets import (
    generate_design_image,
    _generate_post_design_assets,
)
from generation.listing import generate_listing_fields, select_colors
from photoshop.remove_bg import RemoveBgClient
from product.models import Idea
from product.schedule_updates import append_created_product_to_schedules
from schedule.logger_config import log_action
from ui.dashboard_adapter import create_progress_dashboard, safe_dashboard_call
from ui.review import run_manual_design_review


def run_pipeline(
    dry_run: bool,
) -> None:
    """Run the full generation pipeline for ideas, assets, listings, and payloads.

    Args:
        dry_run: If true, skip real Printify product creation.
    """
    dashboard: Optional[Any] = create_progress_dashboard()
    interrupted: bool = False
    safe_dashboard_call(dashboard, "set_stage", "Loading prompts and input files")
    try:
        prompts: Dict[str, str] = load_prompts()
        keywords, contexts = read_keywords_from_ideas_csv(
            constants.IDEAS_CSV_PATH, limit=constants.MAX_KEYWORDS_PER_RUN
        )
        color_to_ids: Dict[str, List[int]] = load_color_to_ids_map(
            constants.VARIANT_MAP_PATH
        )

        if not keywords:
            message: str = "No ideas marked used=false found in ideas.csv"
            log_action(message)
            print(message)
            return

        safe_dashboard_call(dashboard, "set_total_ideas", 0)
        safe_dashboard_call(dashboard, "set_stage", "Initializing clients")

        gemini_key: str = require_setting(
            "GEMINI_API_KEY", constants.GEMINI_API_KEY_PATH
        )
        background_removal_mode: str = constants.BACKGROUND_REMOVAL_MODE.strip().lower()
        removebg_key: str = ""
        if background_removal_mode == constants.REMOVE_BG_API:
            removebg_key = require_setting(
                "REMOVEBG_API_KEY", constants.REMOVEBG_API_KEY_PATH
            )
        printify_token: str = require_setting(
            "PRINTIFY_API_TOKEN", constants.PRINTIFY_API_TOKEN_PATH
        )
        printify_shop_id: str = require_setting(
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
            keyword_products_dir_str: Path = keyword_products_dir(keyword)
            keyword_products_dir_str.mkdir(parents=True, exist_ok=True)
            safe_dashboard_call(dashboard, "set_keyword", keyword, idx, len(keywords))
            safe_dashboard_call(
                dashboard,
                "set_stage",
                "Generating and filtering ideas",
            )
            log_action(f"Processing keyword ({idx}/{len(keywords)}): '{keyword}'")
            successful_products_count: int = 0
            try:
                raw_ideas: List[Dict[str, Any]] = generate_ideas_for_keyword(
                    gemini=gemini,
                    design_prompt=prompts["design"],
                    keyword=keyword,
                    context=context,
                    ideas_per_keyword=constants.IDEAS_PER_KEYWORD,
                )
                write_json(keyword_products_dir_str / "initial_ideas.json", raw_ideas)
                filtered_ideas, filter_metadata = filter_ideas_for_keyword(
                    gemini=gemini,
                    filter_prompt=prompts["filter_design_descriptions"],
                    keyword=keyword,
                    raw_ideas=raw_ideas,
                    filtered_ideas_per_keyword=constants.FILTERED_IDEAS_PER_KEYWORD,
                )
                total_ideas_scheduled += len(filtered_ideas)
                safe_dashboard_call(
                    dashboard,
                    "set_total_ideas",
                    total_ideas_scheduled,
                )
                write_json(keyword_products_dir_str / "filtering.json", filter_metadata)
            except Exception as exc:  # noqa: BLE001
                error_message: str = f"Failed to generate ideas for '{keyword}': {exc}"
                log_action(error_message)
                safe_dashboard_call(dashboard, "add_error", error_message)
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
                    safe_dashboard_call(dashboard, "set_stage", "Generating raw design")
                    log_action(f"Processing idea {idea_number}/{n_ideas}")
                    idea: Idea = build_idea_object(raw_idea=raw_idea, keyword=keyword)
                    safe_dashboard_call(
                        dashboard,
                        "set_idea_name",
                        idea.title,
                        idea_number,
                        n_ideas,
                    )
                    idea.folder_path.mkdir(parents=True, exist_ok=True)
                    save_idea_json(idea)

                    design_path, design_bytes = generate_design_image(
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
                    safe_dashboard_call(dashboard, "add_error", error_message)
                    safe_dashboard_call(dashboard, "mark_idea_finished", False)
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
                safe_dashboard_call(dashboard, "set_stage", "Manual design review")
                try:
                    approved_designs = run_manual_design_review(
                        keyword=keyword,
                        keyword_products_dir=keyword_products_dir_str,
                        design_entries=generated_designs,
                        prompts=prompts,
                        gemini=gemini,
                        max_retries=constants.DESIGN_REVIEW_MAX_RETRIES,
                        dashboard=dashboard,
                    )
                    rejected_count: int = len(generated_designs) - len(approved_designs)
                    for _ in range(max(0, rejected_count)):
                        safe_dashboard_call(dashboard, "mark_idea_finished", False)
                except Exception as exc:  # noqa: BLE001
                    error_message = (
                        f"Manual design review failed for '{keyword}': {exc}"
                    )
                    log_action(error_message)
                    safe_dashboard_call(dashboard, "add_error", error_message)
                    for _ in range(len(generated_designs)):
                        safe_dashboard_call(dashboard, "mark_idea_finished", False)
                    continue

            approved_ideas_count: int = len(approved_designs)
            for approved_index, design_entry in enumerate(approved_designs, start=1):
                try:
                    idea: Idea = design_entry["idea"]
                    design_path: Path = design_entry["design_path"]
                    design_bytes: bytes = design_entry["design_bytes"]
                    safe_dashboard_call(
                        dashboard,
                        "set_idea_name",
                        idea.title,
                        approved_index,
                        approved_ideas_count,
                    )
                    safe_dashboard_call(
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
                    save_final_mockup_image(
                        idea=idea,
                        mockup_cropped_path=mockup_cropped_path,
                    )

                    safe_dashboard_call(
                        dashboard, "set_stage", "Generating listing text"
                    )
                    listing_title, description, tags = generate_listing_fields(
                        idea=idea,
                        prompts=prompts,
                        gemini=gemini,
                    )

                    safe_dashboard_call(
                        dashboard,
                        "set_stage",
                        "Uploading assets and creating product",
                    )
                    selected_colors: List[str] = select_colors(idea, color_to_ids)
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
                            keyword_products_dir_str,
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
                    safe_dashboard_call(dashboard, "mark_idea_finished", True)
                    log_action(f"Completed idea '{idea.title}'")
                except Exception as exc:  # noqa: BLE001
                    error_message = (
                        f"Failed processing idea for keyword '{keyword}': {exc}"
                    )
                    log_action(error_message)
                    safe_dashboard_call(dashboard, "add_error", error_message)
                    safe_dashboard_call(dashboard, "mark_idea_finished", False)
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
        safe_dashboard_call(dashboard, "add_error", message)
    finally:
        final_stage: str = "Interrupted" if interrupted else "Completed"
        safe_dashboard_call(dashboard, "set_stage", final_stage)
        if dashboard is not None:
            dashboard.close()
