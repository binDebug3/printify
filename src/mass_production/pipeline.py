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
    generate_post_design_assets,
)
from generation.listing import generate_listing_fields, select_colors
from photoshop.remove_bg import RemoveBgClient
from product.models import Idea
from product.schedule_updates import append_created_product_to_schedules
from schedule.logger_config import log_action
from ui.dashboard_adapter import create_progress_dashboard
from ui.review import run_manual_design_review


class Orchestrator(object):
    """Class-based orchestrator for the mass production pipeline."""

    def __init__(self, dry_run: bool = constants.DEFAULT_DRY_RUN):
        self.dry_run = dry_run
        self.dashboard = None
        self.gemini_key: str = require_setting(
            "GEMINI_API_KEY", constants.GEMINI_API_KEY_PATH
        )
        self.background_removal_mode: str = (
            constants.BACKGROUND_REMOVAL_MODE.strip().lower()
        )
        self.removebg_key: str = ""
        self.get_required_constants()
        self.set_up_api_clients()

    def get_required_constants(self):
        """
        Load and validate required constants from the configuration.
        """
        if self.background_removal_mode == constants.REMOVE_BG_API:
            self.removebg_key = require_setting(
                "REMOVEBG_API_KEY", constants.REMOVEBG_API_KEY_PATH
            )
        self.printify_token: str = require_setting(
            "PRINTIFY_API_TOKEN", constants.PRINTIFY_API_TOKEN_PATH
        )
        self.printify_shop_id: str = require_setting(
            "PRINTIFY_SHOP_ID", constants.PRINTIFY_SHOP_ID_PATH
        )

    def safe_dashboard_call(
        self,
        method_name: str,
        *args: Any,
    ) -> None:
        """Invoke one dashboard method and suppress UI errors.

        Args:
            dashboard: Dashboard object or None.
            method_name: Method to call.
            args: Positional args for the dashboard method.
        """
        if self.dashboard is None:
            return
        try:
            method = getattr(self.dashboard, method_name)
            method(*args)
        except Exception as exc:  # noqa: BLE001
            log_action(f"Dashboard update failed for method '{method_name}': {exc}")

    def set_up_api_clients(self):
        """
        Set up API clients for Gemini, Remove.bg, and Printify using configuration settings.
        """
        self.gemini: GeminiClient = GeminiClient(
            api_key=self.gemini_key,
            text_model=constants.TEXT_MODEL,
            image_model=constants.IMAGE_MODEL,
            retries=constants.MAX_GEMINI_RETRIES,
        )
        self.remove_bg_client: RemoveBgClient = RemoveBgClient(
            api_key=self.removebg_key,
            endpoint=constants.REMOVE_BG_URL,
            retries=constants.MAX_REMOVEBG_RETRIES,
            removal_mode=self.background_removal_mode,
            smart_matte_start=constants.SMART_BG_MATTE_START,
            smart_matte_end=constants.SMART_BG_MATTE_END,
            smart_feather_radius=constants.SMART_BG_FEATHER_RADIUS,
            smart_edge_alpha_min=constants.SMART_BG_EDGE_ALPHA_MIN,
        )
        self.printify_client: PrintifyClient = PrintifyClient(
            token=self.printify_token,
            shop_id=self.printify_shop_id,
            blueprint_id=constants.BLUEPRINT_ID,
            print_provider_id=constants.PRINT_PROVIDER_ID,
            size_order=constants.SIZE_ORDER,
            size_surcharge_usd=constants.SIZE_SURCHARGE_USD,
            print_x=constants.PRINT_POSITION_X,
            print_y=constants.PRINT_POSITION_Y,
            print_scale=constants.PRINT_SCALE,
            min_price_usd=constants.MIN_PRICE_USD,
            dry_run=self.dry_run,
            retries=constants.MAX_PRINTIFY_RETRIES,
            max_requests_per_minute=constants.PRINTIFY_MAX_REQUESTS_PER_MINUTE,
        )

    def set_up_prompting(self):
        """
        Load and store prompts for idea generation, filtering, design, and listing creation.
        """
        self.prompts: Dict[str, str] = load_prompts()
        self.keywords, self.contexts = read_keywords_from_ideas_csv(
            constants.IDEAS_CSV_PATH, limit=constants.MAX_KEYWORDS_PER_RUN
        )
        self.color_to_ids: Dict[str, List[int]] = load_color_to_ids_map(
            constants.VARIANT_MAP_PATH
        )

    def generate_filtered_ideas(
        self,
        keyword: str,
        context: str,
    ) -> None:
        """
        Generate and filter ideas for a given keyword and context,
        and update the dashboard with progress.

        Args:
            keyword: The keyword for which to generate ideas.
            context: Additional context to inform idea generation.
        """
        self.filtered_ideas: List[Dict[str, Any]] = []
        try:
            raw_ideas: List[Dict[str, Any]] = generate_ideas_for_keyword(
                gemini=self.gemini,
                design_prompt=self.prompts["design"],
                keyword=keyword,
                context=context,
                ideas_per_keyword=constants.IDEAS_PER_KEYWORD,
            )
            write_json(self.keyword_dir / "initial_ideas.json", raw_ideas)
            self.filtered_ideas, filter_metadata = filter_ideas_for_keyword(
                gemini=self.gemini,
                filter_prompt=self.prompts["filter_design_descriptions"],
                keyword=keyword,
                raw_ideas=raw_ideas,
                filtered_ideas_per_keyword=constants.FILTERED_IDEAS_PER_KEYWORD,
            )
            self.total_ideas_scheduled += len(self.filtered_ideas)
            self.safe_dashboard_call("set_total_ideas", self.total_ideas_scheduled)
            write_json(self.keyword_dir / "filtering.json", filter_metadata)
        except Exception as exc:  # noqa: BLE001
            error_message: str = f"Failed to generate ideas for '{keyword}': {exc}"
            log_action(error_message)
            self.safe_dashboard_call("add_error", error_message)

    def build_idea(
        self,
        idea_number: int,
        keyword: str,
        raw_idea: Dict[str, Any],
    ) -> None:
        """
        Build an Idea object from raw idea data and update the dashboard with progress.

        Args:
            idea_number: The sequential number of the idea being processed for the current keyword.
            keyword: The keyword associated with the idea.
            raw_idea: The raw idea data as a dictionary.
        """
        self.safe_dashboard_call("clear_images")
        self.safe_dashboard_call("set_stage", "Generating raw design")
        log_action(f"Processing idea {idea_number}/{self.n_ideas}")
        self.idea: Idea = build_idea_object(raw_idea=raw_idea, keyword=keyword)
        self.safe_dashboard_call(
            "set_idea_name",
            self.idea.title,
            idea_number,
            self.n_ideas,
        )
        self.idea.folder_path.mkdir(parents=True, exist_ok=True)
        save_idea_json(self.idea)

    def generate_design(
        self,
        idea_index: int,
    ) -> None:
        """
        Generate a design image for the current idea and update the dashboard with progress.

        Args:
            idea_index: The index of the idea in the list of filtered ideas for the current word.
        """
        design_path, design_bytes = generate_design_image(
            idea=self.idea,
            prompts=self.prompts,
            gemini=self.gemini,
            dashboard=self.dashboard,
        )

        self.generated_designs.append(
            {
                "review_index": len(self.generated_designs),
                "idea_index": idea_index,
                "idea": self.idea,
                "design_path": design_path,
                "design_bytes": design_bytes,
                "retry_count": 0,
            }
        )

    def generate_mockup(
        self,
        approved_index: int,
        approved_ideas_count: int,
        design_entry: dict[str, Any],
    ) -> None:
        """
        Generate a mockup image for the approved design and update the dashboard with progress.

        Args:
            approved_index: The index of the approved design in the list of approved designs for
                the current keyword.
            approved_ideas_count: The total number of approved designs for the current keyword.
            design_entry: A dictionary containing the idea and design information for the approved
                design.
        """
        idea: Idea = design_entry["idea"]
        self.idea = idea
        design_path: Optional[Path] = design_entry.get("design_path")
        design_bytes: bytes = design_entry["design_bytes"]
        self.safe_dashboard_call("clear_images")
        self.safe_dashboard_call(
            "set_idea_name",
            idea.title,
            approved_index,
            approved_ideas_count,
        )
        if design_path is not None:
            self.safe_dashboard_call("update_image", "raw_design", design_path)
        self.safe_dashboard_call(
            "set_stage",
            "Generating transparent image and mockups",
        )
        self.transparent_path, _, self.mockup_cropped_path = (
            generate_post_design_assets(
                idea=idea,
                prompts=self.prompts,
                gemini=self.gemini,
                remove_bg_client=self.remove_bg_client,
                design_bytes=design_bytes,
                dashboard=self.dashboard,
            )
        )
        save_final_mockup_image(
            idea=idea,
            mockup_cropped_path=self.mockup_cropped_path,
        )

    def update_timer(
        self,
        keyword: str,
    ) -> None:
        """
        Update timing metrics for the current iteration and log the estimated remaining time
        for the keyword.

        Args:
            keyword: The keyword associated with the current iteration, used for logging context.
        """
        self.completed_iterations += 1
        elapsed_time_seconds: float = time.monotonic() - self.loop_start_time
        average_iteration_seconds: float = (
            elapsed_time_seconds / self.completed_iterations
        )
        estimated_total_seconds: float = average_iteration_seconds * self.n_ideas
        estimated_remaining_seconds: float = max(
            estimated_total_seconds - elapsed_time_seconds,
            0.0,
        )
        iteration_duration_seconds: float = time.monotonic() - self.iteration_start_time
        log_action(
            "Filtered-idea timing | "
            f"keyword='{keyword}' | "
            f"iteration={self.completed_iterations}/{self.n_ideas} | "
            f"status='{self.iteration_status}' | "
            f"iteration_seconds={iteration_duration_seconds:.1f} | "
            f"elapsed_seconds={elapsed_time_seconds:.1f} | "
            f"estimated_remaining_seconds={estimated_remaining_seconds:.1f} | "
            f"estimated_total_seconds={estimated_total_seconds:.1f}"
        )

    def log_keyword_start(
        self,
        keyword: str,
        idx: int,
    ) -> None:
        """
        Log the start of processing for a new keyword and update the dashboard stage.

        Args:
            keyword: The keyword that is starting processing.
            idx: The index of the keyword in the list of keywords being processed.
        """
        self.keyword_dir: Path = keyword_products_dir(keyword)
        self.keyword_dir.mkdir(parents=True, exist_ok=True)
        self.safe_dashboard_call("set_keyword", keyword, idx, len(self.keywords))
        self.safe_dashboard_call("set_stage", "Generating and filtering ideas")
        log_action(f"Processing keyword ({idx}/{len(self.keywords)}): '{keyword}'")

    def log_design_error(
        self,
        keyword: str,
        exc: Exception,
    ) -> None:
        """
        Log an error that occurred during design generation and update the dashboard with
        the error message.

        Args:
            keyword: The keyword associated with the idea that failed to generate a design.
            exc: The exception that was raised during design generation.
        """
        self.iteration_status = f"failed: {exc}"
        error_message = f"Failed processing idea for keyword '{keyword}': {exc}"
        log_action(error_message)
        self.safe_dashboard_call("add_error", error_message)
        self.safe_dashboard_call("mark_idea_finished", False)

    def review_design(
        self,
        keyword,
    ) -> bool:
        """
        Run the manual design review process for the generated designs of a keyword, and update the
        dashboard with the results.

        Args:
            keyword: The keyword associated with the designs being reviewed.

        Returns:
            True if the design review process completed successfully, False if it failed.
        """
        success: bool = True
        self.safe_dashboard_call("set_stage", "Manual design review")
        try:
            self.approved_designs = run_manual_design_review(
                keyword=keyword,
                keyword_products_dir=self.keyword_dir,
                design_entries=self.generated_designs,
                prompts=self.prompts,
                gemini=self.gemini,
                max_retries=constants.DESIGN_REVIEW_MAX_RETRIES,
                dashboard=self.dashboard,
            )
            rejected_count: int = len(self.generated_designs) - len(
                self.approved_designs
            )
            for _ in range(max(0, rejected_count)):
                self.safe_dashboard_call("mark_idea_finished", False)
        except Exception as exc:  # noqa: BLE001
            success = False
            error_message = f"Manual design review failed for '{keyword}': {exc}"
            log_action(error_message)
            self.safe_dashboard_call("add_error", error_message)
            for _ in range(len(self.generated_designs)):
                self.safe_dashboard_call("mark_idea_finished", False)
        return success

    def upload_image(
        self,
        idea: Idea,
    ) -> Dict[str, Any]:
        """
        Upload the generated design and mockup images to Printify and save the upload results,
        while updating the dashboard stage and handling any errors that occur during the upload
        process.

        Returns:
            A dictionary containing the results of the image upload operations, which may include
            information about the uploaded design and mockup images.
        """
        self.safe_dashboard_call(
            "set_stage",
            "Uploading assets and creating product",
        )
        uploaded_image: Dict[str, Any] = self.printify_client.upload_image(
            self.transparent_path
        )
        uploaded_mockup: Dict[str, Any] = self.printify_client.upload_image(
            self.mockup_cropped_path
        )
        if uploaded_image or uploaded_mockup:
            write_json(
                idea.folder_path / "printify_upload.json",
                {
                    "design_transparent_upload": uploaded_image,
                    "default_mockup_upload": uploaded_mockup,
                },
            )
        return uploaded_image

    def build_printify_payload(
        self,
    ) -> None:
        """
        Build the payload for creating a Printify product based on the idea and generated assets,
        and save the payload to a JSON file in the idea's folder.
        """
        self.safe_dashboard_call("set_stage", "Generating listing text")
        self.listing_title, description, tags = generate_listing_fields(
            idea=self.idea,
            prompts=self.prompts,
            gemini=self.gemini,
        )

        uploaded_image = self.upload_image(self.idea)

        sampled_price = self.printify_client.pick_base_price_usd(
            base_usd=constants.BASE_PRICE_USD,
            stdev_usd=constants.PRICE_STDEV_USD,
        )
        selected_colors: List[str] = select_colors(self.idea, self.color_to_ids)
        self.payload: Dict[str, Any] = self.printify_client.build_payload(
            title=unique_versioned_title(
                self.listing_title,
                self.keyword_dir,
            ),
            description=description,
            tags=tags,
            selected_colors=selected_colors,
            color_to_ids=self.color_to_ids,
            design_transparent_path=self.transparent_path,
            uploaded_image_id=uploaded_image.get("id") if uploaded_image else None,
            base_price_usd=sampled_price,
        )
        write_json(self.idea.folder_path / "printify_payload.json", self.payload)

    def post_to_printify(
        self,
    ) -> None:
        """
        Post the created product payload to Printify to create a draft product, and handle
        any errors that occur during the product creation process.
        """
        result: Dict[str, Any] = self.printify_client.create_product(self.payload)
        write_json(self.idea.folder_path / "printify_result.json", result)
        created_product_id: str = str(result.get("id", "")).strip()
        if created_product_id:
            try:
                schedule_added: bool = append_created_product_to_schedules(
                    product_title=str(self.payload.get("title", self.listing_title)),
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
        self.successful_products_count += 1
        self.safe_dashboard_call("mark_idea_finished", True)
        log_action(f"Completed idea '{self.idea.title}'")

    def generate_all_designs(
        self,
        keyword: str,
    ) -> None:
        """
        Generate designs for all filtered ideas of the current keyword, and update the dashboard

        Args:
            keyword: The keyword associated with the ideas for which to generate designs.
        """
        for idea_index, raw_idea in enumerate(self.filtered_ideas):
            idea_number: int = idea_index + 1
            self.iteration_start_time: float = time.monotonic()
            self.iteration_status: str = "success"

            try:
                self.build_idea(idea_number, keyword, raw_idea)
                self.generate_design(idea_index)
            except Exception as exc:  # noqa: BLE001
                self.log_design_error(keyword, exc)
                continue
            finally:
                self.update_timer(keyword)

    def post_all_products(
        self,
        keyword: str,
    ) -> None:
        """
        Post all approved designs for the current keyword to Printify, and handle any errors that
        occur during the posting process.

        Args:
            keyword: The keyword associated with the approved designs to post.
        """
        approved_ideas_count: int = len(self.approved_designs)
        for approved_index, design_entry in enumerate(self.approved_designs, start=1):
            try:
                self.generate_mockup(approved_index, approved_ideas_count, design_entry)
                self.build_printify_payload()
                self.post_to_printify()

            except Exception as exc:  # noqa: BLE001
                error_message = f"Failed processing idea for keyword '{keyword}': {exc}"
                log_action(error_message)
                self.safe_dashboard_call("add_error", error_message)
                self.safe_dashboard_call("mark_idea_finished", False)
                continue

    def record_post(
        self,
        keyword: str,
    ) -> None:
        """
        After posting products for a keyword, update the ideas.csv file to mark the idea as
        published, and log the result of the update operation.

        Args:
            keyword: The keyword associated with the idea to mark as published.
        """
        if self.successful_products_count > 0:
            updated: bool = mark_idea_as_published(
                path=constants.IDEAS_CSV_PATH,
                keyword=keyword,
                shirt_count=self.successful_products_count,
            )
            if not updated:
                log_action(
                    f"ideas.csv update skipped after publishing keyword '{keyword}'"
                )

    def start_dashboard(self) -> None:
        """
        Initialize and start the progress dashboard for the mass production pipeline, and handle
        any errors that occur during dashboard initialization.
        """
        self.dashboard: Optional[Any] = create_progress_dashboard()
        self.safe_dashboard_call("set_total_ideas", 0)
        self.safe_dashboard_call("set_stage", "Initializing clients")

    def run_pipeline(self) -> None:
        """Run the full generation pipeline for ideas, assets, listings, and payloads.

        Args:
            dry_run: If true, skip real Printify product creation.
        """
        interrupted: bool = False
        try:
            self.set_up_prompting()
            if not self.keywords:
                log_action("No ideas marked used=false found in ideas.csv")
                return

            self.start_dashboard()
            self.total_ideas_scheduled: int = 0
            for idx, (keyword, context) in enumerate(
                zip(self.keywords, self.contexts), start=1
            ):
                self.log_keyword_start(keyword, idx)
                self.successful_products_count: int = 0

                self.generate_filtered_ideas(keyword, context)
                if len(self.filtered_ideas) == 0:
                    continue

                self.generated_designs: list[dict[str, Any]] = []
                self.n_ideas: int = len(self.filtered_ideas)
                self.loop_start_time: float = time.monotonic()
                self.completed_iterations: int = 0

                self.generate_all_designs(keyword)
                if not self.generated_designs:
                    log_action(f"No designs generated for keyword '{keyword}'")
                    continue

                self.approved_designs: list[dict[str, Any]] = self.generated_designs
                if constants.REVIEW_DESIGNS:
                    error_free: bool = self.review_design(keyword)
                    if not error_free:
                        continue

                self.post_all_products(keyword)
                self.record_post(keyword)

        except KeyboardInterrupt:
            interrupted = True
            message: str = "Pipeline interrupted by user (Ctrl+C)"
            log_action(message)
            self.safe_dashboard_call("add_error", message)

        finally:
            final_stage: str = "Interrupted" if interrupted else "Completed"
            try:
                self.safe_dashboard_call("set_stage", final_stage)
                if self.dashboard is not None:
                    self.dashboard.close()
            except UnboundLocalError as e:
                log_action(f"Dashboard close failed because it was never opened: {e}")
