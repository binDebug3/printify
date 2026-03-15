"""Create a single Printify draft product from a completed dry-run folder."""

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Dict

# Make src/ importable when run as a script from printify root.
SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schedule.logger_config import log_action  # noqa: E402

import constants  # noqa: E402
from photoshop.io_utils import read_json, read_text  # noqa: E402
from clients.printify_client import PrintifyClient  # noqa: E402


def _open_actions_log_in_vscode() -> None:
    """Open meta/actions.log in VS Code and try to focus latest entries.

    This is best-effort behavior and does nothing if the `code` CLI is unavailable.
    """
    log_action("Attempting to open actions.log in VS Code for better visibility")
    code_cli = shutil.which("code")
    if code_cli is None:
        log_action("VS Code CLI not found; skipping actions.log auto-open")
        return

    actions_log = Path(__file__).resolve().parents[3] / "meta" / "actions.log"
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


def _abort(message: str) -> None:
    """Log and print an error, then abort the run.

    Args:
        message: User-facing error message.
    """
    log_action(f"ABORT: {message}")
    print(message)
    raise SystemExit(1)


def _require_file(path: Path, label: str) -> Path:
    """Ensure a required file exists.

    Args:
        path: Candidate file path.
        label: Human-readable file label.

    Returns:
        The same path if it exists.
    """
    log_action(f"Checking existence of required file '{label}' at '{path}'")
    if not path.exists() or not path.is_file():
        directory = path.parent
        file_name = path.name
        if directory.exists() and directory.is_dir():
            options = [child.name for child in directory.iterdir() if child.is_file()]
            suggestion = _closest_folder_name(file_name, options)
            if suggestion is not None:
                _abort(
                    f"Missing required {label}: {path}. Did you mean '{suggestion}'?"
                )
        _abort(f"Missing required {label}: {path}")
    return path


def _closest_folder_name(name: str, options: List[str]) -> str | None:
    """Find the closest folder name candidate using string similarity.

    Args:
        name: User-provided folder slug.
        options: Existing folder slugs.

    Returns:
        Closest match or None.
    """
    log_action(f"Finding closest match for '{name}'")
    matches = difflib.get_close_matches(name, options, n=1, cutoff=0.0)
    return matches[0] if matches else None


def _resolve_folder(folder_slug: str) -> Path:
    """Resolve a dry-run folder by slug and suggest closest match if missing.

    Args:
        folder_slug: Folder name under data/products.

    Returns:
        Absolute path to the dry-run folder.
    """
    log_action(f"Resolving dry-run folder for slug '{folder_slug}'")
    if "/" in folder_slug or "\\" in folder_slug:
        _abort("Folder input must be a slug only (no path separators).")

    products_dir = constants.PRODUCTS_DIR
    candidate = products_dir / folder_slug
    if candidate.exists() and candidate.is_dir():
        return candidate

    existing = (
        [child.name for child in products_dir.iterdir() if child.is_dir()]
        if products_dir.exists()
        else []
    )
    suggestion = _closest_folder_name(folder_slug, existing)
    if suggestion is None:
        _abort(f"Folder '{folder_slug}' not found under {products_dir}.")
    _abort(
        f"Folder '{folder_slug}' not found under {products_dir}. "
        f"Did you mean '{suggestion}'?"
    )
    return candidate


def _find_color_mockup_cropped(folder: Path) -> Path:
    """Find color-specific cropped mockup file inside a dry-run folder.

    Args:
        folder: Dry-run output folder path.

    Returns:
        Path to the matching cropped mockup file.
    """
    # Accept filenames like mockup_(White)_cropped.png, mockup_(Flo_Blue)_cropped.png,
    # or other color labels in the middle.
    pattern = re.compile(r"^mockup_.+_cropped\.png$", re.IGNORECASE)
    candidates = [
        child
        for child in folder.iterdir()
        if child.is_file() and pattern.match(child.name)
    ]
    if not candidates:
        options = [child.name for child in folder.iterdir() if child.is_file()]
        suggestion = _closest_folder_name("mockup_<color>_cropped.png", options)
        if suggestion:
            _abort(
                f"No file matching mockup_<color>_cropped.png found in '{folder}'. "
                f"Closest file: '{suggestion}'."
            )
        _abort(f"No file matching mockup_<color>_cropped.png found in '{folder}'.")
    if len(candidates) > 1:
        log_action(
            f"Multiple color cropped mockups found; using first alphabetical: "
            f"{sorted([p.name for p in candidates])[0]}"
        )
    return sorted(candidates, key=lambda p: p.name)[0]


def _load_keywords(path: Path) -> List[str]:
    """Load keywords from a JSON array text file.

    Args:
        path: Path to keywords.txt.

    Returns:
        List of keyword strings.
    """
    log_action(f"Loading keywords from '{path}'")
    raw = read_text(path)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        _abort(f"keywords.txt is not valid JSON array: {exc}")

    if not isinstance(parsed, list):
        _abort("keywords.txt must contain a JSON array.")

    keywords: List[str] = [str(item).strip() for item in parsed if str(item).strip()]
    if not keywords:
        _abort("keywords.txt has no valid keywords.")
    return keywords


def _load_selected_colors(
    idea_json_path: Path, color_to_ids: Dict[str, List[int]]
) -> List[str]:
    """Load selected colors from ideas.json, with validation and fallback.

    Args:
        idea_json_path: Path to ideas.json.
        color_to_ids: Available color map from variant_map.json.

    Returns:
        Valid color names list.
    """
    log_action(
        f"Loading selected colors against variant_map colors from '{idea_json_path}'"
    )
    ideas_payload = read_json(idea_json_path)
    if not isinstance(ideas_payload, list) or not ideas_payload:
        _abort("ideas.json must contain a non-empty list.")

    first = ideas_payload[0]
    if not isinstance(first, dict):
        _abort("ideas.json first item must be an object.")

    raw_colors = first.get("shirt_colors", [])
    if not isinstance(raw_colors, list):
        _abort("ideas.json field 'shirt_colors' must be a list.")

    selected = [str(c).strip() for c in raw_colors if str(c).strip() in color_to_ids]
    if selected:
        return selected

    fallback = list(color_to_ids.keys())
    if not fallback:
        _abort("variant_map.json has no usable colors.")
    log_action(
        "No valid shirt_colors in ideas.json; falling back to all variant_map colors"
    )
    return fallback


def _load_color_to_ids(path: Path) -> dict[str, list[int]]:
    """Load and validate color-to-ids mapping.

    Args:
        path: Path to variant_map.json.

    Returns:
        Mapping of color name to ordered list of variant ids.
    """
    log_action(f"Loading color-to-ids mapping from '{path}'")
    payload = read_json(path)
    if not isinstance(payload, dict):
        _abort("variant_map.json must contain an object.")

    variants = payload.get("variants", [])
    if not isinstance(variants, list) or not variants:
        _abort("variant_map.json field 'variants' must be a non-empty list.")

    color_to_ids: dict[str, list[int]] = {}
    for entry in variants:
        if not isinstance(entry, dict):
            continue
        color = str(entry.get("color", "")).strip()
        ids = entry.get("ids", [])
        if not color or not isinstance(ids, list):
            continue
        numeric_ids = [int(v) for v in ids if isinstance(v, int)]
        if numeric_ids:
            color_to_ids[color] = numeric_ids

    if not color_to_ids:
        _abort("variant_map.json does not contain valid color/id mappings.")
    return color_to_ids


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for post dry-run product creation.

    Returns:
        Parsed arguments with folder slug.
    """
    log_action("Parsing command-line arguments for post dry-run product creation")
    parser = argparse.ArgumentParser(
        description="Create one Printify draft from a dry-run folder"
    )
    parser.add_argument(
        "folder_slug",
        help="Folder name under data/products generated by dry run (slug only)",
    )
    return parser.parse_args()


def main() -> None:
    """Create a single Printify product draft from dry-run outputs."""
    log_action("'POST DRY RUN' -------------------------------\n")
    args = parse_args()

    folder = _resolve_folder(args.folder_slug)
    log_action(f"Resolved dry-run folder: {folder}")

    idea_json_path = _require_file(folder / "ideas.json", "ideas.json")
    title_path = _require_file(folder / "title.txt", "title.txt")
    description_path = _require_file(folder / "description.txt", "description.txt")
    keywords_path = _require_file(folder / "keywords.txt", "keywords.txt")
    transparent_path = _require_file(
        folder / "design_transparent.png", "design_transparent.png"
    )
    mockup_cropped_path = _find_color_mockup_cropped(folder)

    printify_token = read_text(constants.PRINTIFY_API_TOKEN_PATH)
    printify_shop_id = read_text(constants.PRINTIFY_SHOP_ID_PATH)
    if not printify_token:
        _abort(f"Printify token file is empty: {constants.PRINTIFY_API_TOKEN_PATH}")
    if not printify_shop_id:
        _abort(f"Printify shop id file is empty: {constants.PRINTIFY_SHOP_ID_PATH}")

    title = read_text(title_path)
    description = read_text(description_path)
    keywords = _load_keywords(keywords_path)

    if not title:
        _abort("title.txt is empty.")
    if not description:
        _abort("description.txt is empty.")

    color_to_ids = _load_color_to_ids(constants.VARIANT_MAP_PATH)
    selected_colors = _load_selected_colors(idea_json_path, color_to_ids)

    client = PrintifyClient(
        token=printify_token,
        shop_id=printify_shop_id,
        blueprint_id=constants.BLUEPRINT_ID,
        print_provider_id=constants.PRINT_PROVIDER_ID,
        size_order=constants.SIZE_ORDER,
        size_surcharge_usd=constants.SIZE_SURCHARGE_USD,
        print_x=constants.PRINT_POSITION_X,
        print_y=constants.PRINT_POSITION_Y,
        print_scale=constants.PRINT_SCALE,
        min_price_usd=constants.MIN_PRICE_USD,
        dry_run=False,
        retries=constants.MAX_PRINTIFY_RETRIES,
    )

    base_price = client.pick_base_price_usd(
        constants.BASE_PRICE_USD, constants.PRICE_STDEV_USD
    )
    log_action(f"Sampled base price for '{folder.name}': {base_price}")

    try:
        upload_result = client.upload_image(transparent_path)
    except Exception as exc:  # noqa: BLE001
        _abort(f"Failed to upload image to Printify: {exc}")

    try:
        mockup_upload_result = client.upload_image(mockup_cropped_path)
    except Exception as exc:  # noqa: BLE001
        _abort(f"Failed to upload cropped color mockup to Printify: {exc}")

    image_id = upload_result.get("id") if isinstance(upload_result, dict) else None
    if not image_id:
        _abort("Printify upload succeeded but returned no image id.")

    mockup_image_id = (
        mockup_upload_result.get("id")
        if isinstance(mockup_upload_result, dict)
        else None
    )
    mockup_src = (
        mockup_upload_result.get("preview_url")
        if isinstance(mockup_upload_result, dict)
        else None
    )
    if not mockup_image_id:
        _abort(
            "Mockup upload succeeded but returned no image id, so default image cannot be set."
        )
    log_action(
        f"Using uploaded mockup image id for default image attempt: '{mockup_image_id}'"
    )

    payload = client.build_payload(
        title=title,
        description=description,
        tags=keywords,
        selected_colors=selected_colors,
        color_to_ids=color_to_ids,
        design_transparent_path=transparent_path,
        uploaded_image_id=str(image_id),
        base_price_usd=base_price,
        free_shipping=True,
    )

    try:
        result = client.create_product(payload)
    except Exception as exc:  # noqa: BLE001
        _abort(f"Failed to create Printify product draft: {exc}")

    product_id = result.get("id") if isinstance(result, dict) else None
    if product_id:
        try:
            client.update_product_metadata(
                product_id=str(product_id),
                tags=keywords,
                free_shipping=True,
            )
            log_action(f"Metadata update attempted for product '{product_id}'")

            variant_ids: List[int] = []
            for variant in payload.get("variants", []):
                if not isinstance(variant, dict):
                    continue
                variant_id = variant.get("id")
                if isinstance(variant_id, int):
                    variant_ids.append(variant_id)
            client.set_default_mockup_image(
                product_id=str(product_id),
                mockup_image_id=str(mockup_image_id),
                variant_ids=variant_ids,
                mockup_src=str(mockup_src) if mockup_src else None,
            )
            log_action(
                f"Default mockup update attempted for product '{product_id}' with image "
                f"'{mockup_image_id}'"
            )

            verified_product = client.get_product(str(product_id))
            verified_tags = verified_product.get("tags", [])
            if isinstance(verified_tags, list):
                log_action(
                    f"Verified product '{product_id}' now has {len(verified_tags)} tags"
                )

            verified_images = verified_product.get("images", [])
            mockup_applied = False
            if isinstance(verified_images, list) and mockup_src:
                for image in verified_images:
                    if not isinstance(image, dict):
                        continue
                    src = image.get("src")
                    if isinstance(src, str) and src == mockup_src:
                        mockup_applied = True
                        break
            if mockup_applied:
                log_action(
                    f"Verified product '{product_id}' includes uploaded custom mockup as image"
                )
            else:
                log_action(
                    f"Product '{product_id}' does not include uploaded custom mockup in returned "
                    f"image set; Printify appears to keep generated mockups"
                )
            result = verified_product
        except Exception as exc:  # noqa: BLE001
            log_action(f"Default mockup update attempt failed (continuing): {exc}")

    write_target_payload = folder / "printify_payload.json"
    write_target_result = folder / "printify_result.json"
    write_target_upload = folder / "printify_upload.json"

    with open(write_target_payload, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    with open(write_target_result, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    with open(write_target_upload, "w", encoding="utf-8") as f:
        json.dump(
            {
                "design_transparent_upload": upload_result,
                "default_mockup_upload": mockup_upload_result,
            },
            f,
            indent=2,
        )

    success_msg = (
        f"Created Printify draft product for folder '{folder.name}'. "
        f"Product id: {product_id if product_id else 'unknown'}"
    )
    log_action(success_msg)
    print(success_msg)


if __name__ == "__main__":
    _open_actions_log_in_vscode()
    main()
