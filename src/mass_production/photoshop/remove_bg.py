"""Background removal helpers for the mass production pipeline."""

import argparse
from io import BytesIO
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

from PIL import Image
import requests

try:
    from schedule.logger_config import log_action
except ModuleNotFoundError:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from schedule.logger_config import log_action


class RemoveBgClient:
    """Client for image background removal.

    Args:
        api_key: remove.bg API key.
        endpoint: remove.bg endpoint URL.
        retries: Maximum retries for transient failures.
        removal_mode: Background removal mode, either "api" or "manual".
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        retries: int = 2,
        removal_mode: str = "api",
    ):
        self._api_key: str = api_key
        self._endpoint: str = endpoint
        self._retries: int = retries
        self._removal_mode: str = removal_mode.strip().lower()

    def remove_background(self, image_bytes: bytes) -> bytes:
        """Remove background from an image.

        Args:
            image_bytes: Source image bytes.

        Returns:
            PNG bytes with transparent background.

        Raises:
            RuntimeError: If all retries fail.
        """
        log_action(f"Removing background using mode '{self._removal_mode}'")
        if self._removal_mode == "api":
            return self._remove_background_via_api(image_bytes)
        if self._removal_mode == "manual":
            return self._remove_background_manually(image_bytes)
        raise ValueError(f"Unsupported background removal mode '{self._removal_mode}'")

    def _remove_background_via_api(self, image_bytes: bytes) -> bytes:
        """Remove image background through the remove.bg API.

        Args:
            image_bytes: Source image bytes.

        Returns:
            PNG bytes returned by remove.bg.
        """
        log_action("Calling remove.bg API for background removal")
        headers: Dict[str, str] = {"X-Api-Key": self._api_key}
        files: Dict[str, Tuple[str, bytes, str]] = {
            "image_file": ("design.png", image_bytes, "image/png")
        }
        data: Dict[str, str] = {"size": "auto"}

        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = requests.post(
                    self._endpoint,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60,
                )
                if response.status_code == 200:
                    return response.content
                raise RuntimeError(
                    f"remove.bg failed with status {response.status_code}: {response.text}"
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self._retries - 1:
                    time.sleep(1 + attempt)
                    continue
                raise

        raise RuntimeError(f"remove.bg failed: {last_error}")

    def _remove_background_manually(self, image_bytes: bytes) -> bytes:
        """Remove either pure white or pure black pixels, whichever is more common.

        Args:
            image_bytes: Source image bytes.

        Returns:
            PNG bytes with the selected background color made transparent.
        """
        log_action("Trying manual background removal for white and black pixels")
        image: Image.Image = Image.open(BytesIO(image_bytes)).convert("RGBA")
        white_bytes, white_removed = self._make_color_transparent(
            image=image,
            target_rgb=(255, 255, 255),
        )
        black_bytes, black_removed = self._make_color_transparent(
            image=image,
            target_rgb=(0, 0, 0),
        )

        if white_removed >= black_removed:
            log_action(
                f"Manual background removal selected white pixels ({white_removed} transparent)"
            )
            return white_bytes

        log_action(
            f"Manual background removal selected black pixels ({black_removed} transparent)"
        )
        return black_bytes

    def _make_color_transparent(
        self,
        image: Image.Image,
        target_rgb: tuple[int, int, int],
        threshold: int = 80,  # Adjust this to catch the "static"
    ) -> tuple[bytes, int]:

        # Ensure image is in RGBA mode to support transparency
        output_image = image.convert("RGBA")
        data = output_image.getdata()

        new_data = []
        transparent_count = 0

        for item in data:  # type: ignore
            # Calculate the Euclidean distance between colors
            # item[0]=R, item[1]=G, item[2]=B
            dist = sum((a - b) ** 2 for a, b in zip(item[:3], target_rgb)) ** 0.5

            if dist < threshold:
                # Match found within threshold: set Alpha to 0
                new_data.append((item[0], item[1], item[2], 0))
                transparent_count += 1
            else:
                new_data.append(item)

        output_image.putdata(new_data)

        output_buffer = BytesIO()
        output_image.save(output_buffer, format="PNG")
        return output_buffer.getvalue(), transparent_count


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for manual background removal.

    Returns:
        Parsed command-line arguments.
    """
    log_action("Parsing CLI arguments for remove_bg manual execution")
    parser = argparse.ArgumentParser(
        description=(
            "Manually remove background from a PNG and replace the matching "
            "design*cropped.png in the same folder."
        )
    )
    parser.add_argument(
        "image_path",
        type=Path,
        help="Path to a source PNG image.",
    )
    return parser.parse_args()


def _resolve_output_path(source_path: Path) -> Path:
    """Resolve which design*cropped.png file should be replaced.

    Args:
        source_path: Source PNG path passed from CLI.

    Returns:
        Target output path to be overwritten.

    Raises:
        FileNotFoundError: If no design*cropped.png exists in the source folder.
    """
    log_action(f"Resolving output path for source image '{source_path}'")
    matching_paths = sorted(source_path.parent.glob("design*cropped.png"))

    if source_path.name.startswith("design") and source_path.name.endswith(
        "cropped.png"
    ):
        return source_path

    if not matching_paths:
        raise FileNotFoundError(
            "No output target found. Expected a file matching "
            f"'design*cropped.png' in '{source_path.parent}'."
        )

    return matching_paths[0]


def _run_manual_cli(image_path: Path) -> Path:
    """Run manual background removal from CLI and overwrite target image.

    Args:
        image_path: Source PNG image path.

    Returns:
        Path of the overwritten output image.

    Raises:
        FileNotFoundError: If source image does not exist or no cropped target exists.
        ValueError: If source file is not a PNG.
    """
    log_action(f"Starting CLI manual background removal for '{image_path}'")
    if not image_path.exists():
        raise FileNotFoundError(f"Source image does not exist: {image_path}")
    if image_path.suffix.lower() != ".png":
        raise ValueError(f"Expected a .png file, got: {image_path.name}")

    output_path = _resolve_output_path(source_path=image_path)
    source_bytes = image_path.read_bytes()

    client = RemoveBgClient(
        api_key="",
        endpoint="",
        retries=1,
        removal_mode="manual",
    )
    processed_bytes = client.remove_background(source_bytes)
    output_path.write_bytes(processed_bytes)
    log_action(f"Manual background removal saved to '{output_path}'")
    print(f"Saved manual background-removed image to: {output_path}")
    return output_path


def main() -> None:
    """CLI entry point for manual background removal."""
    log_action("Running remove_bg.py as a CLI tool")
    args = _parse_args()
    _run_manual_cli(image_path=args.image_path)


if __name__ == "__main__":
    main()
