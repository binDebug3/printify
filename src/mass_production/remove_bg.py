"""remove.bg API helper for background removal."""

import time
from typing import Dict, Tuple
import requests


class RemoveBgClient:
    """Client for remove.bg image background removal.

    Args:
        api_key: remove.bg API key.
        endpoint: remove.bg endpoint URL.
        retries: Maximum retries for transient failures.
    """

    def __init__(self, api_key: str, endpoint: str, retries: int = 2):
        self._api_key: str = api_key
        self._endpoint: str = endpoint
        self._retries: int = retries

    def remove_background(self, image_bytes: bytes) -> bytes:
        """Remove background from an image.

        Args:
            image_bytes: Source image bytes.

        Returns:
            PNG bytes with transparent background.

        Raises:
            RuntimeError: If all retries fail.
        """
        headers: Dict[str, str] = {"X-Api-Key": self._api_key}
        files: Dict[str, Tuple[str, bytes, str]] = {"image_file": 
                                                    ("design.png", image_bytes, "image/png")}
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
