"""Generate average shirt color hex values from base mockup PNG images."""

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, List, Tuple

from PIL import Image

try:
    from config.constants import DATA_DIR
    from schedule.logger_config import log_action
except ModuleNotFoundError:
    MODULE_PATH: Path = Path(__file__).resolve()
    MASS_PRODUCTION_ROOT: Path = MODULE_PATH.parents[1]
    SRC_ROOT: Path = MODULE_PATH.parents[2]
    for candidate in (SRC_ROOT, MASS_PRODUCTION_ROOT):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

    from config.constants import DATA_DIR
    from schedule.logger_config import log_action


CENTER_SAMPLE_SIZE: int = 7
DEFAULT_BASE_MOCKUPS_DIR: Path = DATA_DIR / "base_mockups"
DEFAULT_OUTPUT_PATH: Path = DEFAULT_BASE_MOCKUPS_DIR / "_shirt_colors.json"


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for shirt color extraction.

    Returns:
        Parsed command-line arguments.
    """
    log_action("Parsing CLI arguments for shirt color extraction")
    parser = argparse.ArgumentParser(
        description=(
            "Calculate the average hex color from the center 49 pixels of each "
            "base mockup PNG image."
        )
    )
    parser.add_argument(
        "--base-mockups-dir",
        type=Path,
        default=DEFAULT_BASE_MOCKUPS_DIR,
        help="Directory containing base mockup PNG files.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Destination JSON file for extracted shirt colors.",
    )
    return parser.parse_args()


def _get_center_region_bounds(
    image_size: Tuple[int, int],
    sample_size: int = CENTER_SAMPLE_SIZE,
) -> Tuple[int, int, int, int]:
    """Return the centered square bounds for sampling.

    Args:
        image_size: Source image width and height.
        sample_size: Width and height of the square sample.

    Returns:
        Left, top, right, and bottom bounds for the sample box.

    Raises:
        ValueError: If the image is smaller than the requested sample size.
    """
    log_action(
        f"Resolving centered {sample_size}x{sample_size} sample for image {image_size}"
    )
    width, height = image_size
    if width < sample_size or height < sample_size:
        raise ValueError(
            "Images must be at least "
            f"{sample_size}x{sample_size} pixels to extract center colors"
        )

    left: int = (width - sample_size) // 2
    top: int = (height - sample_size) // 2
    return left, top, left + sample_size, top + sample_size


def _average_center_rgb(
    image: Image.Image,
    sample_size: int = CENTER_SAMPLE_SIZE,
) -> Tuple[int, int, int]:
    """Average RGB values from the centered sample region.

    Args:
        image: Source image.
        sample_size: Width and height of the square sample.

    Returns:
        Averaged red, green, and blue channel values.

    Raises:
        RuntimeError: If image pixels cannot be loaded.
    """
    log_action(
        f"Averaging RGB values from the center {sample_size * sample_size} pixels"
    )
    rgba_image: Image.Image = image.convert("RGBA")
    left, top, right, bottom = _get_center_region_bounds(rgba_image.size, sample_size)
    pixels = rgba_image.load()
    if pixels is None:
        raise RuntimeError("Image pixels could not be loaded")

    total_red: int = 0
    total_green: int = 0
    total_blue: int = 0
    pixel_count: int = sample_size * sample_size

    for y_coord in range(top, bottom):
        for x_coord in range(left, right):
            pixel: Tuple[int, int, int, int] = pixels[x_coord, y_coord]  # type: ignore[assignment]
            red, green, blue, _alpha = pixel
            total_red += red
            total_green += green
            total_blue += blue

    return (
        round(total_red / pixel_count),
        round(total_green / pixel_count),
        round(total_blue / pixel_count),
    )


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """Convert an RGB tuple into a lowercase hex string.

    Args:
        rgb: Red, green, and blue channel values.

    Returns:
        Hex color string prefixed with #.
    """
    log_action(f"Converting averaged RGB value {rgb} to hex")
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _list_base_mockup_pngs(base_mockups_dir: Path) -> List[Path]:
    """List PNG images available for shirt color extraction.

    Args:
        base_mockups_dir: Directory containing mockup images.

    Returns:
        Sorted PNG file paths.

    Raises:
        FileNotFoundError: If the base mockups directory does not exist.
    """
    log_action(f"Listing base mockup PNG files in '{base_mockups_dir}'")
    if not base_mockups_dir.exists():
        raise FileNotFoundError(
            f"Base mockups directory does not exist: {base_mockups_dir}"
        )

    return sorted(path for path in base_mockups_dir.glob("*.png") if path.is_file())


def build_shirt_color_mapping(
    base_mockups_dir: Path = DEFAULT_BASE_MOCKUPS_DIR,
) -> Dict[str, str]:
    """Build a filename-to-hex-color mapping for base mockup PNGs.

    Args:
        base_mockups_dir: Directory containing mockup PNG files.

    Returns:
        Mapping of PNG filenames to averaged center hex colors.
    """
    log_action(f"Building shirt color mapping from '{base_mockups_dir}'")
    shirt_colors: Dict[str, str] = {}

    for png_path in _list_base_mockup_pngs(base_mockups_dir):
        with Image.open(png_path) as image:
            average_rgb: Tuple[int, int, int] = _average_center_rgb(image)
        shirt_colors[png_path.name] = _rgb_to_hex(average_rgb)

    log_action(f"Computed shirt colors for {len(shirt_colors)} base mockup PNG file(s)")
    return shirt_colors


def write_shirt_color_mapping(
    base_mockups_dir: Path = DEFAULT_BASE_MOCKUPS_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Write extracted shirt colors to a JSON file.

    Args:
        base_mockups_dir: Directory containing mockup PNG files.
        output_path: Destination JSON file path.

    Returns:
        Path to the written JSON file.
    """
    log_action(
        f"Writing shirt color mapping from '{base_mockups_dir}' to '{output_path}'"
    )
    shirt_colors = build_shirt_color_mapping(base_mockups_dir=base_mockups_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file_obj:
        json.dump(shirt_colors, file_obj, indent=2, ensure_ascii=True, sort_keys=True)
        file_obj.write("\n")

    log_action(f"Saved shirt color mapping JSON to '{output_path}'")
    return output_path


def main() -> None:
    """CLI entry point for shirt color extraction."""
    log_action("Running shirt_colors.py as a CLI tool")
    args = _parse_args()
    write_shirt_color_mapping(
        base_mockups_dir=args.base_mockups_dir,
        output_path=args.output_path,
    )


if __name__ == "__main__":
    main()
