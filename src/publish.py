"""Automates the publishing of Printify products to Etsy."""

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from logger_config import log_action
from notification import send_email
from tools import load_api_token, publish_product


def _configure_mass_production_module_path() -> None:
    """Expose src/mass_production modules to the runtime import path."""
    log_action("Configuring module path for Etsy mockup sync")
    module_dir = Path(__file__).resolve().parent / "mass_production"
    sys.path.insert(0, str(module_dir))


def _open_actions_log_in_vscode() -> None:
    """Open meta/actions.log in VS Code and try to focus latest entries.

    This is best-effort behavior and does nothing if the `code` CLI is unavailable.
    """
    code_cli = shutil.which("code")
    if code_cli is None:
        log_action("VS Code CLI not found; skipping actions.log auto-open")
        return

    actions_log = Path(__file__).resolve().parents[2] / "meta" / "actions.log"
    try:
        subprocess.run(
            [code_cli, "--reuse-window", "--goto", f"{actions_log}:999999"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [code_cli, "--reuse-window", "--command", "workbench.action.closeSidebar"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        log_action(f"Failed to trigger VS Code actions.log focus: {exc}")


def load_schedule(schedule_file: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load the publishing schedule from CSV and filter for today's products.

    Args:
        schedule_file: Path to the CSV file containing the publishing schedule.

    Returns:
        A tuple containing the full DataFrame and today's filtered rows.
    """
    log_action(f"loading publishing schedule from '{schedule_file}'")
    today: str = datetime.now().strftime("%m/%d/%Y")
    full_df: pd.DataFrame = pd.read_csv(schedule_file)
    full_df["publish_status"] = (
        full_df["publish_status"].astype(str).str.lower() == "true"
    )
    todays_df: pd.DataFrame = full_df[full_df["publish_date"] == today].copy()
    log_action(
        f"found {len(todays_df)} products scheduled for publishing today ({today})"
    )
    return full_df, todays_df


def update_schedule(
    full_df: pd.DataFrame,
    schedule_file: str,
    success_count: int,
    total_count: int,
) -> None:
    """Persist updated publish statuses back to the schedule CSV.

    Args:
        full_df: The complete DataFrame with updated publish statuses.
        schedule_file: The path to the CSV file to be updated.
        success_count: The number of products successfully published.
        total_count: The total number of products scheduled for publishing.
    """
    log_action(f"Updating schedule file '{schedule_file}' with publish statuses")
    full_df.to_csv(schedule_file, index=False)
    success_message: str = f"Done. {success_count}/{total_count} products published."
    log_action(success_message)
    print(success_message)


def _sync_etsy_mockups_after_publish(published_products: List[Dict[str, str]]) -> None:
    """Delay briefly, then attempt to upload primary Etsy mockups.

    Args:
        published_products: Successful publish records with product_id, shop_id,
            and nick_name.
    """
    log_action("Waiting 60 seconds before attempting Etsy custom mockup sync")
    time.sleep(60)
    _configure_mass_production_module_path()
    from add_etsy_mockup import add_mockups_for_published_products

    add_mockups_for_published_products(published_products)


def main(token_file: Optional[str] = None, schedule_file: Optional[str] = None) -> None:
    """Publish products to Etsy based on rows scheduled for today.

    Args:
        token_file: Optional path to the file containing the Printify API token.
        schedule_file: Optional path to the CSV file containing the publishing schedule.
    """
    success_status_code: int = 200
    token: str = load_api_token(token_file)
    if schedule_file is None:
        schedule_file = "../data/schedule.csv"

    if not os.path.exists(schedule_file):
        err_msg: str = f"Error: schedule.csv not found at '{schedule_file}'."
        log_action(err_msg)
        print(err_msg)
        return

    full_df, todays_df = load_schedule(schedule_file)

    success_count: int = 0
    published_products: List[Dict[str, str]] = []
    for index, row in todays_df.iterrows():
        shop_id: str = row["shop_id"]
        product_id: str = row["product_id"]
        product_title: str = row["nick_name"]
        already_published: bool = row["publish_status"]

        if already_published:
            log_action(
                f"Product '{product_id}' is already published, skipping '{product_title}'."
            )
            continue

        log_action(f"Publishing product '{product_id}' ({product_title})")
        result = publish_product(product_id, shop_id, token)

        if result.status_code == success_status_code:
            success_count += 1
            full_df.at[index, "publish_status"] = True
            published_products.append(
                {
                    "product_id": product_id,
                    "shop_id": shop_id,
                    "nick_name": product_title,
                }
            )
            log_action(f"Success: Product {product_id} is now publishing to Etsy.")
            send_email(
                subject="New Shirt Published!",
                message_text=(
                    f"The product '{product_title}' (ID: {product_id}) has been "
                    "successfully published to Etsy."
                ),
            )
        else:
            log_action(f"Failed: {result.status_code} - {result.text}")

    if published_products:
        try:
            wrn_msg: str = "I don't actually have a working Etsy API so this won't work"
            log_action(wrn_msg)
            print(wrn_msg)
            _sync_etsy_mockups_after_publish(published_products)
        except Exception as exc:  # noqa: BLE001
            log_action(f"Failed to sync Etsy mockups after publish: {exc}")

    update_schedule(full_df, schedule_file, success_count, len(todays_df))


if __name__ == "__main__":
    log_action("'PUBLISH' script started ----------------------------------------\n")
    _open_actions_log_in_vscode()
    print("CHECKING FOR PRODUCTS TO PUBLISH")
    main()
    time.sleep(2)
