"""Tests for mass_production.pipeline orchestration."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Iterator
from unittest.mock import MagicMock, patch
import pytest

MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

google_module = ModuleType("google")
genai_module = ModuleType("google.genai")
setattr(genai_module, "Client", MagicMock())
setattr(genai_module, "types", SimpleNamespace())
setattr(google_module, "genai", genai_module)
gemini_client_module = ModuleType("gemini_client")
setattr(gemini_client_module, "GeminiClient", MagicMock())
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)
sys.modules.setdefault("gemini_client", gemini_client_module)

from product.models import Idea  # noqa: E402
import config.constants as constants  # noqa: E402
import pipeline as pipeline_module  # noqa: E402
import generation.idea_processing  # noqa: E402
import generation.assets  # noqa: E402
import generation.listing  # noqa: E402
import file_tools.io_utils  # noqa: E402


@pytest.fixture(autouse=True)
def disable_progress_ui() -> Iterator[None]:
    """Disable the optional Tk progress dashboard for automated tests."""
    with patch.object(pipeline_module.constants, "ENABLE_PROGRESS_UI", False):
        yield


class TestRunPipeline:
    """Tests for run_pipeline."""

    @staticmethod
    def _build_orchestrator() -> pipeline_module.Orchestrator:
        """Create an Orchestrator instance without running constructor side effects."""
        orchestrator = pipeline_module.Orchestrator.__new__(
            pipeline_module.Orchestrator
        )
        orchestrator.dashboard = None
        return orchestrator

    def test_logs_and_prints_when_no_unused_keywords_exist(self):
        """Stops early with a user-visible message when ideas.csv has no used=false rows."""
        orchestrator = self._build_orchestrator()

        def _set_up_prompting() -> None:
            orchestrator.keywords = []
            orchestrator.contexts = []

        orchestrator.set_up_prompting = _set_up_prompting
        orchestrator.start_dashboard = MagicMock()
        orchestrator.safe_dashboard_call = MagicMock()

        with patch.object(pipeline_module, "log_action") as mock_log:
            orchestrator.run_pipeline()

        message = "No ideas marked used=false found in ideas.csv"
        mock_log.assert_called_with(message)
        orchestrator.start_dashboard.assert_not_called()

    def test_marks_keyword_as_published_after_successful_product_creation(
        self,
    ):
        """Updates ideas.csv after at least one idea for the keyword completes successfully."""
        orchestrator = self._build_orchestrator()
        orchestrator.successful_products_count = 2

        with patch.object(
            pipeline_module,
            "mark_idea_as_published",
            return_value=True,
        ) as mock_mark:
            orchestrator.record_post("alpha")

        mock_mark.assert_called_once_with(
            path=constants.IDEAS_CSV_PATH,
            keyword="alpha",
            shirt_count=2,
        )

    def test_manual_background_mode_skips_removebg_secret_lookup(self):
        """Does not require the remove.bg secret when manual background removal is enabled."""
        with (
            patch.object(
                pipeline_module.constants,
                "BACKGROUND_REMOVAL_MODE",
                constants.REMOVE_BG_MANUAL,
            ),
            patch.object(
                pipeline_module,
                "require_setting",
                side_effect=["gemini-key", "printify-token", "shop-id"],
            ) as mock_require_setting,
            patch.object(
                pipeline_module.Orchestrator,
                "set_up_api_clients",
                return_value=None,
            ),
        ):
            pipeline_module.Orchestrator(dry_run=False)

        assert mock_require_setting.call_args_list == [
            (("GEMINI_API_KEY", constants.GEMINI_API_KEY_PATH),),
            (("PRINTIFY_API_TOKEN", constants.PRINTIFY_API_TOKEN_PATH),),
            (("PRINTIFY_SHOP_ID", constants.PRINTIFY_SHOP_ID_PATH),),
        ]

    def test_does_not_mark_keyword_published_when_all_ideas_fail(self):
        """Skips ideas.csv updates when no product finishes successfully for the keyword."""
        orchestrator = self._build_orchestrator()
        orchestrator.successful_products_count = 0

        with patch.object(pipeline_module, "mark_idea_as_published") as mock_mark:
            orchestrator.record_post("alpha")

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

        filtered_ideas, metadata = generation.idea_processing.filter_ideas_for_keyword(
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


class TestPostToPrintify:
    """Tests for the final Printify post and schedule step."""

    @staticmethod
    def _build_orchestrator(tmp_path: Path) -> pipeline_module.Orchestrator:
        """Create an Orchestrator instance without running constructor side effects."""
        orchestrator = pipeline_module.Orchestrator.__new__(
            pipeline_module.Orchestrator
        )
        orchestrator.dashboard = None
        orchestrator.safe_dashboard_call = MagicMock()
        orchestrator.successful_products_count = 0
        orchestrator.payload = {"title": "Listing Title"}
        orchestrator.listing_title = "Listing Title"
        orchestrator.idea = Idea(
            keyword="alpha",
            original_title="Alpha",
            title="Alpha 1",
            folder_name="Alpha_1",
            folder_path=tmp_path / "Alpha_1",
            payload={"title": "Alpha 1"},
        )
        orchestrator.idea.folder_path.mkdir(parents=True, exist_ok=True)
        orchestrator.printify_client = MagicMock()
        orchestrator.printify_client.create_product.return_value = {"id": "prod-123"}
        return orchestrator

    def test_post_to_printify_schedules_with_folder_name(self, tmp_path: Path):
        """Uses folder_name for schedule nick_name so rows map to artifact directories."""
        orchestrator = self._build_orchestrator(tmp_path)

        with patch.object(
            pipeline_module,
            "append_created_product_to_schedules",
            return_value=True,
        ) as mock_append:
            orchestrator.post_to_printify()

        mock_append.assert_called_once_with(
            product_title="Alpha_1",
            product_id="prod-123",
        )

    def test_post_to_printify_recovers_missing_payload_file(self, tmp_path: Path):
        """Rewrites printify_payload.json when absent before create-product call."""
        orchestrator = self._build_orchestrator(tmp_path)
        payload_path = orchestrator.idea.folder_path / "printify_payload.json"
        if payload_path.exists():
            payload_path.unlink()

        with patch.object(
            pipeline_module,
            "append_created_product_to_schedules",
            return_value=True,
        ):
            orchestrator.post_to_printify()

        assert payload_path.exists()
        assert payload_path.read_text(encoding="utf-8").strip() != ""


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
            generation.assets,
            "crop_design_image_to_content",
            return_value=b"cropped-image",
        ) as mock_crop:
            design_path, design_bytes = generation.assets.generate_design_image(
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

    def test_keeps_supported_fields_and_ignores_removed_mockup_color(self):
        """Normalizes supported fields and omits legacy mockup_color from payload."""
        raw_payload = {
            "title": "Alpha",
            "shirt_colors": ["pepper"],
            "mockup_color": "Light Blue",
        }

        normalized = generation.idea_processing.normalize_idea_payload(
            raw_payload, "alpha"
        )

        assert normalized["title"] == "Alpha"
        assert normalized["shirt_colors"] == ["pepper"]
        assert "mockup_color" not in normalized


class TestGeneratePostDesignAssets:
    """Tests for post-design asset generation flow."""

    def test_saves_personas_and_background_scene_from_json_response(
        self,
        tmp_path: Path,
    ):
        """Persists persona artifacts before mockup generation uses the mockup scene."""
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
        gemini.generate_text.return_value = """{
            \"buyer_persona_1\": \"Office jokester\",
            \"buyer_persona_2\": \"Weekend griller\",
            \"beneficiary_persona_1\": \"New dad\",
            \"beneficiary_persona_2\": \"Retired pun champion\",
            \"mockup_scene\": \"Sunlit porch with coffee mug\"
        }"""
        gemini.generate_image.return_value = b"mockup-final"
        remove_bg_client = MagicMock()
        remove_bg_client.remove_background.return_value = b"transparent"
        mockup_shirt_path = idea_folder / "lightBlue.png"
        mockup_shirt_path.write_bytes(b"mockup-base")

        default_mockup_path = idea_folder / "mockup_default_lightBlue.png"
        default_mockup_path.write_bytes(b"default-mockup")

        with (
            patch.object(
                generation.assets,
                "create_default_color_mockup",
                return_value=default_mockup_path,
            ),
            patch.object(
                generation.assets,
                "pick_mockup_shirt",
                return_value=mockup_shirt_path,
            ),
            patch.object(
                generation.assets,
                "crop_center_percent",
                return_value=None,
            ),
        ):
            generation.assets.generate_post_design_assets(
                idea=idea,
                prompts={"background": "bg", "mockup": "mk"},
                gemini=gemini,
                remove_bg_client=remove_bg_client,
                design_bytes=b"raw-design",
            )

        assert (idea_folder / "background.txt").read_text(encoding="utf-8") == (
            "Sunlit porch with coffee mug"
        )
        assert (idea_folder / "buyer_personas.txt").read_text(encoding="utf-8") == (
            "Buyer Persona 1:\nOffice jokester\n\nBuyer Persona 2:\nWeekend griller"
        )
        assert (idea_folder / "beneficiary_personas.txt").read_text(
            encoding="utf-8"
        ) == (
            "Beneficiary Persona 1:\nNew dad\n\n"
            "Beneficiary Persona 2:\nRetired pun champion"
        )
        mockup_prompt_arg = gemini.generate_image.call_args.args[0]
        assert "Sunlit porch with coffee mug" in mockup_prompt_arg

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
        mockup_shirt_path = idea_folder / "lightBlue.png"
        mockup_shirt_path.write_bytes(b"mockup-base")

        default_mockup_path = idea_folder / "mockup_default_lightBlue.png"
        default_mockup_path.write_bytes(b"default-mockup")

        with (
            patch.object(
                generation.assets,
                "create_default_color_mockup",
                return_value=default_mockup_path,
            ) as mock_create_default,
            patch.object(
                generation.assets,
                "pick_mockup_shirt",
                return_value=mockup_shirt_path,
            ),
            patch.object(
                generation.assets,
                "crop_center_percent",
                return_value=None,
            ),
        ):
            _, mockup_path, mockup_cropped_path = (
                generation.assets.generate_post_design_assets(
                    idea=idea,
                    prompts={"background": "bg", "mockup": "mk"},
                    gemini=gemini,
                    remove_bg_client=remove_bg_client,
                    design_bytes=b"raw-design",
                )
            )

        mock_create_default.assert_called_once_with(
            design_path=idea_folder / "design_transparent.png",
            mockup_shirt=mockup_shirt_path,
            output_dir=idea.folder_path,
        )
        assert mockup_path.exists()
        assert mockup_cropped_path.name.endswith("_cropped.png")
        gemini.generate_image.assert_called_once()
        _, kwargs = gemini.generate_image.call_args
        assert kwargs["image_bytes"] == b"default-mockup"

    def test_raises_when_mockup_shirt_file_is_missing(self, tmp_path: Path):
        """Fails fast when shirt-selection returns a missing base mockup file."""
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
        remove_bg_client = MagicMock()
        remove_bg_client.remove_background.return_value = b"transparent"

        with (
            patch.object(
                generation.assets,
                "pick_mockup_shirt",
                return_value=idea_folder / "missing.png",
            ),
            pytest.raises(ValueError, match="Missing required file"),
        ):
            generation.assets.generate_post_design_assets(
                idea=idea,
                prompts={"background": "bg", "mockup": "mk"},
                gemini=MagicMock(),
                remove_bg_client=remove_bg_client,
                design_bytes=b"raw-design",
            )


class TestSaveFinalMockupImage:
    """Tests for persisting final mockups in the shared output folder."""

    def test_saves_to_all_final_mockups_with_slugified_idea_name(self, tmp_path: Path):
        """Writes the final cropped mockup bytes to the shared final-mockups directory."""
        idea = Idea(
            keyword="alpha",
            original_title="Alpha Shirt",
            title="Alpha Shirt 1",
            folder_name="Alpha_Shirt_1",
            folder_path=tmp_path / "Alpha_Shirt_1",
            payload={},
        )
        mockup_cropped_path = tmp_path / "mockup_(Light_Blue)_cropped.png"
        mockup_cropped_path.write_bytes(b"mockup-bytes")
        all_final_mockups_dir = tmp_path / "_all_final_mockups"

        with patch.object(
            constants,
            "ALL_FINAL_MOCKUPS_DIR",
            all_final_mockups_dir,
        ):
            destination_path = file_tools.io_utils.save_final_mockup_image(
                idea=idea,
                mockup_cropped_path=mockup_cropped_path,
            )

        assert destination_path == all_final_mockups_dir / "Alpha_Shirt_1.png"
        assert destination_path.exists()
        assert destination_path.read_bytes() == b"mockup-bytes"


class TestGenerateListingFields:
    """Tests for listing field generation."""

    def test_treats_description_response_as_plain_text(self, tmp_path: Path):
        """Uses the description model output directly instead of parsing personas from it."""
        idea_folder = tmp_path / "idea"
        idea_folder.mkdir(parents=True, exist_ok=True)
        idea = Idea(
            keyword="alpha",
            original_title="Alpha Shirt",
            title="Alpha Shirt 1",
            folder_name="Alpha_Shirt_1",
            folder_path=idea_folder,
            payload={"title": "Alpha Shirt 1"},
        )
        gemini = MagicMock()
        gemini.generate_text.side_effect = [
            "Listing Title",
            "A clean listing description.",
            "tag one, tag two, tag three",
        ]

        title, description, keywords = generation.listing.generate_listing_fields(
            idea=idea,
            prompts={
                "title": "title prompt",
                "description": "description prompt",
                "keywords": "keywords prompt",
                "default_description": "Default details.",
            },
            gemini=gemini,
        )

        assert title == "Listing Title"
        assert description == "A clean listing description.\n\nDefault details."
        assert keywords == ["tag one", "tag two", "tag three"]
        assert (idea_folder / "description.txt").read_text(encoding="utf-8") == (
            "A clean listing description.\n\nDefault details."
        )
        assert not (idea_folder / "buyer_personas.txt").exists()
        assert not (idea_folder / "beneficiary_personas.txt").exists()
