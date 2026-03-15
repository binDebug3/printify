"""Retrieve Printify product information.

This module exposes product retrieval helpers and a CLI for running the public
product-info operations directly from the command line.
"""

import argparse
import json
import sys
from pathlib import Path
from pprint import pprint
from typing import Dict, List, Optional

import requests

try:
    from logger_config import log_action
    from tools import load_api_token
    from tools import load_shop_id
except ModuleNotFoundError:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from logger_config import log_action
    from tools import load_api_token
    from tools import load_shop_id


DEFAULT_PRODUCTS_PAGE_SIZE: int = 50
SUCCESS: int = 200


def get_all_products(
    shop_id: Optional[str] = None,
    token: Optional[str] = None,
    page: Optional[int] = None,
    limit: Optional[int] = None,
) -> requests.Response:
    """
    Retrieve products from a Printify shop.

    Args:
        shop_id: The unique identifier of the Printify shop.
        token: The API authentication token for Printify API access.
        page: Page number for paginated product retrieval.
        limit: Max product count to return for the requested page.

    Returns:
        The response object from the Printify API.

    Raises:
        requests.exceptions.RequestException: If the HTTP request fails or times out.
    """
    if shop_id is None:
        log_action("shop_id missing, loading from file")
        shop_id = load_shop_id()

    if token is None:
        log_action("token missing, loading from file")
        token = load_api_token()

    products_url = f"https://api.printify.com/v1/shops/{shop_id}/products.json"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params: Dict[str, int] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    log_action(
        f"requesting products for shop_id='{shop_id}', page={page}, limit={limit}"
    )
    try:
        response = requests.get(
            products_url, headers=headers, params=params or None, timeout=10
        )
    except requests.exceptions.ReadTimeout as exc:
        log_action(
            f"request timed out for shop_id='{shop_id}'. It might not be a valid shop id"
        )
        raise exc

    log_action(f"received status_code={response.status_code} for shop_id='{shop_id}'")
    return response


def get_all_product_ids(
    output_path: str = "../data/product_ids.txt",
    shop_id: Optional[str] = None,
    token: Optional[str] = None,
) -> list:
    """
    Retrieve all product titles and IDs from a Printify shop.

    Args:
        output_path: The path to save the list of product IDs.
        shop_id: The unique identifier of the Printify shop.
        token: The API authentication token for Printify API access.

    Returns:
        A list of tuples containing product titles and IDs.

    Raises:
        ValueError: If the API response is unsuccessful.
    """
    if shop_id is None:
        log_action("shop_id missing, loading from file")
        shop_id = load_shop_id()

    if token is None:
        log_action("token missing, loading from file")
        token = load_api_token()

    log_action("calling get all products with pagination")
    all_product_ids: List = []
    page: int = 1

    while True:
        response = get_all_products(
            shop_id, token, page=page, limit=DEFAULT_PRODUCTS_PAGE_SIZE
        )

        if response.status_code != SUCCESS:
            log_action(
                f"failed to retrieve products, status_code={response.status_code}"
            )
            raise ValueError(
                f"Failed to retrieve products: {response.status_code} - {response.text}"
            )

        products = response.json()
        page_items = products.get("data", [])
        if not page_items:
            break

        all_product_ids.extend(
            (product["title"], product["id"]) for product in page_items
        )

        current_page = products.get("current_page")
        last_page = products.get("last_page")
        if isinstance(current_page, int) and isinstance(last_page, int):
            if current_page >= last_page:
                break
        elif len(page_items) < DEFAULT_PRODUCTS_PAGE_SIZE:
            break

        page += 1

    log_action(f"writing {len(all_product_ids)} product ids to '{output_path}'")
    with open(output_path, "w", encoding="utf-8") as file_handle:
        for title, product_id in all_product_ids:
            file_handle.write(f"{title},{product_id},{shop_id},\n")

    print(
        f"Successfully retrieved and saved {len(all_product_ids)} products to '{output_path}'."
    )
    log_action(f"saved {len(all_product_ids)} product ids to '{output_path}'")
    return all_product_ids


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for product info commands.

    Returns:
        Parsed command-line arguments.
    """
    log_action("parsing command-line arguments for product info retrieval")
    parser = argparse.ArgumentParser(
        description="Retrieve Printify product information."
    )
    parser.add_argument(
        "--list-ids",
        action="store_true",
        help="Write product ids to disk instead of printing the raw product payload.",
    )
    parser.add_argument(
        "--shop-id",
        default=None,
        help="Optional Printify shop id. Defaults to ../meta/shop_id.txt.",
    )
    parser.add_argument(
        "--token-file",
        default=None,
        help="Optional path to a Printify API token file.",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=None,
        help="Optional page number when retrieving raw product payloads.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional page size when retrieving raw product payloads.",
    )
    parser.add_argument(
        "--output-path",
        default="../data/product_ids.txt",
        help="Output file used by --list-ids.",
    )
    return parser.parse_args()


def main() -> None:
    """
    Run the product-info CLI.

    Raises:
        SystemExit: Exits with status code 1 when the selected command fails.
    """
    log_action("starting get_product_info CLI")
    args = parse_args()

    try:
        token: Optional[str] = None
        if args.token_file is not None:
            token = load_api_token(args.token_file)

        if args.list_ids:
            result = get_all_product_ids(
                output_path=args.output_path,
                shop_id=args.shop_id,
                token=token,
            )
            pprint(result)
            return

        response = get_all_products(
            shop_id=args.shop_id,
            token=token,
            page=args.page,
            limit=args.limit,
        )
        try:
            print(json.dumps(response.json(), indent=4))
        except ValueError:
            print(response.text)

        if response.status_code >= 400:
            sys.exit(1)
    except Exception as exc:
        log_action(f"error retrieving product info: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
