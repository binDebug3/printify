"""Automates the publishing of Printify products to Etsy.

This script reads a Printify API token from a local text file and processes
a CSV-based schedule to trigger the publishing process for specific products.
It utilizes the Printify REST API to sync product details (title, description,
images, variants, tags, and shipping templates) to the connected Etsy shop.

Attributes:
    api_token.txt (file): A plain text file containing the Printify API bearer token.
    schedule.csv (file): A CSV file containing the publishing queue.
        Required columns:
            - shop_id: The unique identifier for the Printify shop.
            - product_id: The unique identifier for the product draft.

Example:
    To run the script, ensure both `api_token.txt` and `schedule.csv` are in the
    root directory:
        $ python publish_scheduler.py
"""

import os
import time
from typing import Optional
from datetime import datetime
import pandas as pd
from tools import load_api_token, publish_product
from logger_config import log_action
from notification import send_email


def main(token_file: Optional[str] = None, schedule_file: Optional[str] = None) -> None:
    """
    Publishes products to Etsy based on a schedule defined in a CSV file.

    This function reads product information from a 'schedule.csv' file and
    publishes each product to Etsy using the Printify API. It requires an
    API token stored in '../meta/api_token.txt'.
    The CSV file should contain the following columns:
        - shop_id: The Printify shop ID
        - product_id: The product ID to publish
    For each product in the schedule, the function attempts to publish it and
    prints the result status. If the product publishes successfully (HTTP 200),
    a success message is printed. Otherwise, the HTTP status code and error
    details are printed.

    Args:
        token_file (str): The path to the file containing the Printify API token.
        schedule_file (str): The path to the CSV file containing the publishing schedule.
    Returns:
        None
    Raises:
        SystemExit: If 'schedule_file' is not found in the current directory.
    """
    success_status_code: int = 200
    log_action("loading API token from file")
    token: str = load_api_token(token_file)
    if schedule_file is None:
        schedule_file = "../data/schedule.csv"

    if not os.path.exists(schedule_file):
        err_msg: str = f"Error: schedule.csv not found at '{schedule_file}'."
        log_action(err_msg)
        print(err_msg)
        return

    log_action(f"loading publishing schedule from '{schedule_file}'")
    today: str = datetime.now().strftime("%m/%d/%Y")
    full_df: pd.DataFrame = pd.read_csv(schedule_file)
    full_df["publish_status"] = full_df["publish_status"].astype(str).str.lower() == "true"
    todays_df = full_df[full_df["publish_date"] == today].copy()
    log_action(f"found {len(todays_df)} products scheduled for publishing today ({today})")

    success_count: int = 0
    for index, row in todays_df.iterrows():
        shop_id: str = row["shop_id"]
        product_id: str = row["product_id"]
        product_title: str = row["nick_name"]
        already_published: bool = row["publish_status"]

        if already_published:
            log_action(f"Product '{product_id}' is already published, skipping '{product_title}'.")
            continue

        log_action(f"Publishing product '{product_id}' ({product_title})")
        result = publish_product(product_id, shop_id, token)

        if result.status_code == success_status_code:
            success_count += 1
            full_df.at[index, "publish_status"] = True
            log_action(f"Success: Product {product_id} is now publishing to Etsy.")
            send_email(
                subject="New Shirt Published!",
                message_text=f"The product '{product_title}' (ID: {product_id}) has been "
                "successfully published to Etsy.",
            )
        else:
            log_action(f"Failed: {result.status_code} - {result.text}")

    log_action(f"Updating schedule file '{schedule_file}' with publish statuses")
    full_df.to_csv(schedule_file, index=False)
    success_message: str = (
        f"Done. {success_count}/{len(todays_df)} " + "products published successfully."
    )
    log_action(success_message)
    print(success_message)


if __name__ == "__main__":
    log_action("Publish script started ----------------------------------------\n")
    print("CHECKING FOR PRODUCTS TO PUBLISH")
    main()
    time.sleep(2)  # Sleep to ensure all log messages are written before the script exits
