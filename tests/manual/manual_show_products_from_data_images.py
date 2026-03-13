# flake8: noqa: E501
"""Manual-only viewer test that serves products from data/images in a browser UI.

Run manually from the printify directory:
python -m pytest tests/manual/manual_show_products_from_data_images.py::test_manual_show_products_from_data_images -s --no-header --no-summary 

This file is intentionally named so it is not discovered by default pytest runs.
"""

import json
import mimetypes
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src"
MASS_PRODUCTION_ROOT = SRC_ROOT / "mass_production"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from logger_config import log_action  # noqa: E402
import show_products as show_products_module  # noqa: E402


IMAGES_DIR: Path = WORKSPACE_ROOT / "data" / "images"
MAX_MISSING_FIELDS: int = 3
REQUIRED_DETAIL_FIELDS: list[str] = [
    "mockup_image",
    "design_image",
    "title",
    "keywords",
    "price",
    "description",
]


def _read_text_if_exists(path: Path) -> str:
    """Read text from a file path when present.

    Args:
        path: Candidate text file path.

    Returns:
        File text, or an empty string when missing.
    """
    log_action(f"Reading optional text file '{path}' for manual products viewer")
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _extract_keywords(folder_path: Path) -> list[str]:
    """Extract keywords from keywords.txt when available.

    Args:
        folder_path: Product folder under data/images.

    Returns:
        List of keyword strings.
    """
    log_action(f"Extracting keywords for folder '{folder_path.name}'")
    keywords_path = folder_path / "keywords.txt"
    raw_keywords = _read_text_if_exists(keywords_path)
    if not raw_keywords:
        return []

    try:
        parsed = json.loads(raw_keywords)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass

    return [part.strip() for part in raw_keywords.split(",") if part.strip()]


def _extract_price(folder_path: Path) -> str:
    """Extract price text from printify_payload.json when available.

    Args:
        folder_path: Product folder under data/images.

    Returns:
        Price display string or "N/A".
    """
    log_action(f"Extracting price for folder '{folder_path.name}'")
    payload_path = folder_path / "printify_payload.json"
    if not payload_path.exists():
        return "N/A"

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "N/A"

    variants = payload.get("variants", []) if isinstance(payload, dict) else []
    prices_cents: List[int] = []
    for item in variants:
        if not isinstance(item, dict):
            continue
        price_value = item.get("price")
        if isinstance(price_value, int):
            prices_cents.append(price_value)
    if not prices_cents:
        return "N/A"

    min_cents = min(prices_cents)
    max_cents = max(prices_cents)
    if min_cents == max_cents:
        return f"${min_cents / 100:.2f}"
    return f"${min_cents / 100:.2f} - ${max_cents / 100:.2f}"


def _resolve_mockup_image(folder_path: Path) -> Optional[Path]:
    """Resolve a preferred mockup image path for a product folder.

    Args:
        folder_path: Product folder under data/images.

    Returns:
        Path to chosen mockup image, or None when unavailable.
    """
    log_action(f"Resolving mockup image for folder '{folder_path.name}'")
    preferred = sorted(folder_path.glob("mockup_(*)_cropped.png"))
    if preferred:
        return preferred[0]

    cropped_any = sorted(folder_path.glob("mockup_*_cropped.png"))
    if cropped_any:
        return cropped_any[0]

    any_mockup = sorted(folder_path.glob("mockup_*.png"))
    if any_mockup:
        return any_mockup[0]

    return None


def _build_view_model_from_folder(folder_path: Path) -> Dict[str, Any]:
    """Build a viewer item from one data/images folder.

    Args:
        folder_path: Product folder path.

    Returns:
        Viewer item dictionary with local file paths for images.

    Raises:
        ValueError: If the folder has too many missing fields.
    """
    log_action(f"Building viewer item from folder '{folder_path.name}'")
    title_text = _read_text_if_exists(
        folder_path / "title.txt"
    ) or folder_path.name.replace("_", " ")
    description_text = _read_text_if_exists(folder_path / "description.txt")
    keywords = _extract_keywords(folder_path)
    price_text = _extract_price(folder_path)

    design_path = folder_path / "design.png"
    mockup_path = _resolve_mockup_image(folder_path)

    item: Dict[str, Any] = {
        "id": folder_path.name,
        "title": title_text,
        "description": description_text,
        "keywords": keywords,
        "price": price_text,
        "mockup_image": str(mockup_path) if mockup_path else "",
        "design_image": str(design_path) if design_path.exists() else "",
        "_mockup_local_path": str(mockup_path) if mockup_path else "",
        "_design_local_path": str(design_path) if design_path.exists() else "",
    }

    missing_fields_count = 0
    for field_name in REQUIRED_DETAIL_FIELDS:
        value = item.get(field_name)
        if value == "" or value is None or value == "N/A":
            missing_fields_count += 1
            continue
        if isinstance(value, list) and not value:
            missing_fields_count += 1

    if missing_fields_count > MAX_MISSING_FIELDS:
        raise ValueError(
            f"Skipping '{folder_path.name}' due to missing fields: {missing_fields_count}"
        )

    return item


def _collect_view_models_from_data_images() -> Tuple[List[Dict[str, Any]], List[str]]:
    """Collect valid product view models from data/images folder structure.

    Returns:
        Tuple of (included items, skipped folder messages).
    """
    log_action("Collecting product items from data/images for manual viewer test")
    included_items: List[Dict[str, Any]] = []
    skipped_messages: List[str] = []

    for folder_path in sorted(IMAGES_DIR.iterdir()):
        if not folder_path.is_dir():
            continue
        try:
            included_items.append(_build_view_model_from_folder(folder_path))
        except Exception as exc:  # noqa: BLE001
            skipped_messages.append(f"{folder_path.name}: {exc}")
            log_action(f"Skipping folder '{folder_path.name}' for viewer test: {exc}")

    return included_items, skipped_messages


def _make_local_request_handler(
    items: List[Dict[str, Any]],
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler that serves pages and local image assets.

    Args:
        items: Product view models.

    Returns:
        HTTP request handler class.
    """
    log_action("Creating local request handler for manual data/images viewer")
    by_id: Dict[str, Dict[str, Any]] = {str(item["id"]): item for item in items}

    for item in items:
        product_id = urllib.parse.quote(str(item["id"]))
        item["mockup_image"] = f"/asset/{product_id}/mockup"
        item["design_image"] = f"/asset/{product_id}/design"

    class LocalProductsHandler(BaseHTTPRequestHandler):
        """HTTP handler for local manual products viewer."""

        def _write_html(self, content: str, status_code: int = 200) -> None:
            """Write an HTML response.

            Args:
                content: Response body.
                status_code: HTTP status code.
            """
            encoded = content.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _write_file(self, path: Path) -> None:
            """Write a binary file response.

            Args:
                path: File path to stream.
            """
            if not path.exists() or not path.is_file():
                self._write_html("<h1>Asset not found</h1>", status_code=404)
                return

            data = path.read_bytes()
            content_type, _ = mimetypes.guess_type(str(path))
            self.send_response(200)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            """Serve index, detail pages, and local image assets."""
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self._write_html(show_products_module._render_main_page(items))
                return

            if path.startswith("/product/"):
                product_id = urllib.parse.unquote(path.split("/product/", 1)[1])
                item = by_id.get(product_id)
                if item is None:
                    self._write_html("<h1>Product not found</h1>", status_code=404)
                    return
                self._write_html(show_products_module._render_detail_page(item))
                return

            if path.startswith("/asset/"):
                parts = path.split("/")
                if len(parts) != 4:
                    self._write_html("<h1>Asset not found</h1>", status_code=404)
                    return
                product_id = urllib.parse.unquote(parts[2])
                asset_kind = parts[3]
                item = by_id.get(product_id)
                if item is None:
                    self._write_html("<h1>Asset not found</h1>", status_code=404)
                    return

                original_path = ""
                if asset_kind == "mockup":
                    original_path = str(item.get("_mockup_local_path", "")).strip()
                elif asset_kind == "design":
                    original_path = str(item.get("_design_local_path", "")).strip()

                if not original_path:
                    self._write_html("<h1>Asset not found</h1>", status_code=404)
                    return
                self._write_file(Path(original_path))
                return

            self._write_html("<h1>Not found</h1>", status_code=404)

        def log_message(self, format: str, *args: Any) -> None:
            """Silence default HTTP logging for manual viewer test."""
            return

    return LocalProductsHandler


def test_manual_show_products_from_data_images() -> None:
    """Open a local viewer for products in data/images and allow manual inspection.

    This manual test includes all product folders unless data is missing beyond
    the configured threshold or a folder raises an exception while parsing.
    """
    log_action("Starting manual data/images products viewer test")
    items, skipped = _collect_view_models_from_data_images()
    if not items:
        pytest.skip("No valid products found in data/images for manual viewer test")

    print(f"Including {len(items)} products in viewer")
    if skipped:
        print(f"Skipping {len(skipped)} products with insufficient data/errors:")
        for message in skipped:
            print(f"- {message}")

    server = HTTPServer(("127.0.0.1", 0), _make_local_request_handler(items))
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    viewer_url = f"http://{host}:{port}"
    print(f"Opening viewer: {viewer_url}")

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    webbrowser.open(viewer_url)

    try:
        input("Press Enter to close the viewer and finish the manual test...")
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert len(items) > 0
