"""Manual-only crop smoke test against a random generated design image.

Run manually from the printify directory:
python -m pytest tests/manual/manual_design_crop.py::test_manual_crop_random_design_image -s

This file is intentionally named so it is not discovered by default pytest runs.
"""

import random
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src"
MASS_PRODUCTION_ROOT = SRC_ROOT / "mass_production"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from schedule.logger_config import log_action  # noqa: E402
import photoshop.design_crop as design_crop_module  # noqa: E402


IMAGES_DIR: Path = WORKSPACE_ROOT / "data" / "products"
DESIGN_IMAGE_NAME: str = "design.png"
ARTIFACTS_DIR: Path = PROJECT_ROOT / "tests" / "artifacts"


def _find_design_images() -> list[Path]:
    """Return all design image paths available for manual crop validation.

    Returns:
        Sorted paths to design.png files under data/products.
    """
    log_action("Searching for generated design images for manual crop test")
    return sorted(IMAGES_DIR.rglob(DESIGN_IMAGE_NAME))


def _save_manual_crop_artifacts(
    original_bytes: bytes,
    cropped_bytes: bytes,
    source_name: str,
) -> None:
    """Save original and cropped images to tests/artifacts for manual inspection.

    Args:
        original_bytes: Raw bytes of the selected source image.
        cropped_bytes: Raw bytes of the cropped image result.
        source_name: Folder name used to identify the source design.
    """
    log_action("Saving manual crop artifacts for visual review")
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_stem: str = f"manual_crop_{source_name}_{timestamp}"
    original_output_path: Path = ARTIFACTS_DIR / f"{file_stem}_original.png"
    cropped_output_path: Path = ARTIFACTS_DIR / f"{file_stem}_cropped.png"

    original_output_path.write_bytes(original_bytes)
    cropped_output_path.write_bytes(cropped_bytes)


def test_manual_crop_random_design_image() -> None:
    """Crop one random generated design image and validate basic crop invariants.

    The test picks one design.png from data/products, runs crop_design_image_to_content,
    then validates that the output dimensions remain valid and never exceed the
    original image bounds.
    """
    log_action("Running manual crop smoke test using a random generated design image")
    design_images = _find_design_images()
    if not design_images:
        pytest.skip(f"No '{DESIGN_IMAGE_NAME}' files found under {IMAGES_DIR}")

    random_path = random.SystemRandom().choice(design_images)
    original_bytes = random_path.read_bytes()
    cropped_bytes = design_crop_module.crop_design_image_to_content(original_bytes)
    _save_manual_crop_artifacts(
        original_bytes=original_bytes,
        cropped_bytes=cropped_bytes,
        source_name=random_path.parent.name,
    )

    with Image.open(BytesIO(original_bytes)) as original_image:
        with Image.open(BytesIO(cropped_bytes)) as cropped_image:
            assert cropped_image.width > 0
            assert cropped_image.height > 0
            assert cropped_image.width <= original_image.width
            assert cropped_image.height <= original_image.height
