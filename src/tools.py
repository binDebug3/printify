"""
Tools for interacting with the Printify API.
This module provides utility functions for managing Printify API authentication
and product publishing operations. It handles API token loading from files and
publishing products to the Printify platform with configurable sync options.

Functions:
    load_api_token: Load an API token from a file.
    publish_product: Publish a product to Printify.
"""

import argparse
import json
import pdb  # noqa: F401
import sys
from pathlib import Path
from pprint import pprint
from typing import Dict, List, Optional

import requests
from logger_config import log_action

COMFORT_COLORS_BLUEPRINT_ID: int = 706
COMFORT_COLORS_PRINT_PROVIDER_ID: int = 99
SUCCESS: int = 200


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
        f"sending publish request for " f"product_id='{product_id}' and shop_id='{shop_id}'"
    )

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

    if response.status_code != SUCCESS:
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


def parse_variant_ids(
    data: Dict,
    output_path: str
) -> Dict[str, Dict[str, int]]:
    """
    Parse variant data and create a mapping of color-size combinations to variant IDs.
    
    This function processes product variant data to extract color and size information,
    organizing variant IDs in a hierarchical dictionary structure for easy lookup.
    
    Args:
        data (Dict): Product data containing 'variants' and 'options' keys.
            - 'variants' is a list of variant objects with 'id' and 'options' keys
            - 'options' is a list of option objects with 'type' and 'values' keys
        output_path (str): File path where the variant map will be saved as JSON.
    Returns:
        Dict[str, Dict[str, int]]: A nested dictionary mapping colors to sizes to variant IDs.
            Structure: {color: {size: variant_id}}
            Example: {"Red": {"Small": 12345}, "Blue": {"Medium": 12346}}
    Side Effects:
        - Logs the parsing action and file write operations
        - Creates parent directories if they don't exist at output_path
    """
    variant_map: Dict = {}

    # Map variant IDs to their color and size labels
    log_action("parsing variant data to create color-size-variant_id mapping")
    for variant in data.get("variants", []):
        variant_id = variant.get("id")
        color = variant.get("options", {}).get("color")
        size = variant.get("options", {}).get("size")

        if color and size:
            if color not in variant_map:
                variant_map[color] = {}
            variant_map[color][size] = variant_id

    # Save to JSON file
    log_action(f"writing variant map to '{output_path}'")
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(variant_map, f, indent=4)
    log_action(f"saved variant map with {len(variant_map)} colors to '{output_path}'")
    return variant_map
    

def get_printify_variant_ids(
    output_path: str = "../data/variant_map.json",
    print_provider_id: Optional[int] = None,
    blueprint_id: Optional[int] = None,
    token: Optional[str] = None,
) -> Dict[str, Dict[str, int]]:
    """
    Retrieves and maps product variants from a Printify blueprint.

    This function fetches variant data from the Printify API for a specific
    blueprint and print provider, then creates a nested dictionary mapping
    colors to sizes and their corresponding variant IDs. The result is saved
    to a JSON file.

    Args:
        blueprint_id (int): The unique identifier of the Printify blueprint.
        print_provider_id (int): The unique identifier of the print provider.
        output_path (str): The path to save the variant map JSON file.
            Defaults to '../data/variant_map.json'.
        token (str): The API authentication token for Printify API access.
            If None, it will be loaded from file.

    Returns:
        dict: A nested dictionary mapping colors to sizes and variant IDs.
            Format: {color: {size: variant_id, ...}, ...}

    Raises:
        requests.exceptions.RequestException: If the HTTP request fails.
        ValueError: If the API response is invalid or missing expected data.
    """
    if print_provider_id is None:
        log_action(f"print_provider_id missing, using default {COMFORT_COLORS_PRINT_PROVIDER_ID}")
        print_provider_id = COMFORT_COLORS_PRINT_PROVIDER_ID
    if blueprint_id is None:
        log_action(f"blueprint_id missing, using default {COMFORT_COLORS_BLUEPRINT_ID}")
        blueprint_id = COMFORT_COLORS_BLUEPRINT_ID
    if token is None:
        log_action("token missing, loading from file")
        token = load_api_token()

    url = (f"https://api.printify.com/v1/catalog/blueprints/{blueprint_id}/"
           f"print_providers/{print_provider_id}/variants.json")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        log_action(f"requesting variants for blueprint_id='{blueprint_id}' and "
                   f"print_provider_id='{print_provider_id}'")
        response = requests.get(url, headers=headers, timeout=10)
    except requests.exceptions.RequestException as e:
        log_action(f"request failed for blueprint_id='{blueprint_id}'")
        log_action(f"error details: {e}")
        raise e

    if response.status_code != SUCCESS:
        err_msg: str = f"Failed to retrieve variants: {response.status_code} - {response.text}"
        log_action(err_msg)
        raise ValueError(err_msg)
    
    data = response.json()    
    log_action(f"data has keys: {list(data.keys())}")
    log_action(f"received {len(data.get('variants', []))} for blueprint_id='{blueprint_id}'")
    
    return parse_variant_ids(data, output_path)


def parse_args() -> str | None:
    """
    Parse command-line arguments and return the function name to execute.
    
    This function sets up an argument parser that accepts a function name 
    (either full or abbreviated) and returns the corresponding full function name. 
    If an abbreviated name is provided, it maps it to the full function name.
    
    Returns:
        str | None: The name of the function to execute. Returns one of:
            - "get_printify_variant_ids"
            - "get_all_product_ids"
            - "get_all_products"
            Defaults to "get_printify_variant_ids" if no argument is provided.
            Returns None if parsing fails or no valid function is selected.
    Raises:
        SystemExit: If an invalid function name is provided that is not in the choices list.
    """
    parser = argparse.ArgumentParser(
        description="Run Printify tools functions from the command line."
    )
    parser.add_argument(
        "function",
        nargs="?",
        default="get_printify_variant_ids",
        help="Function to run (default: get_printify_variant_ids)",
        choices=[
            "get_printify_variant_ids",
            "gpvi",
            "get_all_product_ids",
            "gapi",
            "get_all_products",
            "gap",
        ],
    )

    args = parser.parse_args()

    # Map abbreviated function names to full names
    function_map = {
        "gpvi": "get_printify_variant_ids",
        "gapi": "get_all_product_ids",
        "gap": "get_all_products",
    }

    function_name = function_map.get(args.function, args.function)
    return function_name


def main() -> None:
    """
    Execute Printify tools functions with default arguments.

    Provides a command-line interface to run different functions from the
    tools module using their default configuration.
    """
    log_action("'TOOLS' script started ----------------------------------------\n")
    function_name = parse_args()

    try:
        if function_name == "get_printify_variant_ids":
            result = get_printify_variant_ids()
            pprint(result)
        elif function_name == "get_all_product_ids":
            result = get_all_product_ids()
            pprint(result)
        elif function_name == "get_all_products":
            result = get_all_products()
            pprint(result.json())
    except Exception as e:
        log_action(f"error executing {function_name}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
