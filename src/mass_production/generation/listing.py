"""
Listing generation logic for mass production pipeline.
"""

from typing import List, Dict
import json

from config import constants
from clients.gemini_client import GeminiClient
from file_tools.io_utils import write_text
from file_tools.ideas_manager import normalize_keywords_csv_to_json_array
from product.models import Idea
from schedule.logger_config import log_action


def generate_listing_fields(
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


def select_colors(idea: Idea, color_to_ids: Dict[str, List[int]]) -> List[str]:
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
