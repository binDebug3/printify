"""Tests for mass_production client helpers."""

from io import BytesIO
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import clients.gemini_client as gemini_module  # noqa: E402
import clients.printify_client as printify_module  # noqa: E402
import photoshop.remove_bg as remove_bg_module  # noqa: E402


class TestPrintifyClient:
    """Tests for PrintifyClient."""

    def _make_client(self, dry_run: bool = False, retries: int = 2):
        """Return a PrintifyClient configured with simple deterministic values."""
        return printify_module.PrintifyClient(
            token="token",
            shop_id="shop",
            blueprint_id=706,
            print_provider_id=99,
            size_order=["S", "M", "L"],
            size_surcharge_usd={"L": 2.0},
            print_x=0.5,
            print_y=0.2,
            print_scale=0.65,
            min_price_usd=9.99,
            dry_run=dry_run,
            retries=retries,
        )

    def test_build_payload_creates_variants_and_uses_source_image_for_dry_upload(
        self, tmp_path
    ):
        """Builds variant pricing and includes a local source image when no upload ID exists."""
        client = self._make_client()
        design_path = tmp_path / "design_transparent.png"
        design_path.write_bytes(b"png")

        payload = client.build_payload(
            title="Test Title",
            description="Test Description",
            tags=["comfort colors", "Tag One", "tag one", "Way Too Long Tag For Etsy"],
            selected_colors=["pepper"],
            color_to_ids={"pepper": [1, 2, 3]},
            design_transparent_path=design_path,
            uploaded_image_id=None,
            base_price_usd=20.0,
        )

        assert payload["title"] == "Test Title"
        assert [variant["id"] for variant in payload["variants"]] == [1, 2, 3]
        assert [variant["price"] for variant in payload["variants"]] == [
            2000,
            2000,
            2200,
        ]
        image_entry = payload["print_areas"][0]["placeholders"][0]["images"][0]
        assert image_entry["id"] == "DRY_RUN_IMAGE_ID"
        assert image_entry["source_image_path"] == str(design_path)
        assert payload["tags"] == ["Tag One", "Way Too Long Tag For"]

    def test_upload_image_returns_placeholder_in_dry_run(self, tmp_path):
        """Skips network upload and returns a placeholder object when dry_run is enabled."""
        client = self._make_client(dry_run=True)
        image_path = tmp_path / "shirt.png"
        image_path.write_bytes(b"png")

        result = client.upload_image(image_path)

        assert result["dry_run"] is True
        assert result["id"] == "DRY_RUN_IMAGE_ID"
        assert result["file_name"] == "shirt.png"

    def test_create_product_retries_until_success(self):
        """Retries transient failures and returns the successful JSON payload."""
        client = self._make_client(dry_run=False, retries=3)
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"id": "prod-1"}

        with patch.object(
            printify_module.requests,
            "post",
            side_effect=[RuntimeError("temporary"), response],
        ) as mock_post:
            result = client.create_product({"title": "Listing"})

        assert result == {"id": "prod-1"}
        assert mock_post.call_count == 2

    def test_update_product_metadata_returns_stub_in_dry_run(self):
        """Skips network metadata updates when dry_run is enabled."""
        client = self._make_client(dry_run=True)

        result = client.update_product_metadata("prod-1", ["tag"], free_shipping=True)

        assert result == {"dry_run": True, "product_id": "prod-1"}

    def test_set_default_mockup_image_returns_stub_in_dry_run(self):
        """Skips default mockup updates when dry_run is enabled."""
        client = self._make_client(dry_run=True)

        result = client.set_default_mockup_image("prod-1", "img-1", [1, 2, 3])

        assert result == {
            "dry_run": True,
            "product_id": "prod-1",
            "mockup_image_id": "img-1",
        }


class TestGeminiClient:
    """Tests for GeminiClient."""

    def test_generate_text_uses_response_text_when_present(self):
        """Returns stripped response.text directly when the SDK populates it."""
        sdk_client = MagicMock()
        sdk_client.models.generate_content.return_value = SimpleNamespace(
            text="  hello world  "
        )

        with patch.object(gemini_module.genai, "Client", return_value=sdk_client):
            client = gemini_module.GeminiClient("key", "text-model", "image-model")
            result = client.generate_text("prompt")

        assert result == "hello world"

    def test_generate_text_falls_back_to_candidate_parts(self):
        """Reads text from candidate parts when response.text is empty."""
        response = SimpleNamespace(
            text=None,
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[SimpleNamespace(text="  fallback text  ")]
                    )
                )
            ],
        )
        sdk_client = MagicMock()
        sdk_client.models.generate_content.return_value = response

        with patch.object(gemini_module.genai, "Client", return_value=sdk_client):
            client = gemini_module.GeminiClient("key", "text-model", "image-model")
            result = client.generate_text("prompt")

        assert result == "fallback text"

    def test_generate_image_uses_conditioning_image_and_extracts_bytes(self):
        """Builds multimodal content when an input image is supplied and returns image bytes."""
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(
                                inline_data=SimpleNamespace(data=b"img-bytes")
                            )
                        ]
                    )
                )
            ]
        )
        sdk_client = MagicMock()
        sdk_client.models.generate_content.return_value = response

        with (
            patch.object(gemini_module.genai, "Client", return_value=sdk_client),
            patch.object(
                gemini_module.types.Part, "from_bytes", return_value="IMAGE_PART"
            ) as mock_from_bytes,
        ):
            client = gemini_module.GeminiClient("key", "text-model", "image-model")
            result = client.generate_image("prompt", image_bytes=b"seed")

        assert result == b"img-bytes"
        mock_from_bytes.assert_called_once_with(data=b"seed", mime_type="image/png")
        call_kwargs = sdk_client.models.generate_content.call_args.kwargs
        assert call_kwargs["contents"] == ["IMAGE_PART", "prompt"]


class TestRemoveBgClient:
    """Tests for RemoveBgClient."""

    def test_remove_background_returns_response_content_on_success(self):
        """Returns PNG bytes when remove.bg responds with HTTP 200."""
        response = MagicMock(status_code=200, content=b"transparent")
        client = remove_bg_module.RemoveBgClient("key", "https://remove.bg", retries=2)

        with patch.object(remove_bg_module.requests, "post", return_value=response):
            result = client.remove_background(b"image-bytes")

        assert result == b"transparent"

    def test_remove_background_retries_and_raises_last_error(self):
        """Retries failed responses and surfaces the final error after exhausting attempts."""
        bad_response = MagicMock(status_code=500, text="server error")
        client = remove_bg_module.RemoveBgClient("key", "https://remove.bg", retries=2)

        with (
            patch.object(
                remove_bg_module.requests,
                "post",
                return_value=bad_response,
            ),
            pytest.raises(RuntimeError, match="remove.bg failed with status 500"),
        ):
            client.remove_background(b"image-bytes")

    def test_remove_background_manual_mode_prefers_white_when_it_removes_more(self):
        """Uses white-pixel transparency when it removes more pixels than black."""
        client = remove_bg_module.RemoveBgClient(
            "key",
            "https://remove.bg",
            retries=2,
            removal_mode="manual",
        )
        image = Image.new("RGBA", (2, 2))
        image.putdata(
            [
                (255, 255, 255, 255),
                (255, 255, 255, 255),
                (0, 0, 0, 255),
                (20, 20, 20, 255),
            ]
        )
        input_buffer = BytesIO()
        image.save(input_buffer, format="PNG")

        result = client.remove_background(input_buffer.getvalue())

        output_image = Image.open(BytesIO(result)).convert("RGBA")
        assert list(output_image.getdata())[:3] == [
            (255, 255, 255, 0),
            (255, 255, 255, 0),
            (0, 0, 0, 255),
        ]

    def test_remove_background_manual_mode_prefers_black_when_it_removes_more(self):
        """Uses black-pixel transparency when it removes more pixels than white."""
        client = remove_bg_module.RemoveBgClient(
            "key",
            "https://remove.bg",
            retries=2,
            removal_mode="manual",
        )
        image = Image.new("RGBA", (2, 2))
        image.putdata(
            [
                (0, 0, 0, 255),
                (0, 0, 0, 255),
                (0, 0, 0, 255),
                (255, 255, 255, 255),
            ]
        )
        input_buffer = BytesIO()
        image.save(input_buffer, format="PNG")

        result = client.remove_background(input_buffer.getvalue())

        output_image = Image.open(BytesIO(result)).convert("RGBA")
        assert list(output_image.getdata()) == [
            (0, 0, 0, 0),
            (0, 0, 0, 0),
            (0, 0, 0, 0),
            (255, 255, 255, 255),
        ]
