"""Tests for ideas.csv helpers in mass_production.io_utils."""

from datetime import date
import sys
from pathlib import Path

import pandas as pd


MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from photoshop.io_utils import mark_idea_as_published, read_keywords_from_ideas_csv  # noqa: E402


def test_read_keywords_from_ideas_csv_only_includes_used_false(tmp_path):
    """Returns only keywords whose used flag is explicitly false."""
    csv_path = tmp_path / "ideas.csv"
    csv_path.write_text(
        "idea,context,used,shirt_count\n"
        "alpha,cozy winter style,False,0\n"
        "beta,summer beach,true,1\n"
        "gamma,,,0\n"
        "delta,minimal clean lines,FALSE,0\n",
        encoding="utf-8",
    )

    keywords, contexts = read_keywords_from_ideas_csv(csv_path)

    assert keywords == ["alpha", "delta"]
    assert contexts == ["cozy winter style", "minimal clean lines"]


def test_mark_idea_as_published_updates_used_count_and_date(tmp_path):
    """Marks matching used=false rows as published with count and current date."""
    csv_path = tmp_path / "ideas.csv"
    csv_path.write_text(
        "idea,used,shirt_count\nalpha,False,0\nalpha,True,5\nbeta,False,0\n",
        encoding="utf-8",
    )

    updated = mark_idea_as_published(path=csv_path, keyword="alpha", shirt_count=2)

    df = pd.read_csv(csv_path)
    assert updated is True
    assert bool(df.loc[0, "used"])
    assert df.loc[0, "shirt_count"] == 2
    assert df.loc[0, "publication_date"] == date.today().isoformat()
    assert df.loc[1, "shirt_count"] == 5
    assert not bool(df.loc[2, "used"])


def test_mark_idea_as_published_returns_false_when_no_used_false_match(tmp_path):
    """Does not mutate the file when the keyword has no used=false row."""
    csv_path = tmp_path / "ideas.csv"
    csv_path.write_text(
        "idea,used,shirt_count\nalpha,True,1\nbeta,True,2\n",
        encoding="utf-8",
    )

    updated = mark_idea_as_published(path=csv_path, keyword="alpha", shirt_count=2)

    assert updated is False
    df = pd.read_csv(csv_path)
    assert "publication_date" not in df.columns
