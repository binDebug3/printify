"""Tests for shared and extracted Printify API modules."""

import argparse

from unittest.mock import patch, MagicMock, mock_open
import sys
import pytest
import requests

from src.printify_api_tools.get_product_info import (
    get_all_product_ids,
    get_all_products,
    main as product_info_main,
    parse_args as product_info_parse_args,
)
from src.printify_api_tools.get_variant_info import (
    COMFORT_COLORS_BLUEPRINT_ID,
    COMFORT_COLORS_PRINT_PROVIDER_ID,
    get_printify_variant_ids,
    main as variant_info_main,
    parse_args as variant_info_parse_args,
    parse_variant_ids,
)
from src.printify_api_tools.publish_product import (
    main as publish_product_main,
    parse_args as publish_product_parse_args,
    publish_product,
)
from src.tools import (
    load_api_token,
    load_shop_id,
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

        mock_file.assert_called_once_with(
            "../meta/api_token.txt", "r", encoding="utf-8"
        )
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
        with patch(
            "src.printify_api_tools.publish_product.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            publish_product(PRODUCT_ID, shop_id=SHOP_ID, token=TOKEN)

        expected_url = (
            f"https://api.printify.com/v1/shops/{SHOP_ID}"
            f"/products/{PRODUCT_ID}/publish.json"
        )
        assert mock_post.call_args[0][0] == expected_url

    def test_bearer_token_in_auth_header(self):
        """Authorization header contains the correct Bearer token."""
        mock_resp = MagicMock(status_code=200)
        with patch(
            "src.printify_api_tools.publish_product.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            publish_product(PRODUCT_ID, shop_id=SHOP_ID, token=TOKEN)

        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == f"Bearer {TOKEN}"

    def test_payload_contains_all_sync_flags(self):
        """All expected sync fields are present and set to True in the POST payload."""
        mock_resp = MagicMock(status_code=200)
        with patch(
            "src.printify_api_tools.publish_product.requests.post",
            return_value=mock_resp,
        ) as mock_post:
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
        with patch(
            "src.printify_api_tools.publish_product.requests.post",
            return_value=mock_resp,
        ):
            result = publish_product(PRODUCT_ID, shop_id=SHOP_ID, token=TOKEN)

        assert result is mock_resp

    def test_loads_shop_id_when_not_provided(self):
        """Calls load_shop_id when shop_id is None."""
        mock_resp = MagicMock(status_code=200)
        with (
            patch(
                "src.printify_api_tools.publish_product.requests.post",
                return_value=mock_resp,
            ),
            patch(
                "src.printify_api_tools.publish_product.load_shop_id",
                return_value=SHOP_ID,
            ) as mock_load,
        ):
            publish_product(PRODUCT_ID, token=TOKEN)

        mock_load.assert_called_once()

    def test_loads_token_when_not_provided(self):
        """Calls load_api_token when token is None."""
        mock_resp = MagicMock(status_code=200)
        with (
            patch(
                "src.printify_api_tools.publish_product.requests.post",
                return_value=mock_resp,
            ),
            patch(
                "src.printify_api_tools.publish_product.load_api_token",
                return_value=TOKEN,
            ) as mock_load,
        ):
            publish_product(PRODUCT_ID, shop_id=SHOP_ID)

        mock_load.assert_called_once()


class TestGetAllProducts:
    """Tests for get_all_products."""

    def test_gets_from_correct_endpoint(self):
        """Sends a GET request to the Printify products URL for the given shop."""
        mock_resp = MagicMock(status_code=200)
        with patch(
            "src.printify_api_tools.get_product_info.requests.get",
            return_value=mock_resp,
        ) as mock_get:
            get_all_products(shop_id=SHOP_ID, token=TOKEN)

        expected_url = f"https://api.printify.com/v1/shops/{SHOP_ID}/products.json"
        assert mock_get.call_args[0][0] == expected_url

    def test_returns_response_object(self):
        """Returns the response object from requests.get."""
        mock_resp = MagicMock(status_code=200)
        with patch(
            "src.printify_api_tools.get_product_info.requests.get",
            return_value=mock_resp,
        ):
            result = get_all_products(shop_id=SHOP_ID, token=TOKEN)

        assert result is mock_resp

    def test_re_raises_read_timeout(self):
        """Propagates ReadTimeout raised by requests.get."""
        with patch(
            "src.printify_api_tools.get_product_info.requests.get",
            side_effect=requests.exceptions.ReadTimeout,
        ):
            with pytest.raises(requests.exceptions.ReadTimeout):
                get_all_products(shop_id=SHOP_ID, token=TOKEN)

    def test_loads_shop_id_when_not_provided(self):
        """Calls load_shop_id when shop_id is None."""
        mock_resp = MagicMock(status_code=200)
        with (
            patch(
                "src.printify_api_tools.get_product_info.requests.get",
                return_value=mock_resp,
            ),
            patch(
                "src.printify_api_tools.get_product_info.load_shop_id",
                return_value=SHOP_ID,
            ) as mock_load,
        ):
            get_all_products(token=TOKEN)

        mock_load.assert_called_once()

    def test_loads_token_when_not_provided(self):
        """Calls load_api_token when token is None."""
        mock_resp = MagicMock(status_code=200)
        with (
            patch(
                "src.printify_api_tools.get_product_info.requests.get",
                return_value=mock_resp,
            ),
            patch(
                "src.printify_api_tools.get_product_info.load_api_token",
                return_value=TOKEN,
            ) as mock_load,
        ):
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
        with patch(
            "src.printify_api_tools.get_product_info.get_all_products",
            return_value=mock_resp,
        ):
            result = get_all_product_ids(
                output_path=output_file, shop_id=SHOP_ID, token=TOKEN
            )

        assert result == [("Shirt A", "id-1"), ("Shirt B", "id-2")]

    def test_writes_one_line_per_product(self, tmp_path):
        """Writes one CSV-formatted line per product to the output file."""
        mock_resp = self._mock_response([{"title": "Shirt A", "id": "id-1"}])
        output_file = tmp_path / "product_ids.txt"
        with patch(
            "src.printify_api_tools.get_product_info.get_all_products",
            return_value=mock_resp,
        ):
            get_all_product_ids(
                output_path=str(output_file), shop_id=SHOP_ID, token=TOKEN
            )

        contents = output_file.read_text(encoding="utf-8")
        assert f"Shirt A,id-1,{SHOP_ID}," in contents

    def test_raises_value_error_on_api_failure(self, tmp_path):
        """Raises ValueError when the API returns a non-200 status code."""
        mock_resp = MagicMock(status_code=404, text="Not Found")
        output_file = str(tmp_path / "product_ids.txt")
        with patch(
            "src.printify_api_tools.get_product_info.get_all_products",
            return_value=mock_resp,
        ):
            with pytest.raises(ValueError, match="404"):
                get_all_product_ids(
                    output_path=output_file, shop_id=SHOP_ID, token=TOKEN
                )

    def test_fetches_multiple_pages_when_available(self, tmp_path):
        """Continues fetching pages until the API reports the last page."""
        first_page = MagicMock(status_code=200)
        first_page.json.return_value = {
            "current_page": 1,
            "last_page": 2,
            "data": [{"title": "Shirt A", "id": "id-1"}],
        }
        second_page = MagicMock(status_code=200)
        second_page.json.return_value = {
            "current_page": 2,
            "last_page": 2,
            "data": [{"title": "Shirt B", "id": "id-2"}],
        }

        output_file = str(tmp_path / "product_ids.txt")
        with patch(
            "src.printify_api_tools.get_product_info.get_all_products",
            side_effect=[first_page, second_page],
        ):
            result = get_all_product_ids(
                output_path=output_file, shop_id=SHOP_ID, token=TOKEN
            )

        assert result == [("Shirt A", "id-1"), ("Shirt B", "id-2")]


class TestParseVariantIds:
    """Tests for parse_variant_ids."""

    def test_returns_nested_color_size_mapping_and_writes_json(self, tmp_path):
        """Creates the ids payload shape and persists it to the requested file."""
        output_file = tmp_path / "nested" / "variant_map.json"
        data = {
            "variants": [
                {"id": 101, "options": {"color": "Red", "size": "M"}},
                {"id": 102, "options": {"color": "Red", "size": "L"}},
                {"id": 201, "options": {"color": "Blue", "size": "S"}},
            ]
        }

        result = parse_variant_ids(data, str(output_file))

        assert result == {
            "variants": [
                {"color": "Red", "ids": [101, 102]},
                {"color": "Blue", "ids": [201]},
            ]
        }
        assert output_file.exists()
        assert output_file.read_text(encoding="utf-8")

    def test_skips_variants_missing_color_or_size(self, tmp_path):
        """Ignores incomplete variants instead of adding partial keys to the mapping."""
        output_file = tmp_path / "variant_map.json"
        data = {
            "variants": [
                {"id": 101, "options": {"color": "Red", "size": "M"}},
                {"id": 102, "options": {"color": "Red"}},
                {"id": 103, "options": {"size": "L"}},
                {"id": 104, "options": {}},
            ]
        }

        result = parse_variant_ids(data, str(output_file))

        assert result == {"variants": [{"color": "Red", "ids": [101]}]}


class TestGetPrintifyVariantIds:
    """Tests for get_printify_variant_ids."""

    def test_uses_defaults_and_passes_response_data_to_parser(self, tmp_path):
        """Uses default IDs and delegates response parsing to parse_variant_ids."""
        output_file = str(tmp_path / "variant_map.json")
        response = MagicMock(status_code=200)
        response.json.return_value = {"variants": [{"id": 1, "options": {}}]}
        parsed_map = {"variants": [{"color": "Red", "ids": [1]}]}

        with (
            patch(
                "src.printify_api_tools.get_variant_info.load_api_token",
                return_value=TOKEN,
            ),
            patch(
                "src.printify_api_tools.get_variant_info.requests.get",
                return_value=response,
            ) as mock_get,
            patch(
                "src.printify_api_tools.get_variant_info.parse_variant_ids",
                return_value=parsed_map,
            ) as mock_parse,
        ):
            result = get_printify_variant_ids(output_path=output_file)

        expected_url = (
            "https://api.printify.com/v1/catalog/blueprints/"
            f"{COMFORT_COLORS_BLUEPRINT_ID}/print_providers/"
            f"{COMFORT_COLORS_PRINT_PROVIDER_ID}/variants.json"
        )
        assert result == parsed_map
        assert mock_get.call_args[0][0] == expected_url
        assert mock_get.call_args[1]["headers"]["Authorization"] == f"Bearer {TOKEN}"
        mock_parse.assert_called_once_with(response.json.return_value, output_file)

    def test_raises_value_error_when_api_returns_non_200(self, tmp_path):
        """Raises ValueError with response details when the variants API fails."""
        output_file = str(tmp_path / "variant_map.json")
        response = MagicMock(status_code=500, text="server error")

        with patch(
            "src.printify_api_tools.get_variant_info.requests.get",
            return_value=response,
        ):
            with pytest.raises(ValueError, match="Failed to retrieve variants: 500"):
                get_printify_variant_ids(
                    output_path=output_file,
                    print_provider_id=1,
                    blueprint_id=2,
                    token=TOKEN,
                )

    def test_re_raises_request_exception(self, tmp_path):
        """Propagates request-layer failures from requests.get."""
        output_file = str(tmp_path / "variant_map.json")

        with patch(
            "src.printify_api_tools.get_variant_info.requests.get",
            side_effect=requests.exceptions.RequestException("boom"),
        ):
            with pytest.raises(requests.exceptions.RequestException, match="boom"):
                get_printify_variant_ids(
                    output_path=output_file,
                    print_provider_id=1,
                    blueprint_id=2,
                    token=TOKEN,
                )


class TestCliParseArgs:
    """Tests for CLI argument parsing in extracted modules."""

    def test_publish_product_parse_args_reads_product_id(self):
        """Parses the required product id argument for the publish CLI."""
        with patch.object(sys, "argv", ["publish_product.py", PRODUCT_ID]):
            args = publish_product_parse_args()

        assert args.product_id == PRODUCT_ID
        assert args.shop_id is None

    def test_product_info_parse_args_defaults_to_raw_products(self):
        """Leaves list_ids disabled when no flag is provided."""
        with patch.object(sys, "argv", ["get_product_info.py"]):
            args = product_info_parse_args()

        assert args.list_ids is False
        assert args.output_path == "../data/product_ids.txt"

    def test_variant_info_parse_args_uses_defaults(self):
        """Uses the default variant output path when no flags are provided."""
        with patch.object(sys, "argv", ["get_variant_info.py"]):
            args = variant_info_parse_args()

        assert args.output_path == "../data/variant_map.json"
        assert args.print_provider_id is None


class TestCliMain:
    """Tests for CLI entry points in extracted modules."""

    def test_variant_main_prints_lookup_result(self):
        """Executes the variant lookup CLI and pretty-prints the result."""
        args = argparse.Namespace(
            output_path="../data/variant_map.json",
            print_provider_id=None,
            blueprint_id=None,
            token_file=None,
        )
        variant_map = {"variants": [{"color": "Red", "ids": [101]}]}

        with (
            patch(
                "src.printify_api_tools.get_variant_info.parse_args",
                return_value=args,
            ),
            patch(
                "src.printify_api_tools.get_variant_info.get_printify_variant_ids",
                return_value=variant_map,
            ) as mock_get_variants,
            patch("src.printify_api_tools.get_variant_info.pprint") as mock_pprint,
        ):
            variant_info_main()

        mock_get_variants.assert_called_once_with(
            output_path="../data/variant_map.json",
            print_provider_id=None,
            blueprint_id=None,
            token=None,
        )
        mock_pprint.assert_called_once_with(variant_map)

    def test_product_info_main_exits_with_status_one_on_error(self):
        """Exits with code 1 when the product info CLI raises an exception."""
        args = argparse.Namespace(
            list_ids=False,
            shop_id=None,
            token_file=None,
            page=None,
            limit=None,
            output_path="../data/product_ids.txt",
        )

        with (
            patch(
                "src.printify_api_tools.get_product_info.parse_args",
                return_value=args,
            ),
            patch(
                "src.printify_api_tools.get_product_info.get_all_products",
                side_effect=RuntimeError("failure"),
            ),
            patch(
                "src.printify_api_tools.get_product_info.sys.exit",
                side_effect=SystemExit(1),
            ) as mock_exit,
        ):
            with pytest.raises(SystemExit, match="1"):
                product_info_main()

        mock_exit.assert_called_once_with(1)

    def test_publish_product_main_exits_with_status_one_on_error(self):
        """Exits with code 1 when the publish CLI raises an exception."""
        args = argparse.Namespace(
            product_id=PRODUCT_ID,
            shop_id=None,
            token_file=None,
        )

        with (
            patch(
                "src.printify_api_tools.publish_product.parse_args",
                return_value=args,
            ),
            patch(
                "src.printify_api_tools.publish_product.publish_product",
                side_effect=RuntimeError("failure"),
            ),
            patch(
                "src.printify_api_tools.publish_product.sys.exit",
                side_effect=SystemExit(1),
            ) as mock_exit,
        ):
            with pytest.raises(SystemExit, match="1"):
                publish_product_main()

        mock_exit.assert_called_once_with(1)
