"""Tests for extracting average shirt colors from base mockup PNG files."""

import json
from pathlib import Path
import sys

from PIL import Image


MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import photoshop.shirt_colors as shirt_colors_module  # noqa: E402


def _save_mockup(
    path: Path, size: tuple[int, int], center_rgb: tuple[int, int, int]
) -> None:
    """Create a PNG with a center 7x7 square in the requested RGB color.

    Args:
        path: Destination PNG path.
        size: Full image width and height.
        center_rgb: RGB fill for the centered 7x7 region.
    """
    image = Image.new("RGBA", size, (0, 0, 0, 255))
    center_patch = Image.new("RGBA", (7, 7), center_rgb + (255,))
    left = (size[0] - 7) // 2
    top = (size[1] - 7) // 2
    image.paste(center_patch, (left, top))
    image.save(path, format="PNG")


class TestBuildShirtColorMapping:
    """Tests for building filename-to-hex shirt color mappings."""

    def test_uses_only_the_center_49_pixels(self, tmp_path: Path):
        """Ignores border pixels and averages the centered 7x7 sample."""
        image_path = tmp_path / "pepper.png"
        _save_mockup(image_path, size=(9, 9), center_rgb=(18, 52, 86))

        shirt_colors = shirt_colors_module.build_shirt_color_mapping(tmp_path)

        assert shirt_colors == {"pepper.png": "#123456"}

    def test_writes_json_with_png_filenames_as_keys(self, tmp_path: Path):
        """Persists extracted colors into the requested JSON output file."""
        _save_mockup(tmp_path / "black.png", size=(11, 11), center_rgb=(0, 0, 0))
        _save_mockup(tmp_path / "white.png", size=(11, 11), center_rgb=(255, 255, 255))
        output_path = tmp_path / "_shirt_colors.json"

        written_path = shirt_colors_module.write_shirt_color_mapping(
            base_mockups_dir=tmp_path,
            output_path=output_path,
        )

        with open(written_path, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)

        assert written_path == output_path
        assert payload == {
            "black.png": "#000000",
            "white.png": "#ffffff",
        }
