# flake8: noqa: E501
"""Show Printify products in a local browser UI with image tiles and detail windows.

This script fetches all products for a Printify shop and starts a local web server.
The landing page shows product tiles with mockup images and titles. Clicking a tile
opens a new window containing product details in this order: mockup image,
design image, title, keywords, price, description.
"""

import argparse
import html
import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

import requests

import constants

try:
    from schedule.logger_config import log_action
except ModuleNotFoundError:
    SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if SRC_ROOT not in sys.path:
        sys.path.insert(0, SRC_ROOT)
    from schedule.logger_config import log_action


DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8787
REQUEST_TIMEOUT_SECONDS: int = 60
PAGE_SIZE: int = 100


def _require_env(var_name: str) -> str:
    """Read a required environment variable.

    Args:
        var_name: Name of the environment variable.

    Returns:
        Non-empty environment variable value.

    Raises:
        EnvironmentError: If the variable is missing or empty.
    """
    log_action(f"Reading required environment variable '{var_name}'")
    value: str = os.getenv(var_name, "").strip()
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {var_name}. Set it and run again."
        )
    return value


def _headers(token: str) -> Dict[str, str]:
    """Build HTTP headers for Printify requests.

    Args:
        token: Printify API token.

    Returns:
        Request headers.
    """
    log_action("Building Printify API headers")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": constants.PRINTIFY_USER_AGENT,
    }


def _fetch_all_products(token: str, shop_id: str) -> List[Dict[str, Any]]:
    """Fetch all products from Printify using paging.

    Args:
        token: Printify API token.
        shop_id: Printify shop id.

    Returns:
        List of product payload dictionaries.
    """
    log_action(f"Fetching all Printify products for shop_id='{shop_id}'")
    all_products: List[Dict[str, Any]] = []
    page: int = 1

    while True:
        url = (
            f"{constants.PRINTIFY_API_BASE_URL}/shops/{shop_id}/products.json"
            f"?page={page}&limit={PAGE_SIZE}"
        )
        response = requests.get(
            url,
            headers=_headers(token),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload: Dict[str, Any] = response.json()
        page_items: List[Dict[str, Any]] = payload.get("data", [])
        if not page_items:
            break

        all_products.extend(page_items)
        current_page: Optional[int] = payload.get("current_page")
        last_page: Optional[int] = payload.get("last_page")
        if isinstance(current_page, int) and isinstance(last_page, int):
            if current_page >= last_page:
                break
        page += 1

    log_action(f"Fetched {len(all_products)} products from Printify")
    return all_products


def _extract_mockup_image_url(product: Dict[str, Any]) -> str:
    """Extract a preferred mockup image URL from a product payload.

    Args:
        product: Printify product payload.

    Returns:
        Image URL string, if available.
    """
    log_action("Extracting mockup image URL for product tile")
    images: List[Dict[str, Any]] = product.get("images", [])
    for image in images:
        if image.get("is_default") and image.get("src"):
            return str(image.get("src"))
    for image in images:
        if image.get("src"):
            return str(image.get("src"))
    return ""


def _extract_design_image_url(product: Dict[str, Any]) -> str:
    """Extract the design image URL from product print areas.

    Args:
        product: Printify product payload.

    Returns:
        Design image URL string, if available.
    """
    log_action("Extracting design image URL for product details")
    print_areas: List[Dict[str, Any]] = product.get("print_areas", [])
    for area in print_areas:
        placeholders: List[Dict[str, Any]] = area.get("placeholders", [])
        for placeholder in placeholders:
            images: List[Dict[str, Any]] = placeholder.get("images", [])
            for image in images:
                src: Optional[str] = image.get("src")
                if src:
                    return str(src)
    return ""


def _extract_price_text(product: Dict[str, Any]) -> str:
    """Extract a user-friendly price string from product variants.

    Args:
        product: Printify product payload.

    Returns:
        Price display text.
    """
    log_action("Extracting price text for product details")
    variants: List[Dict[str, Any]] = product.get("variants", [])
    enabled_prices: List[int] = []
    for variant in variants:
        if variant.get("is_enabled") and isinstance(variant.get("price"), int):
            enabled_prices.append(int(variant["price"]))

    if not enabled_prices:
        return "N/A"

    min_price_cents: int = min(enabled_prices)
    max_price_cents: int = max(enabled_prices)
    if min_price_cents == max_price_cents:
        return f"${min_price_cents / 100:.2f}"
    return f"${min_price_cents / 100:.2f} - ${max_price_cents / 100:.2f}"


def _build_view_model(product: Dict[str, Any]) -> Dict[str, Any]:
    """Build a normalized product view model for UI rendering.

    Args:
        product: Raw Printify product payload.

    Returns:
        Product view model dictionary.
    """
    product_id: str = str(product.get("id", "")).strip()
    title: str = str(product.get("title", "Untitled product")).strip()
    description: str = str(product.get("description", "")).strip()
    tags: List[str] = [
        str(tag).strip() for tag in product.get("tags", []) if str(tag).strip()
    ]
    return {
        "id": product_id,
        "title": title,
        "description": description,
        "keywords": tags,
        "price": _extract_price_text(product),
        "mockup_image": _extract_mockup_image_url(product),
        "design_image": _extract_design_image_url(product),
    }


def _build_view_models(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert Printify products into UI view models.

    Args:
        products: Raw product payloads.

    Returns:
        List of normalized view models.
    """
    log_action("Building UI view models for product rendering")
    return [_build_view_model(product) for product in products if product.get("id")]


def _render_main_page(items: List[Dict[str, Any]]) -> str:
    """Render the main tiles page HTML.

    Args:
        items: Product view models.

    Returns:
        HTML page string.
    """
    log_action("Rendering main product tiles page")
    tiles: List[str] = []
    for item in items:
        product_id = urllib.parse.quote(str(item["id"]))
        title = html.escape(str(item["title"]))
        image_url = html.escape(str(item["mockup_image"]))
        image_tag = (
            f"<img class='tile-image' src='{image_url}' alt='{title}' loading='lazy'/>"
            if image_url
            else "<div class='tile-fallback'>No image</div>"
        )
        tiles.append(
            "<a class='tile' target='_blank' rel='noopener noreferrer' "
            f"href='/product/{product_id}'>"
            f"{image_tag}"
            f"<div class='tile-title'>{title}</div>"
            "</a>"
        )

    content: str = "\n".join(tiles)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<title>Printify Products</title>"
        "<style>"
        "body{margin:0;font-family:'Segoe UI',Tahoma,sans-serif;background:linear-gradient(180deg,#f7f9fc,#eef3fb);"
        "color:#10233a;}"
        ".wrap{max-width:1300px;margin:0 auto;padding:24px;}"
        ".header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;}"
        "h1{margin:0;font-size:1.8rem;}"
        ".count{font-weight:600;color:#2b4f79;background:#dde9fb;padding:8px 12px;border-radius:999px;}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-top:20px;}"
        ".tile{display:flex;flex-direction:column;text-decoration:none;color:inherit;background:#fff;border-radius:14px;"
        "overflow:hidden;box-shadow:0 10px 24px rgba(24,42,72,.12);border:1px solid #dce7f7;transition:.16s ease;}"
        ".tile:hover{transform:translateY(-2px);box-shadow:0 14px 28px rgba(24,42,72,.16);border-color:#b8cdef;}"
        ".tile-image{width:100%;height:220px;object-fit:cover;background:#f1f4fb;}"
        ".tile-fallback{height:220px;display:flex;align-items:center;justify-content:center;background:#f1f4fb;color:#5a6c84;}"
        ".tile-title{padding:12px 14px;font-weight:700;line-height:1.3;min-height:58px;}"
        "</style></head><body><div class='wrap'><div class='header'><h1>Printify Products</h1>"
        f"<div class='count'>{len(items)} products</div></div><div class='grid'>{content}</div>"
        "</div></body></html>"
    )


def _render_detail_page(item: Dict[str, Any]) -> str:
    """Render product details page in required field order.

    Args:
        item: Product view model.

    Returns:
        HTML page string.
    """
    log_action(f"Rendering details page for product_id='{item['id']}'")
    title = html.escape(str(item["title"]))
    description = html.escape(str(item["description"])) or "N/A"
    keywords = ", ".join(item.get("keywords", []))
    keywords_text = html.escape(keywords) if keywords else "N/A"
    price = html.escape(str(item.get("price", "N/A")))
    mockup_image = html.escape(str(item.get("mockup_image", "")))
    design_image = html.escape(str(item.get("design_image", "")))

    mockup_section = (
        f"<img class='hero' src='{mockup_image}' alt='Mockup image'/>"
        if mockup_image
        else "<div class='fallback'>No mockup image available</div>"
    )
    design_section = (
        f"<img class='hero' src='{design_image}' alt='Design image'/>"
        if design_image
        else "<div class='fallback'>No design image available</div>"
    )

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        f"<title>{title}</title><style>"
        "body{margin:0;background:#0f1a2b;color:#ecf3ff;font-family:'Segoe UI',Tahoma,sans-serif;}"
        ".container{max-width:920px;margin:0 auto;padding:22px;}"
        ".panel{background:#16243b;border:1px solid #27466f;border-radius:14px;padding:16px;margin-bottom:14px;}"
        ".hero{width:100%;max-height:520px;object-fit:contain;background:#0b1320;border-radius:10px;}"
        ".fallback{height:320px;display:flex;align-items:center;justify-content:center;background:#0b1320;"
        "border-radius:10px;color:#9fb4d2;}"
        "h1{margin:0;font-size:1.8rem;}"
        "h2{margin:0 0 8px 0;font-size:1.05rem;color:#b7cef0;text-transform:uppercase;letter-spacing:.05em;}"
        "p{margin:0;line-height:1.5;white-space:pre-wrap;}"
        "</style></head><body><div class='container'>"
        "<div class='panel'><h2>Mockup Image</h2>"
        f"{mockup_section}</div>"
        "<div class='panel'><h2>Design Image</h2>"
        f"{design_section}</div>"
        "<div class='panel'><h2>Title</h2>"
        f"<h1>{title}</h1></div>"
        "<div class='panel'><h2>Keywords</h2>"
        f"<p>{keywords_text}</p></div>"
        "<div class='panel'><h2>Price</h2>"
        f"<p>{price}</p></div>"
        "<div class='panel'><h2>Description</h2>"
        f"<p>{description}</p></div>"
        "</div></body></html>"
    )


def _make_request_handler(items: List[Dict[str, Any]]) -> type[BaseHTTPRequestHandler]:
    """Create an HTTP request handler bound to product data.

    Args:
        items: Product view models.

    Returns:
        Request handler class.
    """
    log_action("Creating request handler for local products server")
    by_id: Dict[str, Dict[str, Any]] = {str(item["id"]): item for item in items}

    class ProductsRequestHandler(BaseHTTPRequestHandler):
        """HTTP handler serving products pages."""

        def _write_html(self, content: str, status_code: int = 200) -> None:
            """Write an HTML response to the client.

            Args:
                content: HTML content body.
                status_code: HTTP status code.
            """
            log_action(f"Serving HTML response with status_code={status_code}")
            encoded = content.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            """Serve main page and product detail pages."""
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self._write_html(_render_main_page(items))
                return

            if path.startswith("/product/"):
                product_id = urllib.parse.unquote(path.split("/product/", 1)[1])
                item = by_id.get(product_id)
                if item is None:
                    self._write_html("<h1>Product not found</h1>", status_code=404)
                    return
                self._write_html(_render_detail_page(item))
                return

            self._write_html("<h1>Not found</h1>", status_code=404)

        def log_message(self, format: str, *args: Any) -> None:
            """Silence default HTTP server stdout logging."""
            return

    return ProductsRequestHandler


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the product viewer.

    Returns:
        Parsed command-line arguments.
    """
    log_action("Parsing CLI arguments for show_products")
    parser = argparse.ArgumentParser(
        description="Show all posted Printify products in a browser UI.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host for local server.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port for local server.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not auto-open the browser.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the local product browser UI server."""
    log_action("Starting Printify products viewer")
    args = _parse_args()
    token = _require_env("PRINTIFY_API_TOKEN")
    shop_id = _require_env("PRINTIFY_SHOP_ID")

    products = _fetch_all_products(token=token, shop_id=shop_id)
    view_models = _build_view_models(products)
    handler_cls = _make_request_handler(view_models)

    server_url = f"http://{args.host}:{args.port}"
    server = HTTPServer((args.host, args.port), handler_cls)
    log_action(f"Serving {len(view_models)} products at {server_url}")
    print(f"Serving {len(view_models)} products at {server_url}")

    if not args.no_open:
        webbrowser.open(server_url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_action("Stopping product viewer server after keyboard interrupt")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
