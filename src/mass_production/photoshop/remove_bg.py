"""Background removal helpers for the mass production pipeline."""

import argparse
from io import BytesIO
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from PIL import Image
from PIL import ImageFilter
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
        smart_matte_start: Start threshold for smart alpha ramp.
        smart_matte_end: End threshold for smart alpha ramp.
        smart_feather_radius: Gaussian blur radius for edge feathering.
        smart_edge_alpha_min: Lower bound alpha used during edge decontamination.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        retries: int = 2,
        removal_mode: str = "api",
        smart_matte_start: float = 14.0,
        smart_matte_end: float = 95.0,
        smart_feather_radius: float = 1.1,
        smart_edge_alpha_min: float = 0.08,
    ):
        self._api_key: str = api_key
        self._endpoint: str = endpoint
        self._retries: int = retries
        self._removal_mode: str = removal_mode.strip().lower()
        self._smart_matte_start: float = smart_matte_start
        self._smart_matte_end: float = smart_matte_end
        self._smart_feather_radius: float = smart_feather_radius
        self._smart_edge_alpha_min: float = smart_edge_alpha_min

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
        if self._removal_mode == "smart":
            return self._remove_background_smart(image_bytes)
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

    def _remove_background_smart(self, image_bytes: bytes) -> bytes:
        """Create a soft alpha matte for white/black backgrounds with cleaner edges.

        This mode assumes the dominant background is black or white, estimates which
        one is present from border pixels, and then computes a smooth per-pixel alpha
        based on color distance from that background. It also feathers the transition
        band and decontaminates edge colors to reduce dark/bright halos.

        Args:
            image_bytes: Source image bytes.

        Returns:
            PNG bytes with refined transparency.
        """
        log_action("Running smart background removal with soft matte")
        rgba_image: Image.Image = Image.open(BytesIO(image_bytes)).convert("RGBA")
        rgba_array: np.ndarray = np.asarray(rgba_image, dtype=np.uint8)
        rgb_array: np.ndarray = rgba_array[..., :3].astype(np.float32)
        source_alpha: np.ndarray = rgba_array[..., 3].astype(np.float32) / 255.0

        background_rgb: np.ndarray = self._estimate_background_color_from_border(
            rgb_array=rgb_array
        )
        color_distance: np.ndarray = np.linalg.norm(
            rgb_array - background_rgb.reshape((1, 1, 3)),
            axis=2,
        )

        # Distances below matte_start are treated as background, above matte_end
        # as foreground, with a smooth gradient in-between.
        matte_start: float = float(self._smart_matte_start)
        matte_end: float = float(self._smart_matte_end)
        alpha_matte: np.ndarray = np.clip(
            (color_distance - matte_start) / (matte_end - matte_start),
            0.0,
            1.0,
        )

        matte_image: Image.Image = Image.fromarray(
            (alpha_matte * 255.0).astype(np.uint8),
            mode="L",
        )
        blurred_matte_raw: np.ndarray = np.asarray(
            matte_image.filter(
                ImageFilter.GaussianBlur(radius=float(self._smart_feather_radius))
            ),
            dtype=np.float32,
        )
        blurred_matte: np.ndarray = blurred_matte_raw / 255.0

        transition_band: np.ndarray = (alpha_matte > 0.0) & (alpha_matte < 1.0)
        alpha_matte[transition_band] = blurred_matte[transition_band]

        final_alpha: np.ndarray = np.clip(alpha_matte * source_alpha, 0.0, 1.0)
        cleaned_rgb: np.ndarray = rgb_array.copy()

        edge_band: np.ndarray = (final_alpha > 0.02) & (final_alpha < 0.98)
        if bool(np.any(edge_band)):
            safe_alpha: np.ndarray = np.clip(
                final_alpha[edge_band],
                float(self._smart_edge_alpha_min),
                1.0,
            )
            foreground_rgb: np.ndarray = rgb_array[edge_band]
            background_contribution: np.ndarray = (
                1.0 - safe_alpha[:, np.newaxis]
            ) * background_rgb[np.newaxis, :]
            cleaned_rgb[edge_band] = (
                foreground_rgb - background_contribution
            ) / safe_alpha[:, np.newaxis]

        output_rgba: np.ndarray = np.empty_like(rgba_array)
        output_rgba[..., :3] = np.clip(cleaned_rgb, 0.0, 255.0).astype(np.uint8)
        output_rgba[..., 3] = (final_alpha * 255.0).astype(np.uint8)

        output_image: Image.Image = Image.fromarray(output_rgba, mode="RGBA")
        output_buffer = BytesIO()
        output_image.save(output_buffer, format="PNG")
        return output_buffer.getvalue()

    def _estimate_background_color_from_border(
        self,
        rgb_array: np.ndarray,
    ) -> np.ndarray:
        """Estimate whether border background is closer to black or white.

        Args:
            rgb_array: Source RGB array of shape (H, W, 3).

        Returns:
            RGB vector for estimated background color.
        """
        top_row: np.ndarray = rgb_array[0, :, :]
        bottom_row: np.ndarray = rgb_array[-1, :, :]
        left_col: np.ndarray = rgb_array[:, 0, :]
        right_col: np.ndarray = rgb_array[:, -1, :]
        border_pixels: np.ndarray = np.vstack(
            [top_row, bottom_row, left_col, right_col]
        )

        white_distance: np.ndarray = np.linalg.norm(255.0 - border_pixels, axis=1)
        black_distance: np.ndarray = np.linalg.norm(border_pixels, axis=1)

        white_vote_ratio: float = float(np.mean(white_distance <= black_distance))
        if white_vote_ratio >= 0.5:
            white_vote_pct: float = white_vote_ratio * 100.0
            log_action(
                "Smart background removal selected white background "
                f"({white_vote_pct:.1f}% border vote)"
            )
            return np.array([255.0, 255.0, 255.0], dtype=np.float32)

        black_vote_pct: float = (1.0 - white_vote_ratio) * 100.0
        log_action(
            "Smart background removal selected black background "
            f"({black_vote_pct:.1f}% border vote)"
        )
        return np.array([0.0, 0.0, 0.0], dtype=np.float32)

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


def calculate_transparent_pixel_ratio(image_bytes: bytes) -> float:
    """Calculate what portion of an RGBA image is fully transparent.

    Args:
        image_bytes: PNG or other image bytes to inspect.

    Returns:
        Ratio of pixels whose alpha channel is 0.0-1.0.
    """
    log_action("Calculating transparent pixel ratio for background removal result")
    with Image.open(BytesIO(image_bytes)) as image_obj:
        rgba_image: Image.Image = image_obj.convert("RGBA")
        alpha_channel = rgba_image.getchannel("A")
        total_pixels: int = rgba_image.width * rgba_image.height
        transparent_pixels: int = sum(
            1 for alpha_value in alpha_channel.getdata() if alpha_value == 0
        )

    return transparent_pixels / float(max(1, total_pixels))


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
