"""Gemini API wrapper for text and image generation."""

import time
from typing import Optional

from google import genai
from google.genai import types


class GeminiClient:
    """Thin client around the Google GenAI SDK.

    Args:
        api_key: Gemini API key from environment.
        text_model: Model name for text outputs.
        image_model: Model name for image outputs.
        retries: Maximum attempts for transient failures.
    """

    def __init__(self, api_key: str, text_model: str, image_model: str, retries: int = 3):
        self._client = genai.Client(api_key=api_key)
        self._text_model = text_model
        self._image_model = image_model
        self._retries = retries

    def generate_text(self, prompt: str) -> str:
        """Generate text content from a prompt.

        Args:
            prompt: Input prompt string.

        Returns:
            Model text response.

        Raises:
            RuntimeError: If no text content is returned.
        """
        last_error: Optional[Exception] = None
        for attempt in range(self._retries):
            try:
                response = self._client.models.generate_content(
                    model=self._text_model,
                    contents=prompt,
                )
                text = getattr(response, "text", None)
                if text:
                    return text.strip()

                for candidate in getattr(response, "candidates", []) or []:
                    content = getattr(candidate, "content", None)
                    for part in getattr(content, "parts", []) or []:
                        part_text = getattr(part, "text", None)
                        if part_text:
                            return part_text.strip()
                raise RuntimeError("Gemini returned no text")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self._retries - 1:
                    time.sleep(1 + attempt)
                    continue
                raise

        raise RuntimeError(f"Gemini text generation failed: {last_error}")

    def generate_image(self, prompt: str, image_bytes: bytes | None = None) -> bytes:
        """Generate an image from prompt, optionally conditioned on an input image.

        Args:
            prompt: Input prompt string.
            image_bytes: Optional PNG/JPEG bytes for image-conditioned generation.

        Returns:
            Generated image bytes.

        Raises:
            RuntimeError: If no image data is returned.
        """
        if image_bytes is None:
            contents = prompt
        else:
            contents = [
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                prompt,
            ]

        last_error: Optional[Exception] = None
        for attempt in range(self._retries):
            try:
                response = self._client.models.generate_content(
                    model=self._image_model,
                    contents=contents,
                    config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
                )
                image_data = self._extract_image_bytes(response)
                if image_data:
                    return image_data
                raise RuntimeError("Gemini returned no image data")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self._retries - 1:
                    time.sleep(1 + attempt)
                    continue
                raise

        raise RuntimeError(f"Gemini image generation failed: {last_error}")

    @staticmethod
    def _extract_image_bytes(response: object) -> bytes | None:
        """Extract image bytes from a Gemini SDK response.

        Args:
            response: Raw SDK response object.

        Returns:
            First image bytes found, else None.
        """
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                inline_data = getattr(part, "inline_data", None)
                if inline_data is None:
                    continue
                data = getattr(inline_data, "data", None)
                if data:
                    return data
        return None
