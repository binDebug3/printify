"""Tests for structured-output prompt loading, parsing, and retries."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import config.constants as constants  # noqa: E402
from config.config_loader import load_prompts  # noqa: E402
from file_tools.parsing import (  # noqa: E402
    parse_json_array,
    parse_json_object_payload_strict,
)
import generation.idea_processing as idea_processing  # noqa: E402
from generation.structured_output import generate_structured_output  # noqa: E402


class TestPromptLoading:
    """Tests for prompt loading with response schemas."""

    def test_load_prompts_appends_design_and_background_response_formats(self):
        """Adds authoritative response-shape instructions to structured prompts."""
        prompts = load_prompts()

        assert "## Required Response Format" in prompts["design"]
        assert "array of objects" in prompts["design"]
        assert '"title": "text"' in prompts["design"]
        assert "## Required Response Format" in prompts["background"]
        assert "single object matching this exact shape" in prompts["background"]
        assert '"mockup_scene": "text"' in prompts["background"]
        assert '"selected_designs"' in prompts["filter_design_descriptions"]
        assert '"selected_designs"' in prompts["filter_design_images_response"]


class TestParsing:
    """Tests for malformed JSON repair helpers."""

    def test_parse_json_array_recovers_from_code_fence_and_trailing_commas(self):
        """Repairs common Gemini JSON issues before parsing an array payload."""
        response_text = """
        Here you go:
        ```json
        [
          {
            "title": "Alpha",
            "shirt_colors": ["Black",],
          }
        ]
        ```
        """

        parsed_payload = parse_json_array(response_text)

        assert parsed_payload == [{"title": "Alpha", "shirt_colors": ["Black"]}]

    def test_parse_json_object_payload_strict_quotes_simple_keys(self):
        """Quotes simple object keys before parsing a background payload."""
        response_text = """
        {
          buyer_persona_1: "Weekend hiker",
          buyer_persona_2: "Gift shopper",
          mockup_scene: "Foggy trailhead"
        }
        """

        parsed_payload = parse_json_object_payload_strict(response_text)

        assert parsed_payload["buyer_persona_1"] == "Weekend hiker"
        assert parsed_payload["mockup_scene"] == "Foggy trailhead"


class TestStructuredOutputRetries:
    """Tests for content-format retries around Gemini text responses."""

    def test_generate_structured_output_retries_after_unrecoverable_json(
        self, tmp_path
    ):
        """Retries Gemini when the first response cannot be repaired into valid JSON."""
        gemini = MagicMock()
        gemini.generate_text.side_effect = [
            "[{'title': 'bad'}]",
            '[{"title": "good"}]',
        ]

        parsed_payload = generate_structured_output(
            gemini=gemini,
            prompt="Return JSON.",
            parser=parse_json_array,
            response_label="test ideas",
            output_dir=tmp_path,
            artifact_stem="ideas",
            max_retries=1,
        )

        assert parsed_payload == [{"title": "good"}]
        assert gemini.generate_text.call_count == 2
        assert (tmp_path / "ideas_attempt_1_response.txt").exists()
        assert (tmp_path / "ideas_attempt_1_retry_prompt.txt").exists()

    def test_filter_ideas_for_keyword_falls_back_after_repeated_bad_json(
        self,
        tmp_path,
    ):
        """Falls back to the default ordering when filter responses stay malformed."""
        raw_ideas = [
            {"title": "Idea 0"},
            {"title": "Idea 1"},
            {"title": "Idea 2"},
        ]
        gemini = MagicMock()
        gemini.generate_text.return_value = "{'selected_designs': []}"

        original_keyword_products_dir = idea_processing.keyword_products_dir
        idea_processing.keyword_products_dir = lambda keyword: tmp_path / keyword
        try:
            filtered_ideas, metadata = idea_processing.filter_ideas_for_keyword(
                gemini=gemini,
                filter_prompt="Filter these ideas.",
                keyword="alpha",
                raw_ideas=raw_ideas,
                filtered_ideas_per_keyword=2,
            )
        finally:
            idea_processing.keyword_products_dir = original_keyword_products_dir

        assert [idea["title"] for idea in filtered_ideas] == ["Idea 0", "Idea 1"]
        assert len(metadata["selected_designs"]) == 3
        assert metadata["selected_designs"][0]["reason"] == (
            "No filter response generated for this idea."
        )
        assert gemini.generate_text.call_count == (
            constants.MAX_STRUCTURED_OUTPUT_RETRIES + 1
        )
