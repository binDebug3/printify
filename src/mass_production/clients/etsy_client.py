
import requests
from pathlib import Path
from typing import Any, Dict, List

import constants
from schedule.logger_config import log_action
from models import EtsyConfig


class EtsyClient:
    """Minimal Etsy API client for listing lookup and image upload.

    Args:
        config: Normalized Etsy credential payload.
        timeout: Request timeout in seconds.
    """

    def __init__(self, config: EtsyConfig, timeout: int = 60):
        log_action(f"Initializing Etsy client for shop '{config.shop_id}'")
        self._config: EtsyConfig = config
        self._timeout: int = timeout

    def find_listing_id_by_title(self, title: str) -> int | None:
        """Find an active Etsy listing by exact title match.

        Args:
            title: Listing title to find.

        Returns:
            The Etsy listing id when found; otherwise None.
        """
        log_action(f"Searching Etsy active listings for title '{title}'")
        normalized_title: str = title.strip().lower()
        offset: int = 0
        limit: int = 100

        while True:
            response: requests.Response = self._request(
                method="GET",
                url=(
                    f"{constants.ETSY_API_BASE_URL}/shops/{self._config.shop_id}/listings/active"
                ),
                params={"limit": limit, "offset": offset},
            )
            payload: Dict[str, Any] = response.json()
            results: List[Dict[str, Any]] = payload.get("results", [])
            for listing in results:
                listing_title: str = str(listing.get("title", "")).strip().lower()
                if listing_title != normalized_title:
                    continue
                listing_id: Any = listing.get("listing_id")
                if isinstance(listing_id, int):
                    return listing_id
                if isinstance(listing_id, str) and listing_id.isdigit():
                    return int(listing_id)

            if len(results) < limit:
                return None
            offset += limit

    def upload_listing_image(
        self, listing_id: int, image_path: Path, make_primary: bool
    ) -> Dict[str, Any]:
        """Upload an image to an Etsy listing.

        Args:
            listing_id: Etsy listing identifier.
            image_path: Local image file to upload.
            make_primary: Whether to set uploaded image rank to the first position.

        Returns:
            Etsy API response payload.
        """
        log_action(
            f"Uploading mockup '{image_path.name}' to Etsy listing '{listing_id}'"
        )
        file_bytes: bytes = image_path.read_bytes()
        data: Dict[str, str] = {"rank": "1" if make_primary else "999"}
        files: Dict[str, tuple[str, bytes, str]] = {
            "image": (image_path.name, file_bytes, "image/png"),
        }
        response: requests.Response = self._request(
            method="POST",
            url=(
                f"{constants.ETSY_API_BASE_URL}/shops/{self._config.shop_id}/listings/"
                f"{listing_id}/images"
            ),
            data=data,
            files=files,
        )
        return response.json()

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Send an Etsy API request and refresh the access token once on 401.

        Args:
            method: HTTP method.
            url: Target URL.
            **kwargs: Forwarded requests arguments.

        Returns:
            Successful HTTP response.
        """
        log_action(f"Sending Etsy {method} request to '{url}'")
        response: requests.Response = requests.request(
            method=method,
            url=url,
            headers=self._headers(),
            timeout=self._timeout,
            **kwargs,
        )
        if response.status_code != 401:
            response.raise_for_status()
            return response

        log_action("Etsy returned 401; attempting access token refresh")
        self._refresh_access_token()
        retry_response: requests.Response = requests.request(
            method=method,
            url=url,
            headers=self._headers(),
            timeout=self._timeout,
            **kwargs,
        )
        retry_response.raise_for_status()
        return retry_response

    def _headers(self) -> Dict[str, str]:
        """Build standard Etsy request headers.

        Returns:
            Header mapping with Etsy auth values.
        """
        log_action("Building Etsy API request headers")
        return {
            "Authorization": f"Bearer {self._config.access_token}",
            "x-api-key": self._config.api_key,
        }

    def _refresh_access_token(self) -> None:
        """Refresh the Etsy OAuth access token in memory.

        Raises:
            RuntimeError: If the refresh response does not contain a new access token.
        """
        log_action("Refreshing Etsy access token")
        response: requests.Response = requests.post(
            constants.ETSY_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self._config.api_key,
                "client_secret": self._config.shared_secret,
                "refresh_token": self._config.refresh_token,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload: Dict[str, Any] = response.json()
        access_token: str = str(payload.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError("Etsy token refresh returned no access_token")
        self._config.access_token = access_token
