"""Background removal helpers for the mass production pipeline."""

from io import BytesIO
import time
from typing import Dict, Tuple

from PIL import Image
import requests

from logger_config import log_action


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
        threshold: int = 70  # Adjust this to catch the "static"
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
