"""Printify payload builder and optional draft product creator."""

import base64
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

import config.constants as constants
from schedule.logger_config import log_action
from file_tools.io_utils import cut


class LeakyBucketRateLimiter:
    """Leaky bucket limiter for evenly pacing outbound API requests."""

    def __init__(self, max_requests_per_minute: int) -> None:
        """Initialize limiter capacity and leak rate.

        Args:
            max_requests_per_minute: Maximum requests allowed during any rolling minute.
        """
        self._capacity: float = float(max(1, max_requests_per_minute))
        self._leak_rate_per_second: float = self._capacity / 60.0
        self._level: float = 0.0
        self._last_checked_at: float = time.monotonic()

    def acquire(self) -> None:
        """Block until a new request can be admitted into the bucket."""
        now: float = time.monotonic()
        leaked_amount: float = (
            now - self._last_checked_at
        ) * self._leak_rate_per_second
        self._level = max(0.0, self._level - leaked_amount)
        self._last_checked_at = now

        if self._level + 1.0 <= self._capacity:
            self._level += 1.0
            return

        overflow: float = (self._level + 1.0) - self._capacity
        wait_seconds: float = overflow / self._leak_rate_per_second
        log_action(
            "Printify leaky bucket delaying request | "
            f"wait_seconds={wait_seconds:.2f} | "
            f"bucket_level={self._level:.2f}/{self._capacity:.0f}"
        )
        time.sleep(wait_seconds)
        self.acquire()


class PrintifyClient:
    """Printify helper for dry-run payload creation and optional API posting.

    Args:
        token: Printify API token.
        shop_id: Printify shop ID.
        blueprint_id: Blueprint ID for product template.
        print_provider_id: Print provider ID.
        size_order: Expected variant size ordering for mapped IDs.
        size_surcharge_usd: Per-size surcharge map.
        print_x: Print placement X coordinate.
        print_y: Print placement Y coordinate.
        print_scale: Print placement scale.
        min_price_usd: Lower bound for generated pricing.
        dry_run: If true, never performs network create requests.
        retries: Maximum retries for create requests.
        max_requests_per_minute: Maximum Printify API requests allowed per minute.
    """

    def __init__(
        self,
        token: str,
        shop_id: str,
        blueprint_id: int,
        print_provider_id: int,
        size_order: List[str],
        size_surcharge_usd: Dict[str, float],
        print_x: float,
        print_y: float,
        print_scale: float,
        min_price_usd: float,
        dry_run: bool,
        retries: int,
        max_requests_per_minute: int,
    ):
        self._token: str = token
        self._shop_id: str = shop_id
        self._blueprint_id: int = blueprint_id
        self._print_provider_id: int = print_provider_id
        self._size_order: List[str] = size_order
        self._size_surcharge_usd = size_surcharge_usd
        self._print_x: float = print_x
        self._print_y: float = print_y
        self._print_scale: float = print_scale
        self._min_price_usd: float = min_price_usd
        self._dry_run: bool = dry_run
        self._retries: int = retries
        self._rate_limiter: LeakyBucketRateLimiter = LeakyBucketRateLimiter(
            max_requests_per_minute=max_requests_per_minute
        )

    def pick_base_price_usd(self, base_usd: float, stdev_usd: float) -> float:
        """Sample a base price from a Gaussian distribution with a minimum floor.

        Args:
            base_usd: Mean price in USD.
            stdev_usd: Standard deviation in USD.

        Returns:
            Rounded base price in USD.
        """
        sampled: float = random.gauss(base_usd, stdev_usd)
        return round(max(self._min_price_usd, sampled), 2)

    def build_payload(
        self,
        title: str,
        description: str,
        tags: List[str],
        selected_colors: List[str],
        color_to_ids: Dict[str, List[int]],
        design_transparent_path: Path,
        uploaded_image_id: str | None,
        base_price_usd: float,
        free_shipping: bool = True,
    ) -> Dict[str, Any]:
        """Build a Printify create-product payload from selected colors and variants.

        Args:
            title: Listing title.
            description: Listing description.
            tags: Listing tags.
            selected_colors: Requested shirt colors.
            color_to_ids: Mapping of color to ordered variant IDs.
            design_transparent_path: Design image path used by print areas.
            uploaded_image_id: Uploaded Printify media-library image id for real runs.
            base_price_usd: Base product price in USD before surcharges.
            free_shipping: Whether to enable free shipping for connected channels that support it.

        Returns:
            Printify payload dictionary.

        Raises:
            ValueError: If no selected colors are available in the variant map.
        """
        log_action(f"Building Printify payload for title '{title}'")
        log_action(f"Selected colors: {selected_colors}")
        log_action(f"Tags: {tags}")
        log_action(f"Base price (USD): {base_price_usd}")
        log_action(f"Design image path: '{cut(design_transparent_path)}'")
        log_action(f"Uploaded image ID: '{uploaded_image_id}'")
        variants: List[Dict[str, Any]] = []
        variant_ids: List[int] = []
        normalized_tags: List[str] = self._normalize_tags(tags)

        colors_in_payload: List[str] = [c for c in selected_colors if c in color_to_ids]
        if not colors_in_payload:
            raise ValueError("No selected colors are available in variant_map.json")

        for color in colors_in_payload:
            ids_for_color: List[int] = color_to_ids[color]
            for idx, variant_id in enumerate(ids_for_color):
                size: str = (
                    self._size_order[idx]
                    if idx < len(self._size_order)
                    else f"IDX_{idx}"
                )
                surcharge: float = self._size_surcharge_usd.get(size, 0.0)
                price_cents: int = int(round((base_price_usd + surcharge) * 100))
                variants.append(
                    {
                        "id": variant_id,
                        "price": price_cents,
                        "is_enabled": True,
                        "is_default": len(variants) == 0,
                    }
                )
                variant_ids.append(variant_id)

        image_entry: Dict[str, Any] = {
            "id": uploaded_image_id or "DRY_RUN_IMAGE_ID",
            "x": self._print_x,
            "y": self._print_y,
            "scale": self._print_scale,
            "angle": 0,
        }
        if uploaded_image_id is None:
            image_entry["source_image_path"] = str(design_transparent_path)

        payload: Dict[str, Any] = {
            "title": title,
            "description": description,
            "blueprint_id": self._blueprint_id,
            "print_provider_id": self._print_provider_id,
            "tags": normalized_tags,
            "sales_channel_properties": {
                "free_shipping": free_shipping,
            },
            "variants": variants,
            "print_areas": [
                {
                    "variant_ids": variant_ids,
                    "placeholders": [
                        {
                            "position": "front",
                            "images": [image_entry],
                        }
                    ],
                }
            ],
        }
        return payload

    def update_product_metadata(
        self,
        product_id: str,
        tags: List[str],
        free_shipping: bool,
    ) -> Dict[str, Any]:
        """Update product metadata fields that may be ignored during create.

        Args:
            product_id: Created product id.
            tags: Tag list to apply.
            free_shipping: Free shipping toggle for supported channels.

        Returns:
            Product payload returned by update endpoint.
        """
        if self._dry_run:
            log_action(
                f"Dry-run mode: skipping metadata update for product '{product_id}'"
            )
            return {
                "dry_run": True,
                "product_id": product_id,
            }

        normalized_tags: List[str] = self._normalize_tags(tags)
        payload: Dict[str, Any] = {
            "tags": normalized_tags,
            "sales_channel_properties": {
                "free_shipping": free_shipping,
            },
        }
        log_action(
            f"Attempting metadata update for product '{product_id}' with "
            f"{len(normalized_tags)} tags"
        )
        response = self._request(
            "put",
            f"{constants.PRINTIFY_API_BASE_URL}/shops/{self._shop_id}/products/{product_id}.json",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def set_default_mockup_image(
        self,
        product_id: str,
        mockup_image_id: str,
        variant_ids: List[int],
        mockup_src: str | None = None,
    ) -> Dict[str, Any]:
        """Best-effort update to set a custom uploaded image as product default mockup.

        Args:
            product_id: Created product id.
            mockup_image_id: Uploaded media-library image id for the custom mockup.
            variant_ids: Enabled variant ids to bind the image to.

        Returns:
            Product payload returned by update endpoint.
        """
        if self._dry_run:
            log_action(
                f"Dry-run mode: skipping default mockup update for product '{product_id}'"
            )
            return {
                "dry_run": True,
                "product_id": product_id,
                "mockup_image_id": mockup_image_id,
            }

        log_action(
            f"Attempting to set custom default mockup image '{mockup_image_id}' "
            f"for product '{product_id}'"
        )
        payload: Dict[str, Any] = {"images": []}
        image_by_id: Dict[str, Any] = {
            "id": mockup_image_id,
            "variant_ids": variant_ids,
            "position": "front",
            "is_default": True,
        }
        payload["images"].append(image_by_id)
        if mockup_src:
            payload["images"].append(
                {
                    "src": mockup_src,
                    "variant_ids": variant_ids,
                    "position": "front",
                    "is_default": True,
                }
            )
        response = self._request(
            "put",
            f"{constants.PRINTIFY_API_BASE_URL}/shops/{self._shop_id}/products/{product_id}.json",
            json=payload,
            timeout=60,
        )
        log_action(f"Set default mockup response status code: {response.status_code}")
        response.raise_for_status()
        return response.json()

    def get_product(self, product_id: str) -> Dict[str, Any]:
        """Fetch product from Printify.

        Args:
            product_id: Product identifier.

        Returns:
            Product payload.
        """
        response = self._request(
            "get",
            f"{constants.PRINTIFY_API_BASE_URL}/shops/{self._shop_id}/products/{product_id}.json",
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def upload_image(self, image_path: Path) -> Dict[str, Any]:
        """Upload an image to the Printify media library.

        Args:
            image_path: Local path to the transparent design image.

        Returns:
            Upload response payload, or a dry-run placeholder object.
        """
        if self._dry_run:
            log_action(f"Dry-run mode: skipping image upload for '{image_path}'")
            return {
                "dry_run": True,
                "id": "DRY_RUN_IMAGE_ID",
                "file_name": image_path.name,
            }

        log_action(f"Uploading image '{cut(image_path)}' to Printify media library")
        encoded_contents = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload: Dict[str, str] = {
            "file_name": image_path.name,
            "contents": encoded_contents,
        }

        response = self._request(
            "post",
            f"{constants.PRINTIFY_API_BASE_URL}/uploads/images.json",
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        return response.json()

    def create_product(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a product draft in Printify, or return dry-run data.

        Args:
            payload: Create-product request body.

        Returns:
            API response payload or dry-run object.
        """
        if self._dry_run:
            log_action(
                f"Dry-run mode: skipping product creation for '{
                    payload.get('title', 'UNKNOWN')
                }'"
            )
            return {
                "dry_run": True,
                "message": "Product creation skipped by dry-run setting.",
                "payload": payload,
            }

        log_action(f"Creating product '{payload.get('title', 'UNKNOWN')}' in Printify")
        url: str = (
            f"{constants.PRINTIFY_API_BASE_URL}/shops/{self._shop_id}/products.json"
        )

        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = self._request("post", url, json=payload, timeout=60)
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self._retries - 1:
                    continue
                raise

        raise RuntimeError(f"Printify create product failed: {last_error}")

    def _headers(self) -> dict[str, str]:
        """Build standard Printify API headers.

        Returns:
            Header mapping for Printify requests.
        """
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": constants.PRINTIFY_USER_AGENT,
        }

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Send a rate-limited HTTP request to the Printify API.

        Args:
            method: HTTP method name.
            url: Target URL.
            **kwargs: Extra request keyword arguments.

        Returns:
            HTTP response object.
        """
        attempts_remaining: int = 2
        while attempts_remaining > 0:
            self._rate_limiter.acquire()
            response: requests.Response = requests.request(
                method=method,
                url=url,
                headers=self._headers(),
                **kwargs,
            )
            if response.status_code != 429:
                return response

            attempts_remaining -= 1
            retry_after_seconds: float = self._parse_retry_after_seconds(response)
            log_action(
                "Printify rate limit response received | "
                f"retry_after_seconds={retry_after_seconds:.2f} | url='{url}'"
            )
            if attempts_remaining == 0:
                return response
            time.sleep(retry_after_seconds)

        raise RuntimeError("Printify request loop exited unexpectedly")

    @staticmethod
    def _parse_retry_after_seconds(response: requests.Response) -> float:
        """Extract a server-provided retry delay from a 429 response.

        Args:
            response: HTTP response object.

        Returns:
            Sleep duration in seconds.
        """
        retry_after_header: str = str(response.headers.get("Retry-After", "")).strip()
        if retry_after_header.isdigit():
            return max(1.0, float(retry_after_header))
        return 5.0

    @staticmethod
    def _normalize_tags(raw_tags: List[str]) -> List[str]:
        """Normalize tags to Etsy-friendly short phrases.

        Args:
            raw_tags: Raw tag candidates.

        Returns:
            Deduplicated list capped at 13 tags, each up to 20 characters.
        """
        default_tags: List[str] = ["comfort colors", "unisex t shirt"]
        raw_tags = [tag for tag in raw_tags if tag not in default_tags]
        log_action(f"Normalizing {len(raw_tags)} raw tags for Etsy compatibility")
        normalized: List[str] = []
        seen: set[str] = set()
        for tag in raw_tags:
            cleaned = re.sub(r"[^a-zA-Z0-9\s'\-]", " ", str(tag)).strip()
            cleaned = re.sub(r"\s+", " ", cleaned)
            if not cleaned:
                continue
            cleaned = cleaned[: constants.KEYWORD_MAX_LENGTH].strip()
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
            if len(normalized) >= constants.MAX_ALLOWED_TAGS:
                break
        return normalized
