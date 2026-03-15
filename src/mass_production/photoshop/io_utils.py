"""I/O and formatting helpers for mass production workflows."""

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, List

import pandas as pd
from PIL import Image
from schedule.logger_config import log_action


def cut(path: Path, separator: str = "automation") -> str:
    """
    Split a Path by a separator and return the last element.

    Args:
        path: The input Path to split.
        separator: The separator to use for splitting.

    Returns:
        The last element after splitting the Path as a string.
    """
    parts: List[str] = str(path).split(separator)
    return parts[-1] if parts else str(path)


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
    log_action(f"Writing text to '{path}'")
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


def read_keywords_from_ideas_csv(path: Path, limit: int | None = None) -> List[str]:
    """Load unused keywords from ideas.csv.

    Args:
        path: CSV path with columns including idea and used.
        limit: Optional maximum keyword count.

    Returns:
        Ordered list of unused keyword strings.
    """
    log_action(f"Reading keywords from '{cut(path)}' with limit={limit}")
    ideas_df: pd.DataFrame = pd.read_csv(path)
    if "idea" not in ideas_df.columns or "used" not in ideas_df.columns:
        return []

    keyword_series: pd.Series = ideas_df["idea"].astype(str).str.strip()
    used_series: pd.Series = ideas_df["used"].astype(str).str.strip().str.lower()
    unused_mask: pd.Series = (keyword_series != "") & (used_series == "false")
    keywords: List[str] = keyword_series.loc[unused_mask].tolist()
    if limit is not None:
        return keywords[:limit]
    return keywords


def mark_idea_as_published(
    path: Path,
    keyword: str,
    shirt_count: int,
) -> bool:
    """Mark a keyword row as published in ideas.csv.

    Args:
        path: Path to ideas.csv.
        keyword: Keyword value in the idea column to update.
        shirt_count: Number of shirts produced for this keyword.

    Returns:
        True when at least one row was updated; otherwise False.
    """
    log_action(
        f"Updating published keyword '{keyword}' in '{path}' with shirt_count={shirt_count}"
    )
    ideas_df: pd.DataFrame = pd.read_csv(path)
    if "idea" not in ideas_df.columns or "used" not in ideas_df.columns:
        log_action(
            "ideas.csv is missing required columns 'idea' and/or 'used'; skipping update"
        )
        return False

    if "shirt_count" not in ideas_df.columns:
        ideas_df["shirt_count"] = 0
    if "publication_date" not in ideas_df.columns:
        ideas_df["publication_date"] = ""

    keyword_series: pd.Series = ideas_df["idea"].astype(str).str.strip()
    used_series: pd.Series = ideas_df["used"].astype(str).str.strip().str.lower()
    target_mask: pd.Series = (keyword_series == keyword.strip()) & (
        used_series == "false"
    )

    updated_rows: int = int(target_mask.sum())
    if updated_rows == 0:
        log_action(f"No used=false ideas.csv rows found for keyword '{keyword}'")
        return False

    ideas_df.loc[target_mask, "used"] = True
    ideas_df.loc[target_mask, "shirt_count"] = ideas_df.loc[
        target_mask, "shirt_count"
    ].astype(int) + int(shirt_count)
    ideas_df.loc[target_mask, "publication_date"] = date.today().isoformat()
    ideas_df.to_csv(path, index=False)
    log_action(f"Updated {updated_rows} row(s) in ideas.csv for keyword '{keyword}'")
    return True


def parse_json_array(text: str) -> list[dict]:
    """Parse a JSON array from model text output.

    Args:
        text: Raw model response.

    Returns:
        Parsed list of dictionaries.

    Raises:
        ValueError: If no valid JSON array is found.
    """
    log_action("Parsing JSON array from model output")
    stripped: str = text.strip()
    try:
        parsed: str = json.loads(stripped)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", stripped, re.DOTALL)
    if not match:
        raise ValueError("No JSON array found in response")

    parsed: str = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise ValueError("Parsed JSON is not a list")
    return [item for item in parsed if isinstance(item, dict)]


def normalize_keywords_csv_to_json_array(keywords_csv: str, max_len: int) -> list[str]:
    """Normalize a comma-separated keyword string into a JSON-compatible list.

    Args:
        keywords_csv: Comma-separated keywords.
        max_len: Maximum length per keyword.

    Returns:
        List of de-duplicated keywords.
    """
    log_action("Normalizing keywords from CSV to JSON array")
    seen: set[str] = set()
    normalized: List[str] = []
    for part in keywords_csv.split(","):
        keyword: str = part.strip().strip("\"'")
        if not keyword:
            continue
        if len(keyword) > max_len:
            keyword = keyword[:max_len].rstrip()
        key: str = keyword.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(keyword)
    return normalized


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
    log_action(f"Generating unique versioned title for '{title}' in '{cut(products_dir)}'")
    slug: str = slugify_title(title)
    candidate: str = title

    if (products_dir / slug).exists():
        candidate = increment_or_append_title_number(title)
        while (products_dir / slugify_title(candidate)).exists():
            candidate = increment_or_append_title_number(candidate)
    return candidate


def crop_center_percent(input_path: Path, output_path: Path, percent: float) -> None:
    """Center-crop to square, then center-crop again by percent.

    Args:
        input_path: Source image path.
        output_path: Destination path.
        percent: Fraction to retain from the square image along width and height.

    Raises:
        ValueError: If percent is not between 0 and 1 inclusive.
    """
    if percent <= 0 or percent > 1:
        raise ValueError("percent must be > 0 and <= 1")

    log_action(
        f"Center-cropping image '{input_path}' to 1:1, then keeping "
        f"{percent * 100:.1f}% of the centered square into '{output_path}'"
    )
    with Image.open(input_path) as image:
        width, height = image.size

        # Step 1: center crop to square (1:1)
        square_size: int = min(width, height)
        square_left: int = (width - square_size) // 2
        square_top: int = (height - square_size) // 2
        square_right: int = square_left + square_size
        square_bottom: int = square_top + square_size
        square_image = image.crop(
            (square_left, square_top, square_right, square_bottom)
        )

        # Step 2: center crop the square by requested percent (e.g., 0.8 -> keep inner 80%)
        inner_size: int = max(1, int(square_size * percent))
        inner_left: int = (square_size - inner_size) // 2
        inner_top: int = (square_size - inner_size) // 2
        inner_right: int = inner_left + inner_size
        inner_bottom: int = inner_top + inner_size

        cropped = square_image.crop((inner_left, inner_top, inner_right, inner_bottom))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output_path)
