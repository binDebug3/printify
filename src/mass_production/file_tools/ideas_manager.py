"""
File tools for managing keyword ideas in CSV format, including reading unused ideas and marking 
them as published.
"""

from typing import List
from pathlib import Path
import pandas as pd
from datetime import date

from schedule.logger_config import log_action
from file_tools.io_utils import cut


def read_keywords_from_ideas_csv(
    path: Path,
    limit: int | None = None,
) -> tuple[list[str], list[str]]:
    """Load unused keyword/context pairs from ideas.csv.

    Args:
        path: CSV path with columns including idea and used.
        limit: Optional maximum keyword count.

    Returns:
        Tuple of ordered lists: (keywords, contexts).

        Context values come from the optional context column. When absent or
        blank, context entries are empty strings.
    """
    log_action(f"Reading keywords from '{cut(path)}' with limit={limit}")
    ideas_df: pd.DataFrame = pd.read_csv(path)
    if "idea" not in ideas_df.columns or "used" not in ideas_df.columns:
        return [], []

    keyword_series: pd.Series = ideas_df["idea"].astype(str).str.strip()
    used_series: pd.Series = ideas_df["used"].astype(str).str.strip().str.lower()
    if "context" in ideas_df.columns:
        context_series: pd.Series = (
            ideas_df["context"].fillna("").astype(str).str.split().str.join(" ")
        )
    else:
        context_series = pd.Series([""] * len(ideas_df), index=ideas_df.index)

    unused_mask: pd.Series = (keyword_series != "") & (used_series == "false")
    keywords: list[str] = keyword_series.loc[unused_mask].tolist()
    contexts: list[str] = context_series.loc[unused_mask].tolist()

    if limit is not None:
        return keywords[:limit], contexts[:limit]
    return keywords, contexts


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
        f"Updating published keyword '{keyword}' in '{cut(path)}' with shirt_count={shirt_count}"
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
