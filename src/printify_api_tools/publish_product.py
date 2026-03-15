"""Publish Printify products through the Printify API.

This module exposes the product publish operation and a small CLI for running
that operation directly from the command line.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import requests

try:
    from schedule.logger_config import log_action
    from schedule.tools import load_api_token
    from schedule.tools import load_shop_id
except ModuleNotFoundError:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from schedule.logger_config import log_action
    from schedule.tools import load_api_token
    from schedule.tools import load_shop_id


def publish_product(
    product_id: str,
    shop_id: Optional[str] = None,
    token: Optional[str] = None,
) -> requests.Response:
    """
    Publish a product to Printify.

    Args:
        product_id: The unique identifier of the product to publish.
        shop_id: The unique identifier of the Printify shop.
        token: The API authentication token for Printify API access.

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

    publish_url = f"https://api.printify.com/v1/shops/{shop_id}/products/{product_id}/publish.json"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "title": True,
        "description": True,
        "images": True,
        "variants": True,
        "tags": True,
        "keyFeatures": True,
        "shipping_template": True,
    }

    log_action(
        f"sending publish request for product_id='{product_id}' and shop_id='{shop_id}'"
    )
    response = requests.post(publish_url, json=payload, headers=headers, timeout=10)
    log_action(
        f"received status_code={response.status_code} for product_id='{product_id}'"
    )
    return response


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for the publish command.

    Returns:
        Parsed command-line arguments.
    """
    log_action("parsing command-line arguments for product publishing")
    parser = argparse.ArgumentParser(description="Publish a Printify product.")
    parser.add_argument("product_id", help="Printify product id to publish.")
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
    return parser.parse_args()


def main() -> None:
    """
    Run the publish-product CLI.

    Raises:
        SystemExit: Exits with status code 1 when the publish request fails.
    """
    log_action("starting publish_product CLI")
    args = parse_args()

    try:
        token: Optional[str] = None
        if args.token_file is not None:
            token = load_api_token(args.token_file)

        response = publish_product(
            product_id=args.product_id,
            shop_id=args.shop_id,
            token=token,
        )
        try:
            payload = response.json()
            print(json.dumps(payload, indent=4))
        except ValueError:
            print(response.text)

        if response.status_code >= 400:
            sys.exit(1)
    except Exception as exc:
        log_action(f"error publishing product: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
