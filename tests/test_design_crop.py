"""Tests for automatic content-bounding-box cropping of generated designs."""

import sys
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

import design_crop as design_crop_module  # noqa: E402


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
