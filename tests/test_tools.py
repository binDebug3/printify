"""Tests for tools.py.

Covers load_api_token, load_shop_id, publish_product, get_all_products,
and get_all_product_ids without hitting the filesystem or the Printify API.
"""

from unittest.mock import patch, MagicMock, mock_open
import pytest
import requests

from src.tools import (
    load_api_token,
    load_shop_id,
    publish_product,
    get_all_products,
    get_all_product_ids,
)


SHOP_ID = "shop-123"
PRODUCT_ID = "prod-456"
TOKEN = "test-token-abc"


class TestLoadApiToken:
    """Tests for load_api_token."""

    def test_reads_and_strips_token(self, tmp_path):
        """Returns the token stripped of leading and trailing whitespace."""
        token_file = tmp_path / "api_token.txt"
        token_file.write_text("  my-secret-token\n", encoding="utf-8")

        assert load_api_token(str(token_file)) == "my-secret-token"

    def test_uses_default_path_when_none(self):
        """Opens ../meta/api_token.txt when filepath is not provided."""
        with patch("builtins.open", mock_open(read_data="default-token")) as mock_file:
            result = load_api_token()

        mock_file.assert_called_once_with("../meta/api_token.txt", "r", encoding="utf-8")
        assert result == "default-token"

    def test_raises_file_not_found_for_missing_file(self):
        """Raises FileNotFoundError when the given filepath does not exist."""
        with pytest.raises(FileNotFoundError):
            load_api_token("/nonexistent/path/to/token.txt")


class TestLoadShopId:
    """Tests for load_shop_id."""

    def test_reads_and_strips_shop_id(self):
        """Returns the shop ID stripped of whitespace."""
        with patch("builtins.open", mock_open(read_data="  shop-999\n")):
            result = load_shop_id()

        assert result == "shop-999"

    def test_reads_from_expected_path(self):
        """Opens ../meta/shop_id.txt."""
        with patch("builtins.open", mock_open(read_data="shop-abc")) as mock_file:
            load_shop_id()

        mock_file.assert_called_once_with("../meta/shop_id.txt", "r", encoding="utf-8")


class TestPublishProduct:
    """Tests for publish_product."""

    def test_posts_to_correct_endpoint(self):
        """Sends a POST request to the Printify publish URL for the given product."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.post", return_value=mock_resp) as mock_post:
            publish_product(PRODUCT_ID, shop_id=SHOP_ID, token=TOKEN)

        expected_url = (
            f"https://api.printify.com/v1/shops/{SHOP_ID}" f"/products/{PRODUCT_ID}/publish.json"
        )
        assert mock_post.call_args[0][0] == expected_url

    def test_bearer_token_in_auth_header(self):
        """Authorization header contains the correct Bearer token."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.post", return_value=mock_resp) as mock_post:
            publish_product(PRODUCT_ID, shop_id=SHOP_ID, token=TOKEN)

        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == f"Bearer {TOKEN}"

    def test_payload_contains_all_sync_flags(self):
        """All expected sync fields are present and set to True in the POST payload."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.post", return_value=mock_resp) as mock_post:
            publish_product(PRODUCT_ID, shop_id=SHOP_ID, token=TOKEN)

        payload = mock_post.call_args[1]["json"]
        expected_keys = {
            "title",
            "description",
            "images",
            "variants",
            "tags",
            "keyFeatures",
            "shipping_template",
        }
        assert set(payload.keys()) == expected_keys
        assert all(v is True for v in payload.values())

    def test_returns_response_object(self):
        """Returns the response object from requests.post."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.post", return_value=mock_resp):
            result = publish_product(PRODUCT_ID, shop_id=SHOP_ID, token=TOKEN)

        assert result is mock_resp

    def test_loads_shop_id_when_not_provided(self):
        """Calls load_shop_id when shop_id is None."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.post", return_value=mock_resp), patch(
            "src.tools.load_shop_id", return_value=SHOP_ID
        ) as mock_load:
            publish_product(PRODUCT_ID, token=TOKEN)

        mock_load.assert_called_once()

    def test_loads_token_when_not_provided(self):
        """Calls load_api_token when token is None."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.post", return_value=mock_resp), patch(
            "src.tools.load_api_token", return_value=TOKEN
        ) as mock_load:
            publish_product(PRODUCT_ID, shop_id=SHOP_ID)

        mock_load.assert_called_once()


class TestGetAllProducts:
    """Tests for get_all_products."""

    def test_gets_from_correct_endpoint(self):
        """Sends a GET request to the Printify products URL for the given shop."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.get", return_value=mock_resp) as mock_get:
            get_all_products(shop_id=SHOP_ID, token=TOKEN)

        expected_url = f"https://api.printify.com/v1/shops/{SHOP_ID}/products.json"
        assert mock_get.call_args[0][0] == expected_url

    def test_returns_response_object(self):
        """Returns the response object from requests.get."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.get", return_value=mock_resp):
            result = get_all_products(shop_id=SHOP_ID, token=TOKEN)

        assert result is mock_resp

    def test_re_raises_read_timeout(self):
        """Propagates ReadTimeout raised by requests.get."""
        with patch("src.tools.requests.get", side_effect=requests.exceptions.ReadTimeout):
            with pytest.raises(requests.exceptions.ReadTimeout):
                get_all_products(shop_id=SHOP_ID, token=TOKEN)

    def test_loads_shop_id_when_not_provided(self):
        """Calls load_shop_id when shop_id is None."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.get", return_value=mock_resp), patch(
            "src.tools.load_shop_id", return_value=SHOP_ID
        ) as mock_load:
            get_all_products(token=TOKEN)

        mock_load.assert_called_once()

    def test_loads_token_when_not_provided(self):
        """Calls load_api_token when token is None."""
        mock_resp = MagicMock(status_code=200)
        with patch("src.tools.requests.get", return_value=mock_resp), patch(
            "src.tools.load_api_token", return_value=TOKEN
        ) as mock_load:
            get_all_products(shop_id=SHOP_ID)

        mock_load.assert_called_once()


class TestGetAllProductIds:
    """Tests for get_all_product_ids."""

    def _mock_response(self, products: list) -> MagicMock:
        """Return a mock 200 response whose .json() contains the given products."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"data": products}
        return mock_resp

    def test_returns_title_id_tuples(self, tmp_path):
        """Returns a list of (title, id) tuples for each product."""
        mock_resp = self._mock_response(
            [
                {"title": "Shirt A", "id": "id-1"},
                {"title": "Shirt B", "id": "id-2"},
            ]
        )
        output_file = str(tmp_path / "product_ids.txt")
        with patch("src.tools.get_all_products", return_value=mock_resp):
            result = get_all_product_ids(output_path=output_file, shop_id=SHOP_ID, token=TOKEN)

        assert result == [("Shirt A", "id-1"), ("Shirt B", "id-2")]

    def test_writes_one_line_per_product(self, tmp_path):
        """Writes one CSV-formatted line per product to the output file."""
        mock_resp = self._mock_response([{"title": "Shirt A", "id": "id-1"}])
        output_file = tmp_path / "product_ids.txt"
        with patch("src.tools.get_all_products", return_value=mock_resp):
            get_all_product_ids(output_path=str(output_file), shop_id=SHOP_ID, token=TOKEN)

        contents = output_file.read_text(encoding="utf-8")
        assert f"Shirt A,id-1,{SHOP_ID}," in contents

    def test_raises_value_error_on_api_failure(self, tmp_path):
        """Raises ValueError when the API returns a non-200 status code."""
        mock_resp = MagicMock(status_code=404, text="Not Found")
        output_file = str(tmp_path / "product_ids.txt")
        with patch("src.tools.get_all_products", return_value=mock_resp):
            with pytest.raises(ValueError, match="404"):
                get_all_product_ids(output_path=output_file, shop_id=SHOP_ID, token=TOKEN)
