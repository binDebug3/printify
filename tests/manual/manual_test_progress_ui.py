"""Manual simulator for the mass production progress dashboard.

Run from the printify directory with:
python tests/manual/manual_test_progress_ui.py

This script does not call external APIs and does not write or modify any files.
It only reads existing image artifacts under ../data/products and streams fake
pipeline progress updates into the dashboard UI.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT: Path = PROJECT_ROOT.parent
SRC_ROOT: Path = PROJECT_ROOT / "src"
MASS_PRODUCTION_ROOT: Path = SRC_ROOT / "mass_production"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from logger_config import log_action  # noqa: E402
from ui.progress_dashboard import PipelineProgressDashboard  # noqa: E402


DEFAULT_STAGE_DELAY_SECONDS: float = 0.8
DEFAULT_PRODUCT_DELAY_SECONDS: float = 1.0
DEFAULT_HOLD_SECONDS: int = 20
DEFAULT_KEYWORD_PREFIX: str = "manual-progress-ui"


@dataclass
class ProductAssets:
    """Container for product folder metadata and image slot mappings.

    Attributes:
        folder_name: Product folder name under data/products.
        folder_path: Product folder path.
        image_slots: Mapping of UI image slot names to image paths.
    """

    folder_name: str
    folder_path: Path
    image_slots: Dict[str, Path]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the manual progress UI simulator.

    Returns:
        Parsed command-line arguments.
    """
    log_action("Parsing arguments for manual progress UI simulator")
    parser = argparse.ArgumentParser(
        description=(
            "Open the progress UI and simulate pipeline progress using local images from "
            "data/products."
        )
    )
    parser.add_argument(
        "--max-products",
        type=int,
        default=0,
        help="Maximum product folders to simulate. 0 means all folders.",
    )
    parser.add_argument(
        "--stage-delay",
        type=float,
        default=DEFAULT_STAGE_DELAY_SECONDS,
        help="Delay in seconds between simulated stage updates.",
    )
    parser.add_argument(
        "--product-delay",
        type=float,
        default=DEFAULT_PRODUCT_DELAY_SECONDS,
        help="Delay in seconds after each simulated product completes.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=DEFAULT_HOLD_SECONDS,
        help="Seconds to keep UI open after simulation completes.",
    )
    parser.add_argument(
        "--inject-errors-every",
        type=int,
        default=0,
        help=(
            "Inject a fake error every N products to preview error panel behavior. "
            "0 disables injection."
        ),
    )
    return parser.parse_args()


def _first_existing(paths: List[Path]) -> Optional[Path]:
    """Return the first existing path from a candidate list.

    Args:
        paths: Candidate paths in priority order.

    Returns:
        First existing path, or None when no path exists.
    """
    log_action("Selecting first existing image from candidates")
    for path in paths:
        if path.exists():
            return path
    return None


def _collect_assets_for_folder(folder_path: Path) -> Optional[ProductAssets]:
    """Build image slot mapping for a single product folder.

    Args:
        folder_path: Product folder path under data/products.

    Returns:
        ProductAssets when at least one image exists, otherwise None.
    """
    log_action(f"Collecting product assets for folder '{folder_path.name}'")

    raw_design_path = folder_path / "design.png"
    transparent_design_path = folder_path / "design_transparent.png"

    uncropped_mockups: List[Path] = sorted(
        path for path in folder_path.glob("mockup_*.png") if "_cropped" not in path.name
    )
    cropped_mockups: List[Path] = sorted(folder_path.glob("mockup_*_cropped.png"))

    default_mockup_path: Optional[Path] = _first_existing(uncropped_mockups)
    generated_mockup_path: Optional[Path] = _first_existing(uncropped_mockups)
    cropped_mockup_path: Optional[Path] = _first_existing(cropped_mockups)

    if cropped_mockup_path is None and (folder_path / "mockup_cropped.png").exists():
        cropped_mockup_path = folder_path / "mockup_cropped.png"

    image_slots: Dict[str, Path] = {}
    if raw_design_path.exists():
        image_slots["raw_design"] = raw_design_path
    if transparent_design_path.exists():
        image_slots["transparent_design"] = transparent_design_path
    if default_mockup_path is not None:
        image_slots["default_mockup"] = default_mockup_path
    if generated_mockup_path is not None:
        image_slots["generated_mockup"] = generated_mockup_path
    if cropped_mockup_path is not None:
        image_slots["cropped_mockup"] = cropped_mockup_path

    if not image_slots:
        return None

    return ProductAssets(
        folder_name=folder_path.name,
        folder_path=folder_path,
        image_slots=image_slots,
    )


def discover_products(max_products: int) -> List[ProductAssets]:
    """Discover product folders and collect image assets for simulation.

    Args:
        max_products: Maximum products to include. 0 means all.

    Returns:
        Ordered list of discovered products with asset mappings.
    """
    log_action("Discovering local products for progress UI simulation")
    products_dir: Path = WORKSPACE_ROOT / "data" / "products"
    if not products_dir.exists():
        raise FileNotFoundError(f"Products directory does not exist: {products_dir}")

    discovered: List[ProductAssets] = []
    for folder_path in sorted(products_dir.iterdir()):
        if not folder_path.is_dir():
            continue
        assets = _collect_assets_for_folder(folder_path)
        if assets is None:
            continue
        discovered.append(assets)
        if max_products > 0 and len(discovered) >= max_products:
            break

    return discovered


def run_manual_simulation(args: argparse.Namespace) -> None:
    """Run local progress simulation against discovered product images.

    Args:
        args: Parsed command-line arguments controlling simulation timing.
    """
    log_action("Starting manual progress UI simulation")
    products: List[ProductAssets] = discover_products(
        max_products=int(args.max_products)
    )
    if not products:
        raise RuntimeError(
            "No product folders with usable images were found under data/products."
        )

    stage_delay: float = max(0.0, float(args.stage_delay))
    product_delay: float = max(0.0, float(args.product_delay))
    hold_seconds: int = max(0, int(args.hold_seconds))
    inject_errors_every: int = max(0, int(args.inject_errors_every))

    dashboard = PipelineProgressDashboard(enabled=True)
    dashboard.set_stage("Manual simulation started")
    dashboard.set_total_ideas(len(products))

    try:
        for index, product in enumerate(products, start=1):
            dashboard.set_keyword(
                keyword=f"{DEFAULT_KEYWORD_PREFIX}-{index}",
                keyword_index=index,
                keyword_total=len(products),
            )
            dashboard.set_idea_name(product.folder_name.replace("_", " "))

            dashboard.set_stage("Generating and filtering ideas (simulated)")
            time.sleep(stage_delay)

            dashboard.set_stage("Generating raw design (simulated)")
            raw_design_path = product.image_slots.get("raw_design")
            if raw_design_path is not None:
                dashboard.update_image("raw_design", raw_design_path)
            time.sleep(stage_delay)

            dashboard.set_stage("Removing background (simulated)")
            transparent_path = product.image_slots.get("transparent_design")
            if transparent_path is not None:
                dashboard.update_image("transparent_design", transparent_path)
            time.sleep(stage_delay)

            dashboard.set_stage("Preparing mockups (simulated)")
            default_mockup_path = product.image_slots.get("default_mockup")
            if default_mockup_path is not None:
                dashboard.update_image("default_mockup", default_mockup_path)
            time.sleep(stage_delay)

            dashboard.set_stage("Generating model mockup (simulated)")
            generated_mockup_path = product.image_slots.get("generated_mockup")
            if generated_mockup_path is not None:
                dashboard.update_image("generated_mockup", generated_mockup_path)
            time.sleep(stage_delay)

            dashboard.set_stage("Cropping final mockup (simulated)")
            cropped_path = product.image_slots.get("cropped_mockup")
            if cropped_path is not None:
                dashboard.update_image("cropped_mockup", cropped_path)
            time.sleep(stage_delay)

            if inject_errors_every > 0 and index % inject_errors_every == 0:
                dashboard.add_error(
                    f"Simulated warning for '{product.folder_name}': transient upload timeout"
                )

            dashboard.set_stage("Uploading and creating product (simulated)")
            dashboard.mark_idea_finished(True)
            time.sleep(product_delay)

        dashboard.set_stage("Simulation complete")
        if hold_seconds > 0:
            log_action(f"Holding dashboard open for {hold_seconds} seconds")
            time.sleep(hold_seconds)
    finally:
        dashboard.close()


def main() -> None:
    """Program entrypoint for manual progress dashboard simulation."""
    log_action("Running manual_test_progress_ui entrypoint")
    args = parse_args()
    run_manual_simulation(args)


if __name__ == "__main__":
    main()
