"""
This module implements the manual design review step of the mass production pipeline,
where a user reviews generated designs and decides whether to keep, reject, or retry them.
"""

from pathlib import Path
from typing import Any, Optional

from clients.gemini_client import GeminiClient
from file_tools.io_utils import write_json
from generation.assets import generate_design_image
from product.models import Idea
from ui.design_review_ui import review_generated_designs
from schedule.logger_config import log_action


def run_manual_design_review(
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

            _, design_bytes = generate_design_image(
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
