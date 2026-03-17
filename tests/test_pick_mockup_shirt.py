"""Tests for picking the best mockup shirt color for a design image."""

import json
from pathlib import Path
import sys

import pytest
from PIL import Image


MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import photoshop.pick_mockup_shirt as pick_shirt_module  # noqa: E402


def _save_solid_png(
    path: Path,
    size: tuple[int, int],
    fill: tuple[int, int, int, int],
) -> None:
    """Save a solid-color RGBA PNG image to disk.

    Args:
        path: Destination file path.
        size: Image width and height in pixels.
        fill: RGBA fill color tuple.
    """
    Image.new("RGBA", size, fill).save(path, format="PNG")


def _save_split_png(
    path: Path,
    size: tuple[int, int],
    left_fill: tuple[int, int, int, int],
    right_fill: tuple[int, int, int, int],
) -> None:
    """Save a PNG split vertically into two equal solid-color regions.

    Args:
        path: Destination file path.
        size: Image width and height.
        left_fill: RGBA fill for the left half.
        right_fill: RGBA fill for the right half.
    """
    image = Image.new("RGBA", size, left_fill)
    right_half = Image.new("RGBA", (size[0] // 2, size[1]), right_fill)
    image.paste(right_half, (size[0] // 2, 0))
    image.save(path, format="PNG")


def _write_shirt_colors_json(path: Path, selected: dict) -> None:
    """Write a minimal _shirt_colors.json with the given selected palette.

    Args:
        path: Destination JSON path.
        selected: Dict mapping shirt name to hex color.
    """
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump({"selected": selected}, file_obj)


class TestFindPredominantColors:
    """Tests for k-means color extraction from fully opaque pixels."""

    def test_uniform_image_returns_single_hex_value(self, tmp_path: Path):
        """All opaque pixels identical; every cluster converges to that color."""
        png_path = tmp_path / "design.png"
        _save_solid_png(png_path, (20, 20), (255, 0, 0, 255))

        colors = pick_shirt_module.find_predominant_colors(png_path)

        assert len(colors) >= 1
        assert all(h == "#ff0000" for h, _ in colors)

    def test_excludes_fully_transparent_pixels(self, tmp_path: Path):
        """Pixels with alpha=0 must not influence the extracted colors."""
        png_path = tmp_path / "design.png"
        _save_split_png(png_path, (20, 20), (255, 0, 0, 255), (0, 0, 255, 0))

        colors = pick_shirt_module.find_predominant_colors(png_path)

        assert all(h == "#ff0000" for h, _ in colors)
        assert "#0000ff" not in [h for h, _ in colors]

    def test_minor_cluster_dropped_below_coverage_threshold(self, tmp_path: Path):
        """A cluster covering less than 10 % of opaque pixels should be excluded."""
        png_path = tmp_path / "design.png"
        image = Image.new("RGBA", (100, 10), (255, 0, 0, 255))
        image.paste(Image.new("RGBA", (5, 10), (0, 0, 255, 255)), (95, 0))
        image.save(png_path, format="PNG")

        colors = pick_shirt_module.find_predominant_colors(png_path)

        assert "#0000ff" not in [h for h, _ in colors]

    def test_raises_for_fully_transparent_image(self, tmp_path: Path):
        """ValueError expected when every pixel is transparent."""
        png_path = tmp_path / "transparent.png"
        _save_solid_png(png_path, (10, 10), (255, 0, 0, 0))

        with pytest.raises(ValueError, match="No fully opaque pixels"):
            pick_shirt_module.find_predominant_colors(png_path)

    def test_coverage_fractions_sum_at_most_one(self, tmp_path: Path):
        """Returned coverage fractions must not exceed 1.0 in total."""
        png_path = tmp_path / "design.png"
        _save_solid_png(png_path, (30, 30), (100, 150, 200, 255))

        colors = pick_shirt_module.find_predominant_colors(png_path)

        total_coverage = sum(cov for _, cov in colors)
        assert total_coverage <= 1.0 + 1e-6


class TestRankShirtColors:
    """Tests for harmony-aware ranking with dark-on-dark exclusion."""

    def test_dark_shirt_excluded_for_dark_design(self):
        """A dark shirt must not be chosen when the design is also dark."""
        design_colors = [("#1e1e1e", 1.0)]
        shirt_colors = {"black": "#1e1e1e", "white": "#eeeeee"}

        result = pick_shirt_module.rank_shirt_colors(design_colors, shirt_colors)

        assert result == "white"

    def test_analogous_darker_blue_beats_neutral_for_light_blue_design(self):
        """A light blue design should prefer a darker analogous blue over white."""
        design_colors = [("#cde1ea", 1.0)]
        shirt_colors = {"white": "#eeeeee", "navy": "#1d314a"}

        result = pick_shirt_module.rank_shirt_colors(design_colors, shirt_colors)

        assert result == "navy"

    def test_blue_green_design_prefers_blue_over_warm_contrast(self):
        """A blue-green design should prefer a neighboring cool hue over a warm shirt."""
        design_colors = [("#63a09b", 1.0)]
        shirt_colors = {"brick": "#825155", "navy": "#1d314a", "ivory": "#f2e9da"}

        result = pick_shirt_module.rank_shirt_colors(design_colors, shirt_colors)

        assert result == "navy"

    def test_near_identical_blue_is_penalized_against_darker_tonal_match(self):
        """A same-value blue shirt should lose to a darker blue tonal pairing."""
        design_colors = [("#cde1ea", 1.0)]
        shirt_colors = {"chambray": "#cde1ea", "navy": "#1d314a"}

        result = pick_shirt_module.rank_shirt_colors(design_colors, shirt_colors)

        assert result == "navy"

    def test_light_red_design_prefers_black_over_green_or_white(self):
        """Light red designs should prefer dark neutral shirts over green or white."""
        design_colors = [("#f77091", 1.0)]
        shirt_colors = {
            "black": "#1e1e1e",
            "bay": "#a4b1a0",
            "white": "#eeeeee",
        }

        result = pick_shirt_module.rank_shirt_colors(design_colors, shirt_colors)

        assert result == "black"

    def test_dark_red_design_prefers_white_or_light_red(self):
        """Dark red designs should favor white or light red over black and green."""
        design_colors = [("#8c3f47", 1.0)]
        shirt_colors = {
            "black": "#1e1e1e",
            "bay": "#a4b1a0",
            "white": "#eeeeee",
            "blossom": "#ecc5ca",
        }

        result = pick_shirt_module.rank_shirt_colors(design_colors, shirt_colors)

        assert result in {"white", "blossom"}

    def test_raises_when_all_candidates_are_dark_on_dark(self):
        """ValueError expected when the filter exhausts all shirt options."""
        design_colors = [("#000000", 1.0)]
        shirt_colors = {"black": "#000000", "graphite": "#4b494a"}

        with pytest.raises(ValueError, match="No valid shirt color candidates"):
            pick_shirt_module.rank_shirt_colors(design_colors, shirt_colors)

    def test_weighted_by_coverage_fraction(self):
        """Dominant cluster coverage should pull the score toward that color."""
        design_colors = [("#000000", 0.99), ("#ffffff", 0.01)]
        shirt_colors = {"white": "#eeeeee", "navy": "#1d314a"}

        # Design is mostly black (dark); navy is dark and gets filtered.
        # Only white survives.
        result = pick_shirt_module.rank_shirt_colors(design_colors, shirt_colors)

        assert result == "white"


class TestPickMockupShirt:
    """Integration tests for the full shirt picking pipeline."""

    def test_returns_path_to_best_harmony_aware_mockup(self, tmp_path: Path):
        """A light blue design should resolve to a darker analogous navy mockup."""
        design_path = tmp_path / "design.png"
        _save_solid_png(design_path, (20, 20), (205, 225, 234, 255))

        (tmp_path / "white.png").touch()
        (tmp_path / "navy.png").touch()
        colors_path = tmp_path / "_shirt_colors.json"
        _write_shirt_colors_json(colors_path, {"white": "#eeeeee", "navy": "#1d314a"})

        original_base = pick_shirt_module.BASE_MOCKUPS_DIR
        original_colors = pick_shirt_module.SHIRT_COLORS_PATH
        pick_shirt_module.BASE_MOCKUPS_DIR = tmp_path
        pick_shirt_module.SHIRT_COLORS_PATH = colors_path
        try:
            result = pick_shirt_module.pick_mockup_shirt(design_path)
        finally:
            pick_shirt_module.BASE_MOCKUPS_DIR = original_base
            pick_shirt_module.SHIRT_COLORS_PATH = original_colors

        assert result.name == "navy.png"
        assert result.exists()

    def test_raises_when_mockup_png_missing(self, tmp_path: Path):
        """FileNotFoundError expected when the chosen color has no PNG on disk."""
        design_path = tmp_path / "design.png"
        _save_solid_png(design_path, (10, 10), (255, 255, 255, 255))

        colors_path = tmp_path / "_shirt_colors.json"
        _write_shirt_colors_json(colors_path, {"navy": "#1d314a"})
        # Intentionally omit navy.png

        original_base = pick_shirt_module.BASE_MOCKUPS_DIR
        original_colors = pick_shirt_module.SHIRT_COLORS_PATH
        pick_shirt_module.BASE_MOCKUPS_DIR = tmp_path
        pick_shirt_module.SHIRT_COLORS_PATH = colors_path
        try:
            with pytest.raises(FileNotFoundError, match="navy"):
                pick_shirt_module.pick_mockup_shirt(design_path)
        finally:
            pick_shirt_module.BASE_MOCKUPS_DIR = original_base
            pick_shirt_module.SHIRT_COLORS_PATH = original_colors
