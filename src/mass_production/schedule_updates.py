"""Schedule update helpers for newly created Printify products."""

import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from schedule.logger_config import log_action
from schedule.tools import load_shop_id

import constants


SCHEDULE_FIELD_NAMES: List[str] = [
    "nick_name",
    "product_id",
    "shop_id",
    "publish_status",
    "publish_date",
]
DATE_FORMAT: str = "%m/%d/%Y"
MIN_PUBLISH_OFFSET_DAYS: int = 4
MAX_PUBLISH_OFFSET_DAYS: int = 40
DATA_SCHEDULE_PATH: Path = constants.DATA_DIR / "schedule.csv"
AUTO_PUBLISH_SCHEDULE_PATH: Path = constants.AUTOMATION_ROOT.joinpath(
    "printify", "src", "schedule", "auto_publish", "schedule.csv"
)


def _read_rows(path: Path) -> List[Dict[str, str]]:
    """Read CSV rows from a schedule file.

    Args:
        path: CSV file path.

    Returns:
        Parsed rows. Missing files return an empty list.
    """
    log_action(f"Loading schedule rows from '{path}'")
    if not path.exists() or not path.is_file():
        return []

    with open(path, "r", encoding="utf-8", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        return [dict(row) for row in reader]


def _append_row(path: Path, row: Dict[str, str]) -> None:
    """Append one row to a schedule CSV, creating it with headers if needed.

    Args:
        path: CSV file path.
        row: Row payload.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header: bool = (not path.exists()) or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=SCHEDULE_FIELD_NAMES)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)
    log_action(
        f"Appended schedule row for product_id='{row['product_id']}' at '{path}'"
    )


def _parse_publish_date(value: str) -> date | None:
    """Parse a schedule date string.

    Args:
        value: Date text in MM/DD/YYYY format.

    Returns:
        Parsed date, or None for invalid values.
    """
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError:
        return None


def choose_publish_date(existing_rows: List[Dict[str, str]], today: date) -> str:
    """Choose a publish date that is as evenly distributed as possible.

    The candidate window is [today + 4 days, today + 40 days], inclusive. Dates
    are selected by lowest current usage count first; ties resolve to the earliest
    date.

    Args:
        existing_rows: Existing rows from data/schedule.csv.
        today: Reference date in local timezone.

    Returns:
        A publish date string in MM/DD/YYYY format.
    """
    window_start: date = today + timedelta(days=MIN_PUBLISH_OFFSET_DAYS)
    window_end: date = today + timedelta(days=MAX_PUBLISH_OFFSET_DAYS)

    counts_by_date: Dict[date, int] = {}
    current: date = window_start
    while current <= window_end:
        counts_by_date[current] = 0
        current = current + timedelta(days=1)

    for row in existing_rows:
        publish_date = _parse_publish_date(row.get("publish_date", ""))
        if publish_date is None:
            continue
        if window_start <= publish_date <= window_end:
            counts_by_date[publish_date] = counts_by_date[publish_date] + 1

    min_count: int = min(counts_by_date.values())
    for candidate in sorted(counts_by_date.keys()):
        if counts_by_date[candidate] == min_count:
            return candidate.strftime(DATE_FORMAT)

    raise RuntimeError("Unable to choose a publish date from schedule window")


def append_created_product_to_schedules(product_title: str, product_id: str) -> bool:
    """Append a newly created Printify product to both schedule CSV files.

    Conflict checks use only data/schedule.csv. If product_id already exists there,
    no row is added.

    Args:
        product_title: Product title to save in the nick_name column.
        product_id: Printify product ID from create-product response.

    Returns:
        True if a row was appended, otherwise False.
    """
    if not constants.SCHEDULE_NEW_PRODUCTS:
        log_action("Skipping schedule update because SCHEDULE_NEW_PRODUCTS is false")
        return False

    normalized_title: str = str(product_title).strip()
    normalized_product_id: str = str(product_id).strip()
    if not normalized_title or not normalized_product_id:
        log_action("Skipping schedule update due to missing title or product_id")
        return False

    source_rows: List[Dict[str, str]] = _read_rows(DATA_SCHEDULE_PATH)
    for row in source_rows:
        if row.get("product_id", "").strip() == normalized_product_id:
            log_action(
                f"Skipping schedule insert for existing product_id='{normalized_product_id}'"
            )
            return False

    chosen_publish_date: str = choose_publish_date(source_rows, datetime.now().date())
    shop_id: str = load_shop_id().strip()
    schedule_row: Dict[str, str] = {
        "nick_name": normalized_title,
        "product_id": normalized_product_id,
        "shop_id": shop_id,
        "publish_status": "False",
        "publish_date": chosen_publish_date,
    }

    _append_row(DATA_SCHEDULE_PATH, schedule_row)
    _append_row(AUTO_PUBLISH_SCHEDULE_PATH, schedule_row)
    return True
