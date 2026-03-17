"""I/O and formatting helpers for mass production workflows."""

import json
import re
from pathlib import Path
from typing import Any, List

from config import constants
from product.models import Idea
from schedule.logger_config import log_action


def cut(path: Path | str, separator: str = "automation") -> str:
    """
    Split a Path or string by a separator and return the last element.

    Args:
        path: The input Path or string to split.
        separator: The separator to use for splitting.

    Returns:
        The last element after splitting the Path as a string.

    """
    path_str: str = str(path)
    parts: List[str] = path_str.split(separator)
    return parts[-1] if parts else path_str


def read_text(path: Path) -> str:
    """Read UTF-8 text from a file.

    Args:
        path: Path to the input file.

    Returns:
        The full file text.
    """
    log_action(f"Reading text from '{cut(path)}'")
    return path.read_text(encoding="utf-8").strip()


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text to a file, creating directories first.

    Args:
        path: Destination file path.
        content: Text to write.
    """
    log_action(f"Writing text to '{cut(path)}'")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_json(path: Path) -> Any:
    """Read JSON from disk.

    Args:
        path: JSON file path.

    Returns:
        Parsed JSON value.
    """
    log_action(f"Reading JSON from '{cut(path)}'")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    """Write JSON to disk with stable pretty formatting.

    Args:
        path: Destination JSON path.
        value: Serializable payload.
    """
    log_action(f"Writing JSON to '{cut(path)}'")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=True)


def write_bytes(path: Path, data: bytes) -> None:
    """Write raw bytes to disk.

    Args:
        path: Destination file path.
        data: Byte payload.
    """
    log_action(f"Writing bytes to '{cut(path)}'")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def slugify_title(title: str) -> str:
    """Create underscore-based folder names from titles.

    Args:
        title: Source title.

    Returns:
        Safe folder slug using underscores.
    """
    log_action(f"Slugifying title '{title}'")
    cleaned: str = re.sub(r"[^A-Za-z0-9 ]+", "", title).strip()
    cleaned: str = re.sub(r"\s+", "_", cleaned)
    return cleaned or "untitled"


def increment_or_append_title_number(title: str) -> str:
    """Increment trailing number or append one when absent.

    Args:
        title: Input title.

    Returns:
        Versioned title with trailing integer incremented or appended.
    """
    log_action(f"Incrementing or appending number in title '{title}'")
    match = re.match(r"^(.*?)(?:\s+(\d+))?$", title.strip())
    if not match:
        return f"{title.strip()} 1"

    base: str = (match.group(1) or "").strip()
    number: str = match.group(2)
    if number is None:
        return f"{base} 1"
    return f"{base} {int(number) + 1}"


def unique_versioned_title(title: str, products_dir: Path) -> str:
    """
    Produce a unique title based on numbering rules and folder collisions.

    Args:
        title: Input title from idea generation.
        products_dir: Base output directory where folders are created.

    Returns:
        Unique versioned title.

    """
    log_action(
        f"Generating unique versioned title for '{title}' in '{cut(products_dir)}'"
    )
    slug: str = slugify_title(title)
    candidate: str = title

    if (products_dir / slug).exists():
        candidate = increment_or_append_title_number(title)
        while (products_dir / slugify_title(candidate)).exists():
            candidate = increment_or_append_title_number(candidate)
    return candidate


def save_idea_json(idea: Idea) -> None:
    """Save per-idea JSON output.

    Args:
        idea: Idea payload object.
    """
    write_json(idea.folder_path / "ideas.json", [idea.payload])
    log_action(
        f"Saved idea JSON for '{idea.title}' to '{cut(idea.folder_path / 'ideas.json')}'"
    )


def save_final_mockup_image(idea: Idea, mockup_cropped_path: Path) -> Path:
    """Save the final cropped mockup into the shared outputs directory.

    Args:
        idea: Idea payload object.
        mockup_cropped_path: Path to the final cropped mockup image.

    Returns:
        Destination path for the saved shared mockup image.
    """
    constants.ALL_FINAL_MOCKUPS_DIR.mkdir(parents=True, exist_ok=True)
    destination_path: Path = (
        constants.ALL_FINAL_MOCKUPS_DIR / f"{slugify_title(idea.title)}.png"
    )
    write_bytes(destination_path, mockup_cropped_path.read_bytes())
    log_action(f"Saved final mockup for '{idea.title}' to '{cut(destination_path)}'")
    return destination_path
