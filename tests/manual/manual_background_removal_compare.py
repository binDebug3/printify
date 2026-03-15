"""Manual comparison helper for background removal modes.

This script picks a random design image from data/products, then writes three
artifacts for side-by-side review:
1. Original image bytes.
2. Manual mode background removal output.
3. Smart mode background removal output.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import random
import sys
from pathlib import Path

PRINTIFY_ROOT: Path = Path(__file__).resolve().parents[2]
AUTOMATION_ROOT: Path = Path(__file__).resolve().parents[3]
SRC_ROOT: Path = PRINTIFY_ROOT / "src"

try:
    from schedule.logger_config import log_action
    import constants
    from photoshop.remove_bg import RemoveBgClient
except ModuleNotFoundError:
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    mass_production_root: Path = SRC_ROOT / "mass_production"
    if str(mass_production_root) not in sys.path:
        sys.path.insert(0, str(mass_production_root))
    from schedule.logger_config import log_action
    import constants
    from photoshop.remove_bg import RemoveBgClient


DATA_PRODUCTS_DIR: Path = AUTOMATION_ROOT / "data" / "products"
ARTIFACTS_DIR: Path = PRINTIFY_ROOT / "tests" / "artifacts" / "background_removal"


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for manual background comparison.

    Returns:
        Parsed command-line arguments.
    """
    log_action("Parsing manual background comparison CLI arguments")
    parser = argparse.ArgumentParser(
        description=(
            "Pick one random design.png from data/products and save original, "
            "manual, and smart background-removed versions to "
            "tests/artifacts/background_removal."
        )
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible selection.",
    )
    return parser.parse_args()


def _collect_design_paths(products_dir: Path) -> list[Path]:
    """Collect candidate design.png files from product folders.

    Args:
        products_dir: Root data/products directory.

    Returns:
        Sorted list of design image paths.

    Raises:
        FileNotFoundError: If no candidate design files are found.
    """
    log_action(f"Collecting design.png candidates from '{products_dir}'")
    design_paths: list[Path] = sorted(products_dir.glob("*/design.png"))
    if not design_paths:
        raise FileNotFoundError(
            f"No design images found matching '{products_dir}/*/design.png'"
        )
    return design_paths


def _pick_random_design(design_paths: list[Path], seed: int | None) -> Path:
    """Pick one random design path.

    Args:
        design_paths: Candidate design paths.
        seed: Optional random seed.

    Returns:
        Chosen design path.
    """
    if seed is not None:
        random.seed(seed)
        log_action(f"Using deterministic random seed {seed} for design selection")

    selected_path: Path = random.choice(design_paths)
    log_action(f"Selected random design image '{selected_path}'")
    return selected_path


def _build_artifact_paths(selected_design: Path) -> tuple[Path, Path, Path]:
    """Build output artifact paths with clear names.

    Args:
        selected_design: Selected design path.

    Returns:
        Tuple of original, manual, and smart output paths.
    """
    log_action("Building artifact file paths for background removal comparison")
    timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name: str = selected_design.parent.name
    base_name: str = f"{folder_name}_{timestamp}"
    original_path: Path = ARTIFACTS_DIR / f"{base_name}_original.png"
    manual_path: Path = ARTIFACTS_DIR / f"{base_name}_manual.png"
    smart_path: Path = ARTIFACTS_DIR / f"{base_name}_smart.png"
    return original_path, manual_path, smart_path


def _run_manual_background_comparison(seed: int | None) -> tuple[Path, Path, Path]:
    """Generate original/manual/smart output artifacts for one random design.

    Args:
        seed: Optional random seed for reproducibility.

    Returns:
        Paths to written original, manual, and smart artifact images.
    """
    log_action("Running manual background removal comparison")
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    design_paths: list[Path] = _collect_design_paths(DATA_PRODUCTS_DIR)
    selected_design: Path = _pick_random_design(design_paths, seed)
    original_path, manual_path, smart_path = _build_artifact_paths(selected_design)

    source_bytes: bytes = selected_design.read_bytes()
    original_path.write_bytes(source_bytes)

    manual_client = RemoveBgClient(
        api_key="",
        endpoint="",
        retries=1,
        removal_mode=constants.REMOVE_BG_MANUAL,
        smart_matte_start=constants.SMART_BG_MATTE_START,
        smart_matte_end=constants.SMART_BG_MATTE_END,
        smart_feather_radius=constants.SMART_BG_FEATHER_RADIUS,
        smart_edge_alpha_min=constants.SMART_BG_EDGE_ALPHA_MIN,
    )
    smart_client = RemoveBgClient(
        api_key="",
        endpoint="",
        retries=1,
        removal_mode=constants.REMOVE_BG_SMART,
        smart_matte_start=constants.SMART_BG_MATTE_START,
        smart_matte_end=constants.SMART_BG_MATTE_END,
        smart_feather_radius=constants.SMART_BG_FEATHER_RADIUS,
        smart_edge_alpha_min=constants.SMART_BG_EDGE_ALPHA_MIN,
    )

    manual_bytes: bytes = manual_client.remove_background(source_bytes)
    smart_bytes: bytes = smart_client.remove_background(source_bytes)

    manual_path.write_bytes(manual_bytes)
    smart_path.write_bytes(smart_bytes)

    log_action(
        f"Saved background comparison artifacts: '{original_path}', '{manual_path}', "
        f"'{smart_path}'"
    )
    return original_path, manual_path, smart_path


def main() -> None:
    """CLI entry point for manual background removal comparison."""
    log_action("Starting manual background removal comparison script")
    args = _parse_args()
    original_path, manual_path, smart_path = _run_manual_background_comparison(
        seed=args.seed
    )
    print(f"Original: {original_path}")
    print(f"Manual:   {manual_path}")
    print(f"Smart:    {smart_path}")


if __name__ == "__main__":
    main()
