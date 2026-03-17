"""Add generated custom mockups to newly published Etsy listings.

This module bridges Printify-published products with Etsy listing image updates.
It uses the published product's nickname to locate the generated mockup folder under
data/products/<keyword>/<nick_name>, fetches the live Printify product title, finds
the corresponding Etsy listing by title, and uploads the cropped custom mockup as
the primary listing image.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import requests

import config.constants as constants
from product.models import EtsyConfig
from clients.etsy_client import EtsyClient
from schedule.logger_config import log_action
from schedule.tools import load_api_token


def load_etsy_config(
    config_path: Path = constants.DEFAULT_ETSY_CONFIG_PATH,
) -> EtsyConfig:
    """Load Etsy credentials from the shared JSON metadata file.

    Args:
        config_path: Path to the Etsy credential JSON file.

    Returns:
        Normalized Etsy configuration object.
    """
    log_action(f"Loading Etsy configuration from '{config_path}'")
    raw_payload: Dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    normalized_payload: Dict[str, str] = {
        _normalize_key(key): str(value).strip() for key, value in raw_payload.items()
    }
    return EtsyConfig(
        api_key=_require_config_value(normalized_payload, ["keystring"]),
        shared_secret=_require_config_value(normalized_payload, ["shared secret"]),
        refresh_token=_require_config_value(normalized_payload, ["refresh token"]),
        access_token=_require_config_value(normalized_payload, ["access token"]),
        shop_id=_require_config_value(normalized_payload, ["shop id"]),
    )


def fetch_printify_product_title(
    product_id: str, printify_shop_id: str, printify_token: str
) -> str:
    """Fetch the current Printify product title.

    Args:
        product_id: Printify product id.
        printify_shop_id: Printify shop id.
        printify_token: Printify bearer token.

    Returns:
        Current Printify product title.
    """
    log_action(
        f"Fetching Printify product title for product '{product_id}' in shop '{printify_shop_id}'"
    )
    response: requests.Response = requests.get(
        f"{constants.PRINTIFY_API_BASE_URL}/shops/{printify_shop_id}/products/{product_id}.json",
        headers={
            "Authorization": f"Bearer {printify_token}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    response.raise_for_status()
    payload: Dict[str, Any] = response.json()
    title: str = str(payload.get("title", "")).strip()
    if not title:
        raise RuntimeError(f"Printify product '{product_id}' returned no title")
    return title


def resolve_mockup_path(
    nick_name: str, products_dir: Path = constants.PRODUCTS_DIR
) -> Path:
    """Resolve the primary cropped mockup path for a nickname folder.

    Args:
        nick_name: Folder name under data/products.
        products_dir: Base products directory.

    Returns:
        Path to the first matching cropped mockup image.
    """
    log_action(f"Resolving Etsy mockup image for nickname folder '{nick_name}'")
    folder_path: Path = products_dir / nick_name
    if (not folder_path.exists() or not folder_path.is_dir()) and products_dir.exists():
        for keyword_dir in sorted(
            products_dir.iterdir(), key=lambda child: child.name.lower()
        ):
            if not keyword_dir.is_dir():
                continue
            nested_candidate: Path = keyword_dir / nick_name
            if nested_candidate.exists() and nested_candidate.is_dir():
                folder_path = nested_candidate
                break

    if not folder_path.exists() or not folder_path.is_dir():
        raise FileNotFoundError(f"Mockup folder not found for nickname '{nick_name}'")

    candidates: List[Path] = sorted(
        [
            child
            for child in folder_path.iterdir()
            if child.is_file() and constants.MOCKUP_FILE_PATTERN.match(child.name)
        ],
        key=lambda child: child.name.lower(),
    )
    if not candidates:
        raise FileNotFoundError(
            f"No cropped mockup image found in folder '{folder_path}'"
        )
    return candidates[0]


def add_mockups_for_published_products(
    published_products: List[Dict[str, str]],
    etsy_config_path: Path = constants.DEFAULT_ETSY_CONFIG_PATH,
    products_dir: Path = constants.PRODUCTS_DIR,
    make_primary: bool = True,
) -> Dict[str, int]:
    """Add generated custom mockups to newly published Etsy listings.

    Args:
        published_products: Successful publish records with product_id, shop_id,
            and nick_name.
        etsy_config_path: Path to the Etsy credential JSON file.
        products_dir: Base products directory.
        make_primary: Whether to upload the mockup as the first listing image.

    Returns:
        Summary counts for processed, updated, and failed products.
    """
    log_action(
        f"Starting Etsy mockup sync for {len(published_products)} published product(s)"
    )
    if not published_products:
        return {"processed": 0, "updated": 0, "failed": 0}

    etsy_client: EtsyClient = EtsyClient(load_etsy_config(etsy_config_path))
    printify_token: str = load_api_token()
    processed_count: int = 0
    updated_count: int = 0
    failed_count: int = 0

    for product in published_products:
        processed_count += 1
        product_id: str = str(product.get("product_id", "")).strip()
        printify_shop_id: str = str(product.get("shop_id", "")).strip()
        nick_name: str = str(product.get("nick_name", "")).strip()
        log_action(
            f"Processing Etsy mockup sync for Printify product '{product_id}' "
            f"and nickname '{nick_name}'"
        )
        try:
            listing_title: str = fetch_printify_product_title(
                product_id=product_id,
                printify_shop_id=printify_shop_id,
                printify_token=printify_token,
            )
            listing_id: int | None = etsy_client.find_listing_id_by_title(listing_title)
            if listing_id is None:
                raise RuntimeError(
                    f"No active Etsy listing found with title '{listing_title}'"
                )

            mockup_path: Path = resolve_mockup_path(
                nick_name=nick_name, products_dir=products_dir
            )
            etsy_client.upload_listing_image(
                listing_id=listing_id,
                image_path=mockup_path,
                make_primary=make_primary,
            )
            updated_count += 1
            log_action(
                f"Uploaded Etsy mockup '{mockup_path.name}' for listing '{listing_id}'"
            )
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            log_action(
                f"Failed Etsy mockup sync for product '{product_id}' ({nick_name}): {exc}"
            )

    summary: Dict[str, int] = {
        "processed": processed_count,
        "updated": updated_count,
        "failed": failed_count,
    }
    log_action(f"Completed Etsy mockup sync summary: {summary}")
    return summary


def _normalize_key(value: str) -> str:
    """Normalize credential keys for case-insensitive lookup.

    Args:
        value: Raw key name from the JSON payload.

    Returns:
        Lowercased key with underscores collapsed to spaces.
    """
    log_action(f"Normalizing Etsy credential key '{value}'")
    return value.strip().lower().replace("_", " ")


def _require_config_value(payload: Dict[str, str], keys: List[str]) -> str:
    """Read a required configuration value by one of several normalized key names.

    Args:
        payload: Normalized config mapping.
        keys: Candidate keys to test.

    Returns:
        Resolved non-empty value.
    """
    log_action(f"Resolving required Etsy config key from candidates: {keys}")
    for key in keys:
        value: str = payload.get(key, "").strip()
        if value:
            return value
    raise KeyError(f"Missing Etsy config value for keys: {keys}")
