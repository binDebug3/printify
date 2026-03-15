"""Tests for Etsy mockup sync helpers."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import add_etsy_mockup as etsy_mockup_module  # noqa: E402


class TestLoadEtsyConfig:
    """Tests for load_etsy_config."""

    def test_loads_expected_keys_from_json_payload(self, tmp_path):
        """Maps the normalized Etsy JSON keys into a typed config object."""
        config_path = tmp_path / "etsy_api_key.json"
        config_path.write_text(
            json.dumps(
                {
                    "keystring": "api-key",
                    "shared secret": "shared-secret",
                    "refresh token": "refresh-token",
                    "access token": "access-token",
                    "shop id": "12345",
                }
            ),
            encoding="utf-8",
        )

        config = etsy_mockup_module.load_etsy_config(config_path)

        assert config.api_key == "api-key"
        assert config.shared_secret == "shared-secret"
        assert config.refresh_token == "refresh-token"
        assert config.access_token == "access-token"
        assert config.shop_id == "12345"


class TestResolveMockupPath:
    """Tests for resolve_mockup_path."""

    def test_returns_matching_mockup_file_from_nickname_folder(self, tmp_path):
        """Finds the cropped mockup image inside the nickname folder."""
        folder = tmp_path / "Folder One"
        folder.mkdir()
        expected = folder / "mockup_(pepper)_cropped.png"
        expected.write_bytes(b"png")

        result = etsy_mockup_module.resolve_mockup_path(
            "Folder One", products_dir=tmp_path
        )

        assert result == expected


class TestEtsyClient:
    """Tests for EtsyClient."""

    def test_find_listing_id_by_title_returns_exact_match(self):
        """Finds the active Etsy listing with the exact title returned by Printify."""
        config = etsy_mockup_module.EtsyConfig(
            api_key="api-key",
            shared_secret="shared-secret",
            refresh_token="refresh-token",
            access_token="access-token",
            shop_id="12345",
        )
        client = etsy_mockup_module.EtsyClient(config)
        response = MagicMock()
        response.json.return_value = {
            "results": [
                {"listing_id": 10, "title": "Other Title"},
                {"listing_id": 11, "title": "Target Title"},
            ]
        }

        with patch.object(client, "_request", return_value=response):
            result = client.find_listing_id_by_title("Target Title")

        assert result == 11

    def test_upload_listing_image_posts_primary_rank(self, tmp_path):
        """Uploads the image with rank=1 when primary placement is requested."""
        image_path = tmp_path / "mockup_(pepper)_cropped.png"
        image_path.write_bytes(b"png")
        config = etsy_mockup_module.EtsyConfig(
            api_key="api-key",
            shared_secret="shared-secret",
            refresh_token="refresh-token",
            access_token="access-token",
            shop_id="12345",
        )
        client = etsy_mockup_module.EtsyClient(config)
        response = MagicMock()
        response.json.return_value = {"listing_image_id": 55}

        with patch.object(client, "_request", return_value=response) as mock_request:
            result = client.upload_listing_image(77, image_path, make_primary=True)

        assert result == {"listing_image_id": 55}
        assert mock_request.call_args.kwargs["data"] == {"rank": "1"}


class TestAddMockupsForPublishedProducts:
    """Tests for add_mockups_for_published_products."""

    def test_processes_published_products_and_uploads_mockups(self, tmp_path):
        """Resolves listing title and mockup path, then uploads one Etsy listing image."""
        folder = tmp_path / "Folder One"
        folder.mkdir()
        mockup_path = folder / "mockup_(pepper)_cropped.png"
        mockup_path.write_bytes(b"png")
        fake_client = MagicMock()
        fake_client.find_listing_id_by_title.return_value = 77

        with (
            patch.object(
                etsy_mockup_module,
                "load_etsy_config",
                return_value=etsy_mockup_module.EtsyConfig(
                    api_key="api-key",
                    shared_secret="shared-secret",
                    refresh_token="refresh-token",
                    access_token="access-token",
                    shop_id="12345",
                ),
            ),
            patch.object(etsy_mockup_module, "EtsyClient", return_value=fake_client),
            patch.object(
                etsy_mockup_module, "load_api_token", return_value="printify-token"
            ),
            patch.object(
                etsy_mockup_module,
                "fetch_printify_product_title",
                return_value="Resolved Listing Title",
            ),
        ):
            result = etsy_mockup_module.add_mockups_for_published_products(
                [{"product_id": "p1", "shop_id": "s1", "nick_name": "Folder One"}],
                products_dir=tmp_path,
            )

        assert result == {"processed": 1, "updated": 1, "failed": 0}
        fake_client.find_listing_id_by_title.assert_called_once_with(
            "Resolved Listing Title"
        )
        fake_client.upload_listing_image.assert_called_once_with(
            listing_id=77,
            image_path=mockup_path,
            make_primary=True,
        )
