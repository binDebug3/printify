"""Tests for mass_production.post_dry_run helper functions."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import post_dry_run as post_dry_run_module  # noqa: E402


class TestPostDryRunHelpers:
    """Tests for post_dry_run helper behavior."""

    def test_find_color_mockup_cropped_returns_first_alphabetical_match(self, tmp_path):
        """Selects the first alphabetical cropped mockup when multiple color files exist."""
        (tmp_path / "mockup_(pepper)_cropped.png").write_bytes(b"png")
        expected = tmp_path / "mockup_(blue)_cropped.png"
        expected.write_bytes(b"png")

        result = post_dry_run_module._find_color_mockup_cropped(tmp_path)

        assert result == expected

    def test_load_keywords_reads_json_array(self, tmp_path):
        """Parses keywords.txt as a JSON array and strips empty values."""
        keywords_path = tmp_path / "keywords.txt"
        keywords_path.write_text(json.dumps(["alpha", "", "beta"]), encoding="utf-8")

        result = post_dry_run_module._load_keywords(keywords_path)

        assert result == ["alpha", "beta"]

    def test_load_keywords_aborts_on_invalid_json(self, tmp_path):
        """Stops with a user-facing abort when keywords.txt is not valid JSON."""
        keywords_path = tmp_path / "keywords.txt"
        keywords_path.write_text("not json", encoding="utf-8")

        with (
            patch.object(
                post_dry_run_module,
                "_abort",
                side_effect=SystemExit(1),
            ) as mock_abort,
            pytest.raises(SystemExit),
        ):
            post_dry_run_module._load_keywords(keywords_path)

        assert "not valid JSON array" in mock_abort.call_args.args[0]

    def test_load_color_to_ids_filters_invalid_entries(self):
        """Keeps only valid color entries with integer variant IDs."""
        payload = {
            "variants": [
                {"color": "pepper", "ids": [1, 2, "x"]},
                {"color": "", "ids": [3]},
                {"color": "blue", "ids": [4]},
            ]
        }

        with patch.object(post_dry_run_module, "read_json", return_value=payload):
            result = post_dry_run_module._load_color_to_ids(Path("variant_map.json"))

        assert result == {"pepper": [1, 2], "blue": [4]}

    def test_load_selected_colors_falls_back_to_all_valid_colors(self):
        """Returns all variant-map colors when ideas.json does not name any valid colors."""
        ideas_payload = [{"shirt_colors": ["invalid"]}]

        with patch.object(post_dry_run_module, "read_json", return_value=ideas_payload):
            result = post_dry_run_module._load_selected_colors(
                Path("ideas.json"), {"pepper": [1], "blue": [2]}
            )

        assert result == ["pepper", "blue"]

    def test_resolve_folder_aborts_with_closest_match_suggestion(self, tmp_path):
        """Suggests the closest existing folder name when the provided slug is missing."""
        (tmp_path / "Modern_Dad_Sneaker_Minimalist_1").mkdir()

        with (
            patch.object(post_dry_run_module.constants, "IMAGES_DIR", tmp_path),
            patch.object(
                post_dry_run_module, "_abort", side_effect=SystemExit(1)
            ) as mock_abort,
            pytest.raises(SystemExit),
        ):
            post_dry_run_module._resolve_folder("Modern_Dad_Sneker_Minimalist_1")

        assert (
            "Did you mean 'Modern_Dad_Sneaker_Minimalist_1'"
            in mock_abort.call_args.args[0]
        )
