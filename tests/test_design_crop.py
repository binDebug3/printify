"""Tests for automatic content-bounding-box cropping of generated designs."""

import sys
import json
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw


MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import photoshop.design_crop as design_crop_module  # noqa: E402


def _make_png_bytes(
    size: tuple[int, int],
    fill: tuple[int, int, int, int],
    rectangle: Optional[tuple[int, int, int, int]] = None,
) -> bytes:
    """Create a synthetic PNG image for cropping tests.

    Args:
        size: Image width and height.
        fill: Background RGBA color.
        rectangle: Optional foreground rectangle in Pillow coordinates.

    Returns:
        PNG bytes for the synthetic image.
    """
    image = Image.new("RGBA", size, fill)
    if rectangle is not None:
        draw = ImageDraw.Draw(image)
        draw.rectangle(rectangle, fill=(0, 0, 0, 255))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class TestCropDesignImageToContent:
    """Tests for cropping design images to their content bounds."""

    def test_crops_white_border_and_keeps_padding(self):
        """Shrinks whitespace while keeping a 5 percent border around the content."""
        image_bytes = _make_png_bytes(
            size=(100, 80),
            fill=(255, 255, 255, 255),
            rectangle=(30, 20, 69, 49),
        )

        cropped_bytes = design_crop_module.crop_design_image_to_content(image_bytes)

        with Image.open(BytesIO(cropped_bytes)) as cropped_image:
            assert cropped_image.size == (44, 34)

    def test_returns_original_size_when_content_fills_frame(self):
        """Leaves the image unchanged when the design already reaches the edges."""
        image_bytes = _make_png_bytes(
            size=(60, 60),
            fill=(255, 255, 255, 255),
            rectangle=(0, 0, 59, 59),
        )

        cropped_bytes = design_crop_module.crop_design_image_to_content(image_bytes)

        with Image.open(BytesIO(cropped_bytes)) as cropped_image:
            assert cropped_image.size == (60, 60)

    def test_supports_transparent_background_content_detection(self):
        """Finds the content box even when the background is transparent."""
        image_bytes = _make_png_bytes(
            size=(80, 70),
            fill=(255, 255, 255, 0),
            rectangle=(10, 15, 49, 44),
        )

        cropped_bytes = design_crop_module.crop_design_image_to_content(image_bytes)

        with Image.open(BytesIO(cropped_bytes)) as cropped_image:
            assert cropped_image.size == (44, 34)


class TestCreateDefaultColorMockup:
    """Tests for composing designs onto color base mockups using bbox.json."""

    def test_creates_output_mockup_with_bbox_paste(self, tmp_path: Path):
        """Pastes design into bbox and saves mockup_default_<color>.png output."""
        base_mockups_dir = tmp_path / "data" / "base_mockups"
        base_mockups_dir.mkdir(parents=True, exist_ok=True)
        mockup_path = base_mockups_dir / "lightBlue.png"
        design_path = tmp_path / "design.png"
        output_dir = tmp_path / "out"

        mockup = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
        mockup.save(mockup_path, format="PNG")

        design = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
        design.save(design_path, format="PNG")

        bbox_payload = {"bbox": {"x": 2, "y": 3, "width": 2, "height": 2}}
        with open(base_mockups_dir / "bbox.json", "w", encoding="utf-8") as file_obj:
            json.dump(bbox_payload, file_obj)

        original_base = design_crop_module.BASE_MOCKUPS_DIR
        design_crop_module.BASE_MOCKUPS_DIR = base_mockups_dir
        try:
            output_path = design_crop_module.create_default_color_mockup(
                design_path=design_path,
                color="Light Blue",
                output_dir=output_dir,
            )
        finally:
            design_crop_module.BASE_MOCKUPS_DIR = original_base

        assert output_path.name == "mockup_default_lightBlue.png"
        assert output_path.exists()

        with Image.open(output_path) as result:
            result_rgba = result.convert("RGBA")
            pasted_pixel = result_rgba.getpixel((2, 3))
            untouched_pixel = result_rgba.getpixel((0, 0))

        assert pasted_pixel == (255, 0, 0, 255)
        assert untouched_pixel == (255, 255, 255, 255)

    def test_preserves_design_aspect_ratio_inside_bbox(self, tmp_path: Path):
        """Scales proportionally so the design fits within bbox without stretching."""
        base_mockups_dir = tmp_path / "data" / "base_mockups"
        base_mockups_dir.mkdir(parents=True, exist_ok=True)
        mockup_path = base_mockups_dir / "lightBlue.png"
        design_path = tmp_path / "design.png"
        output_dir = tmp_path / "out"

        mockup = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
        mockup.save(mockup_path, format="PNG")

        design = Image.new("RGBA", (4, 2), (255, 0, 0, 255))
        design.save(design_path, format="PNG")

        bbox_payload = {"bbox": {"x": 2, "y": 2, "width": 4, "height": 4}}
        with open(base_mockups_dir / "bbox.json", "w", encoding="utf-8") as file_obj:
            json.dump(bbox_payload, file_obj)

        original_base = design_crop_module.BASE_MOCKUPS_DIR
        design_crop_module.BASE_MOCKUPS_DIR = base_mockups_dir
        try:
            output_path = design_crop_module.create_default_color_mockup(
                design_path=design_path,
                color="Light Blue",
                output_dir=output_dir,
            )
        finally:
            design_crop_module.BASE_MOCKUPS_DIR = original_base

        with Image.open(output_path) as result:
            result_rgba = result.convert("RGBA")

            # BBox top row should remain background because resized design is centered.
            assert result_rgba.getpixel((2, 2)) == (255, 255, 255, 255)
            assert result_rgba.getpixel((5, 2)) == (255, 255, 255, 255)

            # Design fills full bbox width but only half height (4x2), preserving 2:1 ratio.
            assert result_rgba.getpixel((2, 3)) == (255, 0, 0, 255)
            assert result_rgba.getpixel((5, 3)) == (255, 0, 0, 255)
            assert result_rgba.getpixel((2, 4)) == (255, 0, 0, 255)
            assert result_rgba.getpixel((5, 4)) == (255, 0, 0, 255)

            # BBox bottom row should remain background for the same reason.
            assert result_rgba.getpixel((2, 5)) == (255, 255, 255, 255)
            assert result_rgba.getpixel((5, 5)) == (255, 255, 255, 255)
