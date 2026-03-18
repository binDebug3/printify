"""Invert black and white values in an image from the command line.

The script accepts an optional image path argument. If no path is provided,
it opens a file picker dialog so the user can select an image interactively.
The inverted image is saved next to the original with "_inverted" appended
to the filename stem. If a color is provided with ``-c``/``--color``, the image
is filled with that color instead and saved with ``_<hexcode>`` appended.
"""

import argparse
import logging
from pathlib import Path
import sys
from typing import Optional

from PIL import Image
from PIL import ImageOps
from PIL import UnidentifiedImageError
import tkinter as tk
from tkinter import filedialog


DEFAULT_OUTPUT_SUFFIX: str = "_inverted"
DEFAULT_OUTPUT_EXTENSION: str = ".png"
FILE_DIALOG_TITLE: str = "Select an image to invert"
WHITE_HEX: str = "ffffff"
BLACK_HEX: str = "000000"
IMAGE_FILE_TYPES: list[tuple[str, str]] = [
    (
        "Image files",
        "*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff;*.webp;*.gif",
    ),
    ("All files", "*.*"),
]


LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    """
    Configure console logging for this script.

    Returns:
        None
    """
    if logging.getLogger().handlers:
        LOGGER.debug("Root logger already configured; reusing existing handlers")
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    LOGGER.info("Configured CLI logging")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """
    Parse command line arguments.

    Args:
        argv: Optional CLI argument list for testing.

    Returns:
        Parsed argument namespace.
    """
    LOGGER.info("Parsing command line arguments for invert script")
    parser = argparse.ArgumentParser(
        description=("Invert an image so black becomes white and white becomes black.")
    )
    parser.add_argument(
        "image_path",
        nargs="?",
        help="Path to the source image. If omitted, a file browser opens.",
    )
    parser.add_argument(
        "-c",
        "--color",
        help="Solid fill color: white, black, or hex (RRGGBB or #RRGGBB).",
    )
    return parser.parse_args(argv)


def normalize_hex_color(color_value: str) -> str:
    """
    Normalize CLI color input into a lowercase six-digit hex code.

    Args:
        color_value: Raw color value from CLI.

    Returns:
        Six-digit lowercase hex code without '#'.

    Raises:
        ValueError: If color is not white, black, or a valid six-digit hex code.
    """
    LOGGER.info("Normalizing color input: %s", color_value)
    lowered: str = color_value.strip().lower()
    if lowered == "white":
        return WHITE_HEX
    if lowered == "black":
        return BLACK_HEX

    normalized: str = lowered[1:] if lowered.startswith("#") else lowered
    if len(normalized) != 6 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(
            "Color must be 'white', 'black', or a hex value like 'ff00aa' or '#ff00aa'."
        )
    return normalized


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """
    Convert a six-digit hex code into an RGB tuple.

    Args:
        hex_color: Six-digit lowercase hex color without '#'.

    Returns:
        RGB tuple with integer channel values.
    """
    LOGGER.info("Converting hex color '%s' to RGB", hex_color)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def prompt_for_image_path() -> Optional[Path]:
    """
    Open a file picker so the user can choose an image.

    Returns:
        Selected image path, or None when selection is canceled or fails.
    """
    LOGGER.info("Opening file dialog to select an input image")
    root: Optional[tk.Tk] = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_path: str = filedialog.askopenfilename(
            title=FILE_DIALOG_TITLE,
            filetypes=IMAGE_FILE_TYPES,
        )
        if not selected_path:
            LOGGER.warning("File dialog was canceled; no image selected")
            return None
        return Path(selected_path)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Failed to open file dialog: %s", exc)
        return None
    finally:
        if root is not None:
            root.destroy()


def validate_image_path(image_path: Path) -> Path:
    """
    Validate and normalize an input image path.

    Args:
        image_path: Candidate path to validate.

    Returns:
        Resolved absolute image path.

    Raises:
        FileNotFoundError: If the path does not exist.
        IsADirectoryError: If the path points to a directory.
        PermissionError: If the file cannot be read.
    """
    LOGGER.info("Validating input image path: %s", image_path)
    expanded_path: Path = image_path.expanduser()
    resolved_path: Path = expanded_path.resolve()

    if not resolved_path.exists():
        raise FileNotFoundError(f"Input path does not exist: '{resolved_path}'")
    if not resolved_path.is_file():
        raise IsADirectoryError(f"Input path is not a file: '{resolved_path}'")
    if not resolved_path.stat().st_size:
        raise ValueError(f"Input image is empty: '{resolved_path}'")
    if not resolved_path.suffix:
        LOGGER.warning("Input file has no extension: %s", resolved_path)

    return resolved_path


def build_output_path(image_path: Path, suffix: str = DEFAULT_OUTPUT_SUFFIX) -> Path:
    """
    Build output path beside the input image.

    Args:
        image_path: Absolute source image path.

    Returns:
        Output path with the suffix appended to the stem.
    """
    LOGGER.info("Building output path for image: %s", image_path)
    output_extension: str = image_path.suffix or DEFAULT_OUTPUT_EXTENSION
    output_name: str = f"{image_path.stem}{suffix}{output_extension}"
    return image_path.with_name(output_name)


def invert_image(image: Image.Image) -> Image.Image:
    """
    Invert the image while preserving alpha transparency when present.

    Args:
        image: Loaded source image.

    Returns:
        Inverted image object.
    """
    LOGGER.info("Inverting image in mode '%s'", image.mode)
    if "A" in image.getbands():
        rgba_image: Image.Image = image.convert("RGBA")
        red, green, blue, alpha = rgba_image.split()
        inverted_rgb: Image.Image = ImageOps.invert(
            Image.merge("RGB", (red, green, blue))
        )
        inv_red, inv_green, inv_blue = inverted_rgb.split()
        return Image.merge("RGBA", (inv_red, inv_green, inv_blue, alpha))

    if image.mode == "1":
        inverted_l: Image.Image = ImageOps.invert(image.convert("L"))
        return inverted_l.convert("1")

    if image.mode in {"L", "RGB"}:
        return ImageOps.invert(image)

    return ImageOps.invert(image.convert("RGB"))


def fill_image(image: Image.Image, color_rgb: tuple[int, int, int]) -> Image.Image:
    """
    Fill the image with a solid RGB color while preserving alpha when present.

    Args:
        image: Loaded source image.
        color_rgb: RGB color channels.

    Returns:
        Solid color image object.
    """
    LOGGER.info("Filling image in mode '%s' with RGB color %s", image.mode, color_rgb)
    if "A" in image.getbands():
        alpha_channel: Image.Image = image.convert("RGBA").split()[3]
        fill_rgb: Image.Image = Image.new("RGB", image.size, color_rgb)
        red, green, blue = fill_rgb.split()
        return Image.merge("RGBA", (red, green, blue, alpha_channel))

    return Image.new("RGB", image.size, color_rgb)


def invert_image_file(
    input_path: Path,
    output_path: Path,
    fill_rgb_color: Optional[tuple[int, int, int]] = None,
) -> None:
    """
    Invert an input image file and save the output image.

    Args:
        input_path: Path to source image.
        output_path: Path where processed image is written.
        fill_rgb_color: Optional RGB color. When provided, image is filled.

    Returns:
        None

    Raises:
        UnidentifiedImageError: If input file is not a valid image.
        OSError: If image load/save fails.
    """
    LOGGER.info("Loading input image from: %s", input_path)
    with Image.open(input_path) as source_image:
        if fill_rgb_color is None:
            processed_image: Image.Image = invert_image(source_image)
            LOGGER.info("Saving inverted image to: %s", output_path)
        else:
            processed_image = fill_image(source_image, fill_rgb_color)
            LOGGER.info("Saving color-filled image to: %s", output_path)
        processed_image.save(output_path)


def main(argv: Optional[list[str]] = None) -> int:
    """
    Run the invert image command line workflow.

    Args:
        argv: Optional CLI argument list.

    Returns:
        Process exit code. Zero indicates success.
    """
    configure_logging()
    LOGGER.info("Starting invert image CLI")
    args = parse_args(argv)

    raw_image_path: Optional[Path] = Path(args.image_path) if args.image_path else None
    if raw_image_path is None:
        raw_image_path = prompt_for_image_path()
        if raw_image_path is None:
            LOGGER.error("No image selected. Nothing to process.")
            return 1

    try:
        fill_rgb_color: Optional[tuple[int, int, int]] = None
        output_suffix: str = DEFAULT_OUTPUT_SUFFIX
        if args.color:
            normalized_hex: str = normalize_hex_color(args.color)
            fill_rgb_color = hex_to_rgb(normalized_hex)
            output_suffix = f"_{normalized_hex}"

        input_path: Path = validate_image_path(raw_image_path)
        output_path: Path = build_output_path(input_path, suffix=output_suffix)
        invert_image_file(
            input_path=input_path,
            output_path=output_path,
            fill_rgb_color=fill_rgb_color,
        )
    except (FileNotFoundError, IsADirectoryError, PermissionError, ValueError) as exc:
        LOGGER.error("Input validation failed: %s", exc)
        return 1
    except UnidentifiedImageError:
        LOGGER.error("Input file is not a recognized image: %s", raw_image_path)
        return 1
    except OSError as exc:
        LOGGER.error("Image processing failed: %s", exc)
        return 1

    LOGGER.info("Inverted image created successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
