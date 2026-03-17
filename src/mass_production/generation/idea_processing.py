"""
Idea processing functions for mass product generation pipeline.
"""

from typing import List, Dict, Any
from pathlib import Path
import json

from config import constants
from clients.gemini_client import GeminiClient
from file_tools.io_utils import (
    write_text,
    slugify_title,
    unique_versioned_title,
    cut,
)
from file_tools.parsing import (
    parse_json_array,
    parse_json_object_payload,
)
from product.models import Idea
from config.config_loader import (
    keyword_products_dir,
)
from schedule.logger_config import log_action


def normalize_idea_payload(raw: dict[str, Any], keyword: str) -> dict[str, Any]:
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


def build_idea_object(raw_idea: dict[str, Any], keyword: str) -> Idea:
    """Create Idea object with versioned title and output folder.

    Args:
        raw_idea: Model-generated idea payload.
        keyword: Keyword used to generate this idea.

    Returns:
        Idea model with derived storage fields.
    """
    keyword_products_dir_str: Path = keyword_products_dir(keyword)
    normalized: Dict[str, Any] = normalize_idea_payload(raw_idea, keyword)
    original_title: str = normalized["title"]
    title: str = unique_versioned_title(original_title, keyword_products_dir_str)
    folder_name: str = slugify_title(title)
    folder_path: Path = keyword_products_dir_str / folder_name
    normalized["title"] = title
    return Idea(
        keyword=keyword,
        original_title=original_title,
        title=title,
        folder_name=folder_name,
        folder_path=folder_path,
        payload=normalized,
    )


def generate_ideas_for_keyword(
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


def write_persona_files(folder_path: Path, payload: dict[str, Any]) -> None:
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


def filter_ideas_for_keyword(
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
    parsed_payload: dict[str, Any] = parse_json_object_payload(response_text)
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
