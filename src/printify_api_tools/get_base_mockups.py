"""Download base mockup images for a Printify product.

This script fetches one Printify product, extracts mockup image URLs, writes them
to data/base_mockups/links.txt, and downloads the images to
data/base_mockups/<name>.png. Names are based on color in camelCase when
available, otherwise a numbered fallback like mockup1.png is used.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

PRINTIFY_API_BASE_URL: str = "https://api.printify.com/v1"
REQUEST_TIMEOUT_SECONDS: int = 30
AUTOMATION_ROOT: Path = Path(__file__).resolve().parents[3]
OUTPUT_DIR: Path = AUTOMATION_ROOT / "data" / "base_mockups"
LINKS_FILE: Path = OUTPUT_DIR / "links.txt"
VARIANT_IDS_PATH: Path = AUTOMATION_ROOT / "data" / "variant_ids.json"
VARIANT_MAP_PATH: Path = AUTOMATION_ROOT / "data" / "variant_map.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed command-line argument namespace.
    """
    log_action("Parsing command-line arguments for base mockup download")
    parser = argparse.ArgumentParser(
        description=(
            "Fetch mockup URLs for a Printify product, save links.txt, "
            "and download mockup PNGs."
        )
    )
    parser.add_argument(
        "product_id",
        nargs="?",
        default=None,
        help="Printify product id to fetch.",
    )
    parser.add_argument(
        "--from-links",
        action="store_true",
        help="Download all mockups from data/base_mockups/links.txt.",
    )
    return parser.parse_args()


def fetch_product(product_id: str, shop_id: str, token: str) -> Dict:
    """Fetch a single Printify product payload by id.

    Args:
        product_id: Printify product id.
        shop_id: Printify shop id.
        token: Printify API token.

    Returns:
        Product payload dictionary.

    Raises:
        ValueError: If the API request fails.
    """
    log_action(f"Fetching product payload for product_id='{product_id}'")
    url: str = f"{PRINTIFY_API_BASE_URL}/shops/{shop_id}/products/{product_id}.json"
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise ValueError(
            f"Failed to fetch product: {response.status_code} - {response.text}"
        )
    return response.json()


def to_camel_case(text: str) -> str:
    """Convert a string into lower camelCase with non-alnum filtering.

    Args:
        text: Input text.

    Returns:
        camelCase string, or empty string when no valid characters are present.
    """
    log_action("Converting text to camelCase for file naming")
    words: List[str] = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return ""
    first_word: str = words[0].lower()
    rest_words: List[str] = [word.capitalize() for word in words[1:]]
    return first_word + "".join(rest_words)


def load_variant_color_map(variant_map_path: Optional[Path] = None) -> Dict[int, str]:
    """Load a variant-id to color-name map from data/variant_map.json.

    Args:
        variant_map_path: Optional path override for variant map JSON.

    Returns:
        Mapping from variant id to color text.
    """
    if variant_map_path is None:
        variant_map_path = (
            VARIANT_IDS_PATH if VARIANT_IDS_PATH.exists() else VARIANT_MAP_PATH
        )
    log_action(f"Loading variant-color map from '{variant_map_path}'")
    if not variant_map_path.exists():
        raise FileNotFoundError(f"Variant map not found: '{variant_map_path}'")

    with open(variant_map_path, "r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    variants = payload.get("variants", [])
    if not isinstance(variants, list):
        raise ValueError("variant_map.json must contain a 'variants' list")

    variant_to_color: Dict[int, str] = {}
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        color_name = variant.get("color")
        ids = variant.get("ids", [])
        if not isinstance(color_name, str) or not isinstance(ids, list):
            continue

        for variant_id in ids:
            if isinstance(variant_id, int):
                variant_to_color[variant_id] = color_name

    return variant_to_color


def extract_variant_id_from_link(url: str, product_id: str) -> Optional[int]:
    """Extract variant id from mockup URL segment after product_id.

    Args:
        url: Mockup image URL.
        product_id: Printify product id.

    Returns:
        Variant id if found, otherwise None.
    """
    log_action("Extracting variant id from mockup URL")
    pattern = re.compile(rf"/{re.escape(product_id)}/(\d+)(?:/|$|\?)")
    match = pattern.search(url)
    if match is None:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_variant_id_from_link_by_map(
    url: str,
    variant_to_color: Dict[int, str],
) -> Optional[int]:
    """Extract variant id from a URL by matching known variant ids.

    This is useful when only links are available and product_id is not known.

    Args:
        url: Mockup image URL.
        variant_to_color: Mapping from variant ids to colors.

    Returns:
        Variant id if any numeric URL segment matches known ids.
    """
    log_action("Extracting variant id from URL using variant map lookup")
    for match in re.finditer(r"\d+", url):
        try:
            variant_id = int(match.group(0))
        except ValueError:
            continue
        if variant_id in variant_to_color:
            return variant_id
    return None


def extract_mockups(
    product: Dict,
    product_id: str,
    variant_to_color: Dict[int, str],
) -> List[Tuple[str, Optional[str]]]:
    """Extract mockup URL and optional color name tuples from product images.

    Args:
        product: Printify product payload.
        product_id: Printify product id used in mockup URL parsing.
        variant_to_color: Mapping from variant ids to color names.

    Returns:
        List of tuples in shape (url, color_or_none).
    """
    log_action("Extracting mockup URLs and colors from product images")
    images: List[Dict] = product.get("images", [])
    results: List[Tuple[str, Optional[str]]] = []

    for image in images:
        src = image.get("src")
        if not isinstance(src, str) or not src:
            continue

        variant_id = extract_variant_id_from_link(src, product_id)
        color_name: Optional[str] = None
        if variant_id is not None:
            color_name = variant_to_color.get(variant_id)

        results.append((src, color_name))

    return results


def assign_filenames(mockups: List[Tuple[str, Optional[str]]]) -> List[Tuple[str, str]]:
    """Assign output filenames for mockup URLs.

    Args:
        mockups: Mockup tuples in shape (url, color_or_none).

    Returns:
        List of tuples in shape (url, filename_without_extension).
    """
    log_action("Assigning output filenames for extracted mockups")
    assigned: List[Tuple[str, str]] = []
    used_names: Dict[str, int] = {}
    fallback_index: int = 1

    for url, color_name in mockups:
        base_name: str = ""
        if color_name:
            base_name = to_camel_case(color_name)

        if not base_name:
            base_name = f"mockup{fallback_index}"
            fallback_index += 1

        if base_name in used_names:
            used_names[base_name] += 1
            base_name = f"{base_name}{used_names[base_name]}"
        else:
            used_names[base_name] = 1

        assigned.append((url, base_name))

    return assigned


def write_links_file(urls: List[str], links_path: Optional[Path] = None) -> None:
    """Write mockup URLs to links.txt.

    Args:
        urls: Mockup URL list.
        links_path: Output path for links text file.
    """
    if links_path is None:
        links_path = LINKS_FILE
    log_action(f"Appending {len(urls)} mockup URLs to '{links_path}'")
    links_path.parent.mkdir(parents=True, exist_ok=True)
    with open(links_path, "a", encoding="utf-8") as file_obj:
        for url in urls:
            file_obj.write(f"{url}\n")


def download_image(url: str, output_path: Path) -> None:
    """Download one image URL to output path.

    Args:
        url: Image source URL.
        output_path: Local path for PNG file.

    Raises:
        ValueError: If image download fails.
    """
    log_action(f"Downloading mockup image to '{output_path.name}'")
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise ValueError(f"Failed to download image: {response.status_code} - {url}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as file_obj:
        file_obj.write(response.content)


def resolve_conflict_path(output_path: Path) -> Path:
    """Return a non-conflicting image path by appending a numeric suffix.

    Args:
        output_path: Preferred output path.

    Returns:
        First available path that does not yet exist.
    """
    log_action(f"Resolving output path conflicts for '{output_path.name}'")
    if not output_path.exists():
        return output_path

    stem: str = output_path.stem
    suffix: str = output_path.suffix
    index: int = 2
    while True:
        candidate = output_path.with_name(f"{stem}{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def save_mockups(product_id: str) -> List[Path]:
    """Fetch product mockups, write links file, and download image files.

    Args:
        product_id: Printify product id.

    Returns:
        List of output image paths.
    """
    log_action(f"Saving base mockups for product_id='{product_id}'")
    shop_id: str = load_shop_id()
    token: str = load_api_token()
    product: Dict = fetch_product(product_id=product_id, shop_id=shop_id, token=token)
    variant_to_color: Dict[int, str] = load_variant_color_map()
    mockups: List[Tuple[str, Optional[str]]] = extract_mockups(
        product=product,
        product_id=product_id,
        variant_to_color=variant_to_color,
    )
    if not mockups:
        raise ValueError("No mockup image URLs were found in the product payload.")

    assigned: List[Tuple[str, str]] = assign_filenames(mockups)
    write_links_file([url for url, _ in assigned])

    output_paths: List[Path] = []
    for url, name in assigned:
        output_path = resolve_conflict_path(OUTPUT_DIR / f"{name}.png")
        download_image(url, output_path)
        output_paths.append(output_path)

    return output_paths


def download_mockups_from_links_file(
    links_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    variant_map_path: Optional[Path] = None,
) -> List[Path]:
    """Download all mockups listed in links.txt using variant ids for color naming.

    Args:
        links_path: Path to links text file. Defaults to data/base_mockups/links.txt.
        output_dir: Directory for downloaded mockups. Defaults to data/base_mockups.
        variant_map_path: Optional path to variant map JSON.

    Returns:
        List of downloaded image paths.

    Raises:
        FileNotFoundError: If links file does not exist.
        ValueError: If no valid links are found.
    """
    if links_path is None:
        links_path = LINKS_FILE
    if output_dir is None:
        output_dir = OUTPUT_DIR

    log_action(f"Downloading mockups from links file '{links_path}'")
    if not links_path.exists():
        raise FileNotFoundError(f"Links file not found: '{links_path}'")

    variant_to_color = load_variant_color_map(variant_map_path)
    with open(links_path, "r", encoding="utf-8") as file_obj:
        raw_links = [line.strip() for line in file_obj.readlines()]

    links = [link for link in raw_links if link]
    if not links:
        raise ValueError(f"No links found in '{links_path}'")

    mockups: List[Tuple[str, Optional[str]]] = []
    for link in links:
        variant_id = extract_variant_id_from_link_by_map(link, variant_to_color)
        color_name = (
            variant_to_color.get(variant_id) if variant_id is not None else None
        )
        mockups.append((link, color_name))

    assigned = assign_filenames(mockups)

    output_paths: List[Path] = []
    for url, name in assigned:
        output_path = resolve_conflict_path(output_dir / f"{name}.png")
        download_image(url, output_path)
        output_paths.append(output_path)

    return output_paths


def main() -> None:
    """Run the CLI entrypoint for downloading base mockups.

    Raises:
        ValueError: If required inputs are missing or API data is invalid.
    """
    log_action("Starting get_base_mockups CLI")
    args = parse_args()
    if args.from_links:
        output_paths: List[Path] = download_mockups_from_links_file()
    else:
        if args.product_id is None or not args.product_id.strip():
            raise ValueError("product_id is required unless --from-links is used")
        output_paths = save_mockups(
            product_id=args.product_id.strip(),
        )

    print(f"Saved {len(output_paths)} mockups to '{OUTPUT_DIR}'.")
    print(f"Saved links file to '{LINKS_FILE}'.")


if __name__ == "__main__":
    main()
