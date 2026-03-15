"""Standalone manual review UI runner using sample folders from ../data/products.

Run from the printify directory with:
python tests/manual/manual_review_ui_runner.py

Optional explicit folders:
python tests/manual/manual_review_ui_runner.py --folders \
    Certified_Dad_Joke_Badge_1 Minimalist_Dad_Shoes_1 Vintage_Official_Seal_1
"""

import argparse
import sys
from pathlib import Path
from typing import Any, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src"
MASS_PRODUCTION_ROOT = PROJECT_ROOT / "src" / "mass_production"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from design_review_ui import review_generated_designs  # noqa: E402
from logger_config import log_action  # noqa: E402


DEFAULT_SAMPLE_FOLDERS: List[str] = [
    "Certified_Dad_Joke_Badge_1",
    "Minimalist_Dad_Shoes_1",
    "Vintage_Official_Seal_1",
]
IMAGES_DIR: Path = WORKSPACE_ROOT / "data" / "products"
DEFAULT_KEYWORD: str = "manual-review-ui-sample"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the standalone review runner.

    Returns:
        Parsed CLI arguments.
    """
    log_action("Parsing arguments for manual review UI runner")
    parser = argparse.ArgumentParser(
        description="Open the browser-based manual design review UI using sample image folders.",
    )
    parser.add_argument(
        "--folders",
        nargs="+",
        default=DEFAULT_SAMPLE_FOLDERS,
        help="Folder names under ../data/products to include in the review UI.",
    )
    parser.add_argument(
        "--keyword",
        default=DEFAULT_KEYWORD,
        help="Keyword label shown in the review UI header.",
    )
    return parser.parse_args()


def _build_review_entry(folder_name: str, review_index: int) -> dict[str, Any]:
    """Build one design review payload entry from a generated image folder.

    Args:
        folder_name: Folder under ../data/products.
        review_index: Stable numeric index used by the review UI.

    Returns:
        Review payload entry compatible with review_generated_designs().

    Raises:
        FileNotFoundError: If the folder or design image does not exist.
    """
    log_action(f"Building manual review entry for folder '{folder_name}'")
    folder_path: Path = IMAGES_DIR / folder_name
    design_path: Path = folder_path / "design.png"

    if not folder_path.exists():
        raise FileNotFoundError(f"Sample folder does not exist: {folder_path}")
    if not design_path.exists():
        raise FileNotFoundError(f"Sample design image does not exist: {design_path}")

    return {
        "index": review_index,
        "idea_index": review_index,
        "title": folder_name.replace("_", " "),
        "retry_count": 0,
        "image_path": str(design_path),
    }


def build_review_entries(folder_names: list[str]) -> list[dict[str, Any]]:
    """Build review payload entries from a list of sample folder names.

    Args:
        folder_names: Folder names under ../data/products.

    Returns:
        Review UI payload entries.
    """
    log_action("Building manual review UI payload from sample image folders")
    return [
        _build_review_entry(folder_name=folder_name, review_index=index)
        for index, folder_name in enumerate(folder_names)
    ]


def main() -> None:
    """Run the standalone manual review UI against sample image folders.

    This opens the same browser UI used by the pipeline, but without running
    generation, filtering, background removal, or publishing steps.
    """
    log_action("Starting standalone manual review UI runner")
    args = parse_args()
    review_entries: list[dict[str, Any]] = build_review_entries(args.folders)

    print("Opening manual review UI with these folders:")
    for entry in review_entries:
        print(f"- {entry['title']}")

    decisions: dict[int, str] = review_generated_designs(
        keyword=args.keyword,
        designs=review_entries,
    )
    selected_actions: list[str] = [
        f"{review_entries[index]['title']}: {decisions.get(index, 'keep')}"
        for index in range(len(review_entries))
    ]

    print("Submitted decisions:")
    for line in selected_actions:
        print(f"- {line}")


if __name__ == "__main__":
    main()
