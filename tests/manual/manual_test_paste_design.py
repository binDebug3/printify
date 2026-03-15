"""Manual runner for create_default_color_mockup.

This script is manual-only and is not collected by default pytest runs because
its filename does not start with `test_`.

Usage examples:
    python tests/manual/manual_test_paste_design.py
    python tests/manual/manual_test_paste_design.py --color "Light Blue"
    python tests/manual/manual_test_paste_design.py --design-path C:/path/to/design_transparent.png
    python tests/manual/manual_test_paste_design.py --output-dir tests/artifacts
"""

import argparse
import random
import sys
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src"
MASS_PRODUCTION_ROOT = SRC_ROOT / "mass_production"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from schedule.logger_config import log_action  # noqa: E402
from photoshop.design_crop import create_default_color_mockup  # noqa: E402


DEFAULT_COLOR: str = "white"
DEFAULT_OUTPUT_DIR: Path = PROJECT_ROOT / "tests" / "artifacts"
DEFAULT_DESIGN_NAME: str = "design_transparent.png"
IMAGES_DIR: Path = WORKSPACE_ROOT / "data" / "products"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for manual mockup composition.

    Returns:
        Parsed argument namespace.
    """
    log_action("Parsing arguments for manual design paste runner")
    parser = argparse.ArgumentParser(
        description=(
            "Manually run create_default_color_mockup with optional inputs. "
            "If omitted, picks a random design_transparent.png, uses color=white, "
            "and writes to tests/artifacts."
        )
    )
    parser.add_argument(
        "--design-path",
        default=None,
        help="Path to design image. Defaults to random data/products/**/design_transparent.png.",
    )
    parser.add_argument(
        "--color",
        default=DEFAULT_COLOR,
        help=f"Color name for base mockup lookup. Defaults to '{DEFAULT_COLOR}'.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for composed mockup. Defaults to tests/artifacts.",
    )
    return parser.parse_args()


def find_random_design_path() -> Path:
    """Pick one random design_transparent.png from data/products.

    Returns:
        Selected design image path.

    Raises:
        FileNotFoundError: If no design_transparent.png files are found.
    """
    log_action("Selecting random design_transparent.png from data/products")
    candidates = sorted(IMAGES_DIR.rglob(DEFAULT_DESIGN_NAME))
    if not candidates:
        raise FileNotFoundError(
            f"No '{DEFAULT_DESIGN_NAME}' files found under '{IMAGES_DIR}'."
        )
    return random.SystemRandom().choice(candidates)


def resolve_design_path(raw_design_path: Optional[str]) -> Path:
    """Resolve design path from CLI argument or random fallback.

    Args:
        raw_design_path: Optional CLI design path string.

    Returns:
        Resolved design image path.

    Raises:
        FileNotFoundError: If explicit path is missing.
    """
    log_action("Resolving design path for manual paste runner")
    if raw_design_path is None:
        return find_random_design_path()

    design_path = Path(raw_design_path)
    if not design_path.exists():
        raise FileNotFoundError(f"Design image does not exist: '{design_path}'")
    return design_path


def main() -> None:
    """Run manual design-to-mockup composition and print result path."""
    log_action("Starting manual_test_paste_design runner")
    args = parse_args()

    design_path = resolve_design_path(args.design_path)
    color = args.color
    output_dir = Path(args.output_dir)

    log_action(
        f"Running create_default_color_mockup with design='{design_path}', "
        f"color='{color}', output_dir='{output_dir}'"
    )
    output_path = create_default_color_mockup(
        design_path=design_path,
        color=color,
        output_dir=output_dir,
    )

    print(f"Design path: {design_path}")
    print(f"Color: {color}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
