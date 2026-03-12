"""
Tools for interacting with the Printify API.
This module provides utility functions for managing Printify API authentication
and product publishing operations. It handles API token loading from files and
publishing products to the Printify platform with configurable sync options.

Functions:
    load_api_token: Load an API token from a file.
    publish_product: Publish a product to Printify.
"""

from typing import Optional, List
from pprint import pprint
import requests
from logger_config import log_action


def load_api_token(filepath: Optional[str] = None) -> str:
    """
    Load an API token from a file.

    This function reads the contents of a file and returns the API token
    as a string with leading and trailing whitespace removed.

    Args:
        filepath (str): The path to the file containing the API token.
    Returns:
        str: The API token read from the file, with whitespace stripped.
    Raises:
        FileNotFoundError: If the file at the specified filepath does not exist.
        IOError: If there is an error reading the file.
    """
    if filepath is None:
        filepath = "../meta/api_token.txt"
    log_action(f"reading token from '{filepath}'")

    with open(filepath, "r", encoding="utf-8") as f:
        token = f.read().strip()

    log_action("token loaded successfully")
    return token


def load_shop_id() -> str:
    """
    Load the Printify shop ID from a file.

    This function reads the contents of 'shop_id.txt' and returns the shop ID
    as a string with leading and trailing whitespace removed.

    Returns:
        str: The Printify shop ID read from 'shop_id.txt', with whitespace stripped.
    """
    file_path: str = "../meta/shop_id.txt"
    log_action(f"reading shop id from '{file_path}'")
    with open(file_path, "r", encoding="utf-8") as f:
        shop_id = f.read().strip()

    log_action("shop id loaded successfully")
    return shop_id


def publish_product(
    product_id: str,
    shop_id: Optional[str] = None,
    token: Optional[str] = None,
) -> requests.Response:
    """
    Publishes a product to Printify.

    This function publishes a product to the Printify platform by sending a POST
    request to the Printify API's publish endpoint. It configures which product
    attributes should be synced during publication.

    Args:
        shop_id (str): The unique identifier of the Printify shop.
        product_id (str): The unique identifier of the product to publish.
        token (str): The API authentication token for Printify API access.
    Returns:
        requests.Response: The response object from the Printify API containing
            the publication result and status code.
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

    # Printify's publish endpoint allows you to toggle what gets synced
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
        f"sending publish request for " f"product_id='{product_id}' and shop_id='{shop_id}'")

    response = requests.post(publish_url, json=payload, headers=headers, timeout=10)
    log_action(f"received status_code={response.status_code} " f"for product_id='{product_id}'")
    return response


def get_all_products(
    shop_id: Optional[str] = None,
    token: Optional[str] = None,
) -> requests.Response:
    """
    Retrieves all products from a Printify shop.

    This function sends a GET request to the Printify API to fetch all products
    associated with a specific shop. It requires the shop ID and an API token
    for authentication.

    Args:
        shop_id (str): The unique identifier of the Printify shop.
        token (str): The API authentication token for Printify API access.
    Returns:
        requests.Response: The response object from the Printify API containing
            the list of products and status code.
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

    log_action(f"requesting products for shop_id='{shop_id}'")
    try:
        response = requests.get(products_url, headers=headers, timeout=10)
    except requests.exceptions.ReadTimeout as e:
        log_action(f"request timed out for shop_id='{shop_id}'. It might not be a valid shop id")
        raise e
    log_action(f"received status_code={response.status_code} " f"for shop_id='{shop_id}'")
    return response


def get_all_product_ids(
    output_path: str = "../data/product_ids.txt",
    shop_id: Optional[str] = None,
    token: Optional[str] = None,
) -> list:
    """
    Retrieves all product IDs from a Printify shop.

    This function fetches all products from a specified Printify shop and extracts
    their unique identifiers (IDs). It requires the shop ID and an API token for
    authentication.

    Args:
        output_path (str): The path to save the list of product IDs.
            Defaults to '../data/product_ids.txt'.
        shop_id (str): The unique identifier of the Printify shop.
        token (str): The API authentication token for Printify API access.
    Returns:
        list: A list of tuples containing product titles and their corresponding IDs.
    Raises:
        requests.exceptions.RequestException: If the HTTP request fails or times out.
        ValueError: If the response does not contain valid product data.
    """
    if shop_id is None:
        log_action("shop_id missing, loading from file")
        shop_id = load_shop_id()

    if token is None:
        log_action("token missing, loading from file")
        token = load_api_token()

    log_action("calling get all products")
    response = get_all_products(shop_id, token)

    if response.status_code != 200:
        log_action("failed to retrieve products, " f"status_code={response.status_code}")
        raise ValueError(f"Failed to retrieve products: {response.status_code} - {response.text}")

    products = response.json()
    all_product_ids: List = [(product["title"], product["id"]) for product in products["data"]]

    # save to output file
    log_action(f"writing {len(all_product_ids)} product ids to '{output_path}'")
    with open(output_path, "w", encoding="utf-8") as f:
        for title, product_id in all_product_ids:
            f.write(f"{title},{product_id},{shop_id},\n")

    print(f"Successfully retrieved and saved {len(all_product_ids)} products to '{output_path}'.")
    log_action(f"saved {len(all_product_ids)} product ids to '{output_path}'")
    return all_product_ids


if __name__ == "__main__":
    log_action("Tools script started ----------------------------------------\n")
    pprint(get_all_product_ids())
