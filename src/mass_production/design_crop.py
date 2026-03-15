"""Crop generated design images to their content bounds with configurable padding."""

from collections import Counter
import json
from io import BytesIO
import math
from pathlib import Path
import re
from typing import Optional

from PIL import Image
from logger_config import log_action


FOREGROUND_TOLERANCE: int = 10
BASE_MOCKUPS_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "base_mockups"


def crop_design_image_to_content(
    image_bytes: bytes,
    padding_percent: float = 0.05,
) -> bytes:
    """Crop a generated design image to its foreground bounding box.

    Args:
        image_bytes: Source image bytes.
        padding_percent: Fractional padding added around the detected content box.

    Returns:
        PNG bytes cropped to the detected content bounds plus padding.

    Raises:
        ValueError: If padding_percent is outside the range [0, 1).
    """
    log_action(
        f"Cropping generated design image to content bounds with padding={padding_percent:.2f}"
    )
    if padding_percent < 0 or padding_percent >= 1:
        raise ValueError("padding_percent must be >= 0 and < 1")

    with Image.open(BytesIO(image_bytes)) as image:
        rgba_image: Image.Image = image.convert("RGBA")
        bounding_box = _find_foreground_bounding_box(rgba_image)
        if bounding_box is None:
            log_action(
                "No foreground bounding box detected; keeping original design image"
            )
            return _image_to_png_bytes(rgba_image)

        padded_box = _expand_bounding_box(
            bounding_box=bounding_box,
            image_size=rgba_image.size,
            padding_percent=padding_percent,
        )
        if padded_box == (0, 0, rgba_image.width, rgba_image.height):
            log_action(
                "Detected content already fills the design image; no crop applied"
            )
            return _image_to_png_bytes(rgba_image)

        cropped_image: Image.Image = rgba_image.crop(padded_box)
        log_action(f"Applied design crop with bounding box {padded_box}")
        return _image_to_png_bytes(cropped_image)


def _find_foreground_bounding_box(
    image: Image.Image,
    tolerance: int = FOREGROUND_TOLERANCE,
) -> Optional[tuple[int, int, int, int]]:
    """Find the bounding box of non-background pixels.

    Args:
        image: RGBA image to inspect.
        tolerance: Maximum per-channel difference treated as background.

    Returns:
        Pillow-style bounding box tuple, or None when no foreground is found.
    """
    log_action(f"Finding foreground bounding box with tolerance={tolerance}")
    background_color = _detect_background_color(image)
    pixels = image.load()
    if pixels is None:
        log_action("Failed to load image pixels for foreground bounding box detection")
        raise RuntimeError("Image pixels could not be loaded")
    min_x: Optional[int] = None
    min_y: Optional[int] = None
    max_x: Optional[int] = None
    max_y: Optional[int] = None

    for y_coord in range(image.height):
        for x_coord in range(image.width):
            pixel: int = pixels[x_coord, y_coord]  # type: ignore[assignment]
            if _is_foreground_pixel(pixel, background_color, tolerance):  # type: ignore
                if min_x is None or x_coord < min_x:
                    min_x = x_coord
                if min_y is None or y_coord < min_y:
                    min_y = y_coord
                if max_x is None or x_coord > max_x:
                    max_x = x_coord
                if max_y is None or y_coord > max_y:
                    max_y = y_coord

    if None in {min_x, min_y, max_x, max_y}:
        return None
    return (min_x, min_y, max_x + 1, max_y + 1)  # type: ignore[assignment]


def _detect_background_color(image: Image.Image) -> tuple[int, int, int, int]:
    """Detect the dominant border color used as the background reference.

    Args:
        image: RGBA image to inspect.

    Returns:
        Dominant border RGBA color.
    """
    log_action("Detecting background color from design image border pixels")
    border_pixels: list[tuple[int, int, int, int]] = []
    pixels = image.load()

    for x_coord in range(image.width):
        border_pixels.append(pixels[x_coord, 0])  # type: ignore[assignment]
        border_pixels.append(pixels[x_coord, image.height - 1])  # type: ignore[assignment]
    for y_coord in range(image.height):
        border_pixels.append(pixels[0, y_coord])  # type: ignore[assignment]
        border_pixels.append(pixels[image.width - 1, y_coord])  # type: ignore[assignment]

    color_counts = Counter(border_pixels)
    return color_counts.most_common(1)[0][0]


def _is_foreground_pixel(
    pixel: tuple[int, int, int, int],
    background_color: tuple[int, int, int, int],
    tolerance: int,
) -> bool:
    """Determine whether a pixel differs enough from the background.

    Args:
        pixel: Pixel RGBA tuple to inspect.
        background_color: Reference border color.
        tolerance: Maximum per-channel difference treated as background.

    Returns:
        True when the pixel is part of the design foreground.
    """
    delta = max(
        abs(pixel[0] - background_color[0]),
        abs(pixel[1] - background_color[1]),
        abs(pixel[2] - background_color[2]),
        abs(pixel[3] - background_color[3]),
    )
    return delta > tolerance


def _expand_bounding_box(
    bounding_box: tuple[int, int, int, int],
    image_size: tuple[int, int],
    padding_percent: float,
) -> tuple[int, int, int, int]:
    """Expand a bounding box by a percentage of its width and height.

    Args:
        bounding_box: Pillow-style bounding box tuple.
        image_size: Original image width and height.
        padding_percent: Fractional padding applied to width and height.

    Returns:
        Expanded bounding box clamped to the image bounds.
    """
    log_action(
        f"Expanding bounding box {bounding_box} with padding={padding_percent:.2f}"
    )
    left, top, right, bottom = bounding_box
    image_width, image_height = image_size
    box_width = max(1, right - left)
    box_height = max(1, bottom - top)
    padding_x = int(math.ceil(box_width * padding_percent))
    padding_y = int(math.ceil(box_height * padding_percent))

    return (
        max(0, left - padding_x),
        max(0, top - padding_y),
        min(image_width, right + padding_x),
        min(image_height, bottom + padding_y),
    )


def _image_to_png_bytes(image: Image.Image) -> bytes:
    """Serialize an image to PNG bytes.

    Args:
        image: Pillow image to serialize.

    Returns:
        PNG bytes.
    """
    log_action("Serializing cropped design image to PNG bytes")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _to_camel_case(value: str) -> str:
    """Convert free-form color text to lower camelCase.

    Args:
        value: Input color text.

    Returns:
        Lower camelCase string.

    Raises:
        ValueError: If value has no alphanumeric tokens.
    """
    log_action(f"Converting color '{value}' to camelCase")
    tokens = re.findall(r"[A-Za-z0-9]+", value)
    if not tokens:
        raise ValueError("color must include at least one alphanumeric character")
    return tokens[0].lower() + "".join(token.capitalize() for token in tokens[1:])


def create_default_color_mockup(
    design_path: Path,
    color: str,
    output_dir: Path,
) -> Path:
    """Create a default color mockup by pasting a design into a saved bbox.

    This function loads a design image and a color-specific base mockup image,
    reads bbox coordinates from data/base_mockups/bbox.json using key `bbox`
    in xywh format, scales the design proportionally to fit within the bbox,
    and composites it onto the mockup.

    Args:
        design_path: Path to the design image.
        color: Shirt color name used to locate base mockup image.
        output_dir: Directory where the composed mockup is saved.

    Returns:
        Path to the saved composed image.

    Raises:
        FileNotFoundError: If design, base mockup, or bbox JSON is missing.
        ValueError: If bbox JSON is invalid.
    """
    log_action(
        f"Creating default mockup for color='{color}' from design='{design_path}'"
    )
    if not design_path.exists():
        raise FileNotFoundError(f"Design image not found: '{design_path}'")

    color_camel = _to_camel_case(color)

    mockup_dir_candidates = [
        BASE_MOCKUPS_DIR,
        BASE_MOCKUPS_DIR.parent / "base_mockup",
    ]
    mockup_path: Optional[Path] = None
    for candidate_dir in mockup_dir_candidates:
        candidate_path = candidate_dir / f"{color_camel}.png"
        if candidate_path.exists():
            mockup_path = candidate_path
            break

    if mockup_path is None:
        raise FileNotFoundError(
            f"No base mockup found for color='{color}' as '{color_camel}.png'"
        )

    bbox_path = BASE_MOCKUPS_DIR / "bbox.json"
    if not bbox_path.exists():
        raise FileNotFoundError(f"Bounding box file not found: '{bbox_path}'")

    with open(bbox_path, "r", encoding="utf-8") as file_obj:
        bbox_payload = json.load(file_obj)

    bbox = bbox_payload.get("bbox")
    if not isinstance(bbox, dict):
        raise ValueError("bbox.json must contain a 'bbox' object in xywh format")

    try:
        x_coord = int(bbox["x"])
        y_coord = int(bbox["y"])
        box_width = int(bbox["width"])
        box_height = int(bbox["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "bbox.json 'bbox' must include integer x, y, width, height"
        ) from exc

    if box_width <= 0 or box_height <= 0:
        raise ValueError("bbox width and height must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"mockup_default_{color_camel}.png"

    with (
        Image.open(mockup_path) as mockup_image,
        Image.open(design_path) as design_image,
    ):
        mockup_rgba: Image.Image = mockup_image.convert("RGBA")
        design_rgba: Image.Image = design_image.convert("RGBA")

        design_width, design_height = design_rgba.size
        scale_ratio = min(box_width / design_width, box_height / design_height)
        resized_width = max(1, int(round(design_width * scale_ratio)))
        resized_height = max(1, int(round(design_height * scale_ratio)))

        resized_design = design_rgba.resize(
            (resized_width, resized_height), Image.Resampling.LANCZOS
        )
        paste_x = x_coord + (box_width - resized_width) // 2
        paste_y = y_coord + (box_height - resized_height) // 2

        mockup_rgba.paste(resized_design, (paste_x, paste_y), resized_design)
        mockup_rgba.save(output_path, format="PNG")

    log_action(f"Saved color mockup to '{output_path}'")
    return output_path
