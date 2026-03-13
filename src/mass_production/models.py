"""Data models for mass production pipeline objects."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Idea:
    """Container for a generated idea and its derived title metadata.

    Attributes:
        keyword: Source keyword used to generate the idea.
        original_title: Title returned by the model before versioning.
        title: Versioned title used for storage and listing.
        folder_name: Underscore-based folder slug from title.
        folder_path: Absolute folder path for this idea's artifacts.
        payload: Raw idea JSON payload.
    """

    keyword: str
    original_title: str
    title: str
    folder_name: str
    folder_path: Path
    payload: dict


@dataclass
class EtsyConfig:
    """Normalized Etsy API configuration.

    Attributes:
        api_key: Etsy application keystring used for the x-api-key header.
        shared_secret: Etsy application shared secret.
        refresh_token: OAuth refresh token.
        access_token: OAuth access token.
        shop_id: Etsy shop identifier.
    """
    api_key: str
    shared_secret: str
    refresh_token: str
    access_token: str
    shop_id: str
