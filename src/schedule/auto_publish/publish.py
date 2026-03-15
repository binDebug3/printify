"""Bare-bones Printify product publisher for GitHub Actions daily scheduling."""

import csv
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import requests


_DIR: Path = Path(__file__).resolve().parent
LOG_PATH: Path = _DIR / "auto_publish.log"
SCHEDULE_PATH: Path = _DIR / "schedule.csv"

PUBLISH_URL_TEMPLATE: str = (
    "https://api.printify.com/v1/shops/{shop_id}/products/{product_id}/publish.json"
)
SUCCESS_STATUS_CODE: int = 200
DATE_FORMAT: str = "%m/%d/%Y"
PUBLISH_PAYLOAD: Dict[str, bool] = {
    "title": True,
    "description": True,
    "images": True,
    "variants": True,
    "tags": True,
    "keyFeatures": True,
    "shipping_template": True,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(funcName)-20s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
    ],
)
_logger = logging.getLogger(__name__)


def log_action(action: str) -> None:
    """Write a standardised action message to both stdout and the log file.

    Args:
        action: Descriptive message of the event being recorded.
    """
    _logger.info(action, stacklevel=2)


def _require_env(var_name: str) -> str:
    """Read a required environment variable.

    Args:
        var_name: Name of the environment variable.

    Returns:
        Non-empty variable value.

    Raises:
        EnvironmentError: If the variable is absent or empty.
    """
    value: str = os.environ.get(var_name, "").strip()
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {var_name}")
    return value


def load_schedule(path: Path) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Load schedule.csv and return all rows plus those scheduled for today.

    Args:
        path: Absolute path to schedule.csv.

    Returns:
        Tuple of (all_rows, todays_rows) where each row is a plain dict.
    """
    today: str = datetime.now().strftime(DATE_FORMAT)
    log_action(f"Loading schedule from '{path}', filtering for {today}")

    rows: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        for row in reader:
            rows.append(dict(row))

    todays_rows: List[Dict[str, str]] = [
        row for row in rows if row.get("publish_date", "").strip() == today
    ]
    log_action(f"Found {len(todays_rows)} product(s) scheduled for today ({today})")
    return rows, todays_rows


def publish_product(product_id: str, shop_id: str, token: str) -> requests.Response:
    """Send a publish request to the Printify API.

    Args:
        product_id: Printify product ID.
        shop_id: Printify shop ID.
        token: Printify API bearer token.

    Returns:
        HTTP response from the Printify API.
    """
    url: str = PUBLISH_URL_TEMPLATE.format(shop_id=shop_id, product_id=product_id)
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    log_action(f"Publishing product_id='{product_id}' to shop_id='{shop_id}'")
    response: requests.Response = requests.post(
        url, json=PUBLISH_PAYLOAD, headers=headers, timeout=15
    )
    log_action(f"Response status={response.status_code} for product_id='{product_id}'")
    return response


def main() -> None:
    """Publish today's scheduled products to Printify.

    Reads PRINTIFY_API_TOKEN and PRINTIFY_SHOP_ID from environment variables,
    loads schedule.csv, and publishes every unpublished product whose
    publish_date matches today.
    """
    log_action("Auto-publish started")

    token: str = _require_env("PRINTIFY_API_TOKEN")
    shop_id: str = _require_env("PRINTIFY_SHOP_ID")

    if not SCHEDULE_PATH.exists():
        log_action(f"schedule.csv not found at '{SCHEDULE_PATH}'; nothing to publish")
        return

    _all_rows, todays_rows = load_schedule(SCHEDULE_PATH)

    if not todays_rows:
        log_action("No products scheduled for today; exiting")
        return

    success_count: int = 0
    total_count: int = len(todays_rows)

    for row in todays_rows:
        product_id: str = row.get("product_id", "").strip()
        nick_name: str = row.get("nick_name", "").strip()
        already_published: bool = (
            row.get("publish_status", "").strip().lower() == "true"
        )

        if not product_id:
            log_action("Skipping row with missing product_id")
            continue

        if already_published:
            log_action(f"Skipping '{nick_name}' ({product_id}): already published")
            continue

        response: requests.Response = publish_product(product_id, shop_id, token)

        if response.status_code == SUCCESS_STATUS_CODE:
            success_count += 1
            log_action(
                f"Success: '{nick_name}' ({product_id}) is now publishing to Etsy"
            )
        else:
            log_action(
                f"Failed: '{nick_name}' ({product_id}) "
                f"status={response.status_code} body={response.text[:300]}"
            )

    log_action(
        f"Auto-publish complete: {success_count}/{total_count} product(s) published"
    )


if __name__ == "__main__":
    main()
