"""Tests for mass_production.pipeline orchestration."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

google_module = ModuleType("google")
genai_module = ModuleType("google.genai")
genai_module.Client = MagicMock()
genai_module.types = SimpleNamespace()
google_module.genai = genai_module
gemini_client_module = ModuleType("gemini_client")
gemini_client_module.GeminiClient = MagicMock()
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)
sys.modules.setdefault("gemini_client", gemini_client_module)

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
            pipeline_module.run_pipeline(dry_run=True)

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
                    "filter_design_descriptions": "filter prompt",
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
                pipeline_module.constants,
                "REVIEW_DESIGNS",
                False,
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
            patch.object(
                pipeline_module,
                "_filter_ideas_for_keyword",
                return_value=(
                    [{"title": "Alpha Shirt"}],
                    {
                        "selected_designs": [
                            {"index": 0, "pass": True, "rank": 1, "reason": "fit"}
                        ]
                    },
                ),
            ),
            patch.object(pipeline_module, "_build_idea_object", return_value=idea),
            patch.object(
                pipeline_module,
                "_generate_design_image",
                return_value=(transparent_path, b"png"),
            ),
            patch.object(
                pipeline_module,
                "_generate_post_design_assets",
                return_value=(
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
            pipeline_module.run_pipeline(dry_run=False)

        mock_mark.assert_called_once_with(
            path=constants.IDEAS_CSV_PATH,
            keyword="alpha",
            shirt_count=constants.IDEAS_PER_KEYWORD,
        )

    def test_manual_background_mode_skips_removebg_secret_lookup(self, tmp_path):
        """Does not require the remove.bg secret when manual background removal is enabled."""
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
                    "filter_design_descriptions": "filter prompt",
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
                pipeline_module.constants,
                "REVIEW_DESIGNS",
                False,
            ),
            patch.object(
                pipeline_module,
                "_require_setting",
                side_effect=["gemini-key", "printify-token", "shop-id"],
            ) as mock_require_setting,
            patch.object(
                pipeline_module.constants,
                "BACKGROUND_REMOVAL_MODE",
                constants.BACKGROUND_REMOVAL_MODE_MANUAL,
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
            patch.object(
                pipeline_module,
                "_filter_ideas_for_keyword",
                return_value=(
                    [{"title": "Alpha Shirt"}],
                    {
                        "selected_designs": [
                            {"index": 0, "pass": True, "rank": 1, "reason": "fit"}
                        ]
                    },
                ),
            ),
            patch.object(pipeline_module, "_build_idea_object", return_value=idea),
            patch.object(
                pipeline_module,
                "_generate_design_image",
                return_value=(transparent_path, b"png"),
            ),
            patch.object(
                pipeline_module,
                "_generate_post_design_assets",
                return_value=(transparent_path, mockup_path, mockup_path),
            ),
            patch.object(
                pipeline_module,
                "_generate_listing_fields",
                return_value=("Listing Title", "Description", ["tag one", "tag two"]),
            ),
            patch.object(pipeline_module, "_select_colors", return_value=["pepper"]),
            patch.object(pipeline_module, "mark_idea_as_published", return_value=True),
        ):
            pipeline_module.run_pipeline(dry_run=False)

        assert mock_require_setting.call_args_list == [
            (("GEMINI_API_KEY", constants.GEMINI_API_KEY_PATH),),
            (("PRINTIFY_API_TOKEN", constants.PRINTIFY_API_TOKEN_PATH),),
            (("PRINTIFY_SHOP_ID", constants.PRINTIFY_SHOP_ID_PATH),),
        ]

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
                    "filter_design_descriptions": "filter prompt",
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
                pipeline_module,
                "_filter_ideas_for_keyword",
                return_value=(
                    [{"title": "Alpha Shirt"}],
                    {
                        "selected_designs": [
                            {"index": 0, "pass": True, "rank": 1, "reason": "fit"}
                        ]
                    },
                ),
            ),
            patch.object(
                pipeline_module, "_build_idea_object", side_effect=RuntimeError("boom")
            ),
            patch.object(pipeline_module, "mark_idea_as_published") as mock_mark,
        ):
            pipeline_module.run_pipeline(dry_run=False)

        mock_mark.assert_not_called()

    def test_filter_ideas_for_keyword_limits_to_filtered_count(self):
        """Returns top passing designs up to FILTERED_IDEAS_PER_KEYWORD."""
        raw_ideas = [{"title": f"Idea {idx}"} for idx in range(4)]
        gemini = MagicMock()
        gemini.generate_text.return_value = """
        {
          "selected_designs": [
            {"index": 0, "pass": true, "rank": 3, "reason": "ok"},
            {"index": 1, "pass": false, "rank": 4, "reason": "weak"},
            {"index": 2, "pass": true, "rank": 1, "reason": "best"},
            {"index": 3, "pass": true, "rank": 2, "reason": "good"}
          ]
        }
        """

        filtered_ideas, metadata = pipeline_module._filter_ideas_for_keyword(
            gemini=gemini,
            filter_prompt="filter prompt",
            keyword="alpha",
            raw_ideas=raw_ideas,
            filtered_ideas_per_keyword=2,
        )

        assert len(filtered_ideas) == 2
        assert filtered_ideas[0]["title"] == "Idea 2"
        assert filtered_ideas[1]["title"] == "Idea 3"
        assert "selected_designs" in metadata
        assert len(metadata["selected_designs"]) == 4


class TestGenerateDesignImage:
    """Tests for design image generation and auto-cropping."""

    def test_generate_design_image_crops_before_writing(self, tmp_path):
        """Runs the generated image through the content cropper before saving."""
        idea = Idea(
            keyword="alpha",
            original_title="Alpha Shirt",
            title="Alpha Shirt 1",
            folder_name="Alpha_Shirt_1",
            folder_path=tmp_path / "Alpha_Shirt_1",
            payload={"title": "Alpha Shirt 1"},
        )
        gemini = MagicMock()
        gemini.generate_image.return_value = b"raw-image"

        with patch.object(
            pipeline_module,
            "crop_design_image_to_content",
            return_value=b"cropped-image",
        ) as mock_crop:
            design_path, design_bytes = pipeline_module._generate_design_image(
                idea=idea,
                prompts={"image": "image prompt"},
                gemini=gemini,
            )

        mock_crop.assert_called_once_with(
            image_bytes=b"raw-image",
            padding_percent=constants.DESIGN_CROP_PADDING_PERCENT,
        )
        assert design_path == idea.folder_path / "design.png"
        assert design_path.read_bytes() == b"cropped-image"
        assert design_bytes == b"cropped-image"


class TestNormalizeIdeaPayload:
    """Tests for idea payload normalization."""

    def test_preserves_mockup_color_field(self):
        """Copies the new mockup_color field from raw Gemini payload."""
        raw_payload = {
            "title": "Alpha",
            "mockup_color": "Light Blue",
            "shirt_colors": ["pepper"],
        }

        normalized = pipeline_module._normalize_idea_payload(raw_payload, "alpha")

        assert normalized["mockup_color"] == "Light Blue"


class TestGeneratePostDesignAssets:
    """Tests for post-design asset generation flow."""

    def test_uses_default_color_mockup_as_gemini_input(self, tmp_path: Path):
        """Conditions Gemini mockup generation with the pre-composed default mockup."""
        idea_folder = tmp_path / "idea"
        idea_folder.mkdir(parents=True, exist_ok=True)
        design_path = idea_folder / "design.png"
        design_path.write_bytes(b"design-bytes")

        idea = Idea(
            keyword="alpha",
            original_title="Alpha Shirt",
            title="Alpha Shirt 1",
            folder_name="Alpha_Shirt_1",
            folder_path=idea_folder,
            payload={"mockup_color": "Light Blue"},
        )
        gemini = MagicMock()
        gemini.generate_text.return_value = "Studio"
        gemini.generate_image.return_value = b"mockup-final"
        remove_bg_client = MagicMock()
        remove_bg_client.remove_background.return_value = b"transparent"

        default_mockup_path = idea_folder / "mockup_default_lightBlue.png"
        default_mockup_path.write_bytes(b"default-mockup")

        with (
            patch.object(
                pipeline_module,
                "create_default_color_mockup",
                return_value=default_mockup_path,
            ) as mock_create_default,
            patch.object(
                pipeline_module,
                "crop_center_percent",
                return_value=None,
            ),
        ):
            _, mockup_path, mockup_cropped_path = (
                pipeline_module._generate_post_design_assets(
                    idea=idea,
                    prompts={"background": "bg", "mockup": "mk"},
                    gemini=gemini,
                    remove_bg_client=remove_bg_client,
                    design_path=design_path,
                    design_bytes=b"raw-design",
                )
            )

        mock_create_default.assert_called_once_with(
            design_path=design_path,
            color="Light Blue",
            output_dir=idea.folder_path,
        )
        assert mockup_path.exists()
        assert mockup_cropped_path.name.endswith("_cropped.png")
        gemini.generate_image.assert_called_once()
        _, kwargs = gemini.generate_image.call_args
        assert kwargs["image_bytes"] == b"default-mockup"

    def test_raises_when_mockup_color_is_missing(self, tmp_path: Path):
        """Fails fast when mockup_color is absent from the idea payload."""
        idea_folder = tmp_path / "idea"
        idea_folder.mkdir(parents=True, exist_ok=True)
        design_path = idea_folder / "design.png"
        design_path.write_bytes(b"design-bytes")

        idea = Idea(
            keyword="alpha",
            original_title="Alpha Shirt",
            title="Alpha Shirt 1",
            folder_name="Alpha_Shirt_1",
            folder_path=idea_folder,
            payload={},
        )

        with pytest.raises(ValueError, match="mockup_color"):
            pipeline_module._generate_post_design_assets(
                idea=idea,
                prompts={"background": "bg", "mockup": "mk"},
                gemini=MagicMock(),
                remove_bg_client=MagicMock(),
                design_path=design_path,
                design_bytes=b"raw-design",
            )
