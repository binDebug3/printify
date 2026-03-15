"""Retrieve Printify variant information.

This module exposes variant retrieval helpers and a CLI for running the public
variant lookup operation directly from the command line.
"""

import argparse
import json
import sys
from pathlib import Path
from pprint import pprint
from typing import Dict, List, Optional

import requests

try:
    from schedule.logger_config import log_action
    from schedule.tools import load_api_token
except ModuleNotFoundError:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from schedule.logger_config import log_action
    from schedule.tools import load_api_token
    
# This is janky because these are already definced in mass_production.constants,
# but I can't import them
COMFORT_COLORS_BLUEPRINT_ID: int = 706
COMFORT_COLORS_PRINT_PROVIDER_ID: int = 99
SUCCESS: int = 200


def parse_variant_ids(
    data: Dict, output_path: str
) -> Dict[str, List[Dict[str, object]]]:
    """
    Parse variant data into color entries with ordered variant IDs.

    Args:
        data: Product data containing variant records.
        output_path: File path where the variant map will be saved as JSON.

    Returns:
        A payload shaped like {"variants": [{"color": ..., "ids": [...]}]}.
    """
    color_to_ids: Dict[str, List[int]] = {}

    log_action("parsing variant data to create color-to-ids mapping")
    for variant in data.get("variants", []):
        variant_id = variant.get("id")
        color = variant.get("options", {}).get("color")
        size = variant.get("options", {}).get("size")

        if color and size and isinstance(variant_id, int):
            if color not in color_to_ids:
                color_to_ids[color] = []
            color_to_ids[color].append(variant_id)

    payload: Dict[str, List[Dict[str, object]]] = {
        "variants": [
            {"color": color, "ids": ids} for color, ids in color_to_ids.items()
        ]
    }

    log_action(f"writing variant map to '{output_path}'")
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=4)
    log_action(f"saved variant map with {len(color_to_ids)} colors to '{output_path}'")
    return payload


def get_printify_variant_ids(
    output_path: str = "../data/variant_map.json",
    print_provider_id: Optional[int] = None,
    blueprint_id: Optional[int] = None,
    token: Optional[str] = None,
) -> Dict[str, List[Dict[str, object]]]:
    """
    Retrieve and map product variants from a Printify blueprint.

    Args:
        output_path: The path to save the variant map JSON file.
        print_provider_id: The unique identifier of the print provider.
        blueprint_id: The unique identifier of the Printify blueprint.
        token: The API authentication token for Printify API access.

    Returns:
        A dictionary with a single variants key containing color/id mappings.

    Raises:
        requests.exceptions.RequestException: If the HTTP request fails.
        ValueError: If the API response is invalid.
    """
    if print_provider_id is None:
        log_action(
            f"print_provider_id missing, using default {COMFORT_COLORS_PRINT_PROVIDER_ID}"
        )
        print_provider_id = COMFORT_COLORS_PRINT_PROVIDER_ID
    if blueprint_id is None:
        log_action(f"blueprint_id missing, using default {COMFORT_COLORS_BLUEPRINT_ID}")
        blueprint_id = COMFORT_COLORS_BLUEPRINT_ID
    if token is None:
        log_action("token missing, loading from file")
        token = load_api_token()

    url = (
        f"https://api.printify.com/v1/catalog/blueprints/{blueprint_id}/"
        f"print_providers/{print_provider_id}/variants.json"
    )
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        log_action(
            f"requesting variants for blueprint_id='{blueprint_id}' and "
            f"print_provider_id='{print_provider_id}'"
        )
        response = requests.get(url, headers=headers, timeout=10)
    except requests.exceptions.RequestException as exc:
        log_action(f"request failed for blueprint_id='{blueprint_id}'")
        log_action(f"error details: {exc}")
        raise exc

    if response.status_code != SUCCESS:
        error_message = (
            f"Failed to retrieve variants: {response.status_code} - {response.text}"
        )
        log_action(error_message)
        raise ValueError(error_message)

    data = response.json()
    log_action(f"data has keys: {list(data.keys())}")
    log_action(
        f"received {len(data.get('variants', []))} for blueprint_id='{blueprint_id}'"
    )

    return parse_variant_ids(data, output_path)


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for variant lookup.

    Returns:
        Parsed command-line arguments.
    """
    log_action("parsing command-line arguments for variant lookup")
    parser = argparse.ArgumentParser(
        description="Retrieve Printify variant ids for a blueprint/provider pair."
    )
    parser.add_argument(
        "--output-path",
        default="../data/variant_map.json",
        help="Path where the variant map JSON should be written.",
    )
    parser.add_argument(
        "--print-provider-id",
        type=int,
        default=None,
        help="Optional Printify print provider id.",
    )
    parser.add_argument(
        "--blueprint-id",
        type=int,
        default=None,
        help="Optional Printify blueprint id.",
    )
    parser.add_argument(
        "--token-file",
        default=None,
        help="Optional path to a Printify API token file.",
    )
    return parser.parse_args()


def main() -> None:
    """
    Run the variant-info CLI.

    Raises:
        SystemExit: Exits with status code 1 when variant lookup fails.
    """
    log_action("starting get_variant_info CLI")
    args = parse_args()

    try:
        token: Optional[str] = None
        if args.token_file is not None:
            token = load_api_token(args.token_file)

        result = get_printify_variant_ids(
            output_path=args.output_path,
            print_provider_id=args.print_provider_id,
            blueprint_id=args.blueprint_id,
            token=token,
        )
        pprint(result)
    except Exception as exc:
        log_action(f"error retrieving variant info: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
