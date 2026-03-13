"""Tests for mass_production.pipeline orchestration."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from models import Idea  # noqa: E402
import constants  # noqa: E402
import pipeline as pipeline_module  # noqa: E402


class TestRunPipeline:
    """Tests for run_pipeline."""

    def test_logs_and_prints_when_no_unused_keywords_exist(self):
        """Stops early with a user-visible message when ideas.csv has no used=false rows."""
        with (
            patch.object(pipeline_module, "_load_prompts", return_value={}),
            patch.object(
                pipeline_module, "read_keywords_from_ideas_csv", return_value=[]
            ),
            patch.object(
                pipeline_module,
                "_load_color_to_ids_map",
                return_value={"pepper": [101]},
            ),
            patch.object(pipeline_module, "log_action") as mock_log,
            patch("builtins.print") as mock_print,
        ):
            pipeline_module.run_pipeline(
                dry_run=True, keyword_limit=5, ideas_per_keyword=2
            )

        message = "No ideas marked used=false found in ideas.csv"
        mock_log.assert_called_with(message)
        mock_print.assert_called_once_with(message)

    def test_marks_keyword_as_published_after_successful_product_creation(
        self, tmp_path
    ):
        """Updates ideas.csv after at least one idea for the keyword completes successfully."""
        transparent_path = tmp_path / "design_transparent.png"
        mockup_path = tmp_path / "mockup.png"
        transparent_path.write_bytes(b"png")
        mockup_path.write_bytes(b"png")

        idea = Idea(
            keyword="alpha",
            original_title="Alpha Shirt",
            title="Alpha Shirt 1",
            folder_name="Alpha_Shirt_1",
            folder_path=tmp_path / "Alpha_Shirt_1",
            payload={"shirt_colors": ["pepper"]},
        )
        mock_printify_client = MagicMock()
        mock_printify_client.pick_base_price_usd.return_value = 29.45
        mock_printify_client.upload_image.side_effect = [
            {"id": "img-1"},
            {"id": "img-2"},
        ]
        mock_printify_client.build_payload.return_value = {
            "title": "Listing Title 1",
            "variants": [
                {"id": 101, "price": 2945, "is_enabled": True, "is_default": True}
            ],
        }
        mock_printify_client.create_product.return_value = {"id": "prod-1"}

        with (
            patch.object(
                pipeline_module,
                "_load_prompts",
                return_value={
                    "design": "design prompt",
                    "image": "image prompt",
                    "background": "background prompt",
                    "mockup": "mockup prompt",
                    "title": "title prompt",
                    "description": "description prompt",
                    "keywords": "keywords prompt",
                    "default_description": "default description",
                },
            ),
            patch.object(
                pipeline_module, "read_keywords_from_ideas_csv", return_value=["alpha"]
            ),
            patch.object(
                pipeline_module,
                "_load_color_to_ids_map",
                return_value={"pepper": [101]},
            ),
            patch.object(
                pipeline_module,
                "_require_setting",
                side_effect=["gemini-key", "removebg-key", "printify-token", "shop-id"],
            ),
            patch.object(pipeline_module, "GeminiClient", return_value=MagicMock()),
            patch.object(pipeline_module, "RemoveBgClient", return_value=MagicMock()),
            patch.object(
                pipeline_module, "PrintifyClient", return_value=mock_printify_client
            ),
            patch.object(
                pipeline_module,
                "_generate_ideas_for_keyword",
                return_value=[{"title": "Alpha Shirt"}],
            ),
            patch.object(pipeline_module, "_build_idea_object", return_value=idea),
            patch.object(
                pipeline_module,
                "_generate_design_assets",
                return_value=(
                    transparent_path,
                    transparent_path,
                    mockup_path,
                    mockup_path,
                ),
            ),
            patch.object(
                pipeline_module,
                "_generate_listing_fields",
                return_value=("Listing Title", "Description", ["tag one", "tag two"]),
            ),
            patch.object(pipeline_module, "_select_colors", return_value=["pepper"]),
            patch.object(
                pipeline_module, "mark_idea_as_published", return_value=True
            ) as mock_mark,
        ):
            pipeline_module.run_pipeline(
                dry_run=False, keyword_limit=1, ideas_per_keyword=9
            )

        mock_mark.assert_called_once_with(
            path=constants.IDEAS_CSV_PATH,
            keyword="alpha",
            shirt_count=constants.IDEAS_PER_KEYWORD,
        )

    def test_does_not_mark_keyword_published_when_all_ideas_fail(self):
        """Skips ideas.csv updates when no product finishes successfully for the keyword."""
        with (
            patch.object(
                pipeline_module,
                "_load_prompts",
                return_value={
                    "design": "design prompt",
                    "image": "image prompt",
                    "background": "background prompt",
                    "mockup": "mockup prompt",
                    "title": "title prompt",
                    "description": "description prompt",
                    "keywords": "keywords prompt",
                    "default_description": "default description",
                },
            ),
            patch.object(
                pipeline_module, "read_keywords_from_ideas_csv", return_value=["alpha"]
            ),
            patch.object(
                pipeline_module,
                "_load_color_to_ids_map",
                return_value={"pepper": [101]},
            ),
            patch.object(
                pipeline_module,
                "_require_setting",
                side_effect=["gemini-key", "removebg-key", "printify-token", "shop-id"],
            ),
            patch.object(pipeline_module, "GeminiClient", return_value=MagicMock()),
            patch.object(pipeline_module, "RemoveBgClient", return_value=MagicMock()),
            patch.object(pipeline_module, "PrintifyClient", return_value=MagicMock()),
            patch.object(
                pipeline_module,
                "_generate_ideas_for_keyword",
                return_value=[{"title": "Alpha Shirt"}],
            ),
            patch.object(
                pipeline_module, "_build_idea_object", side_effect=RuntimeError("boom")
            ),
            patch.object(pipeline_module, "mark_idea_as_published") as mock_mark,
        ):
            pipeline_module.run_pipeline(
                dry_run=False, keyword_limit=1, ideas_per_keyword=2
            )

        mock_mark.assert_not_called()
