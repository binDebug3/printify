"""Visual check for manual background removal using a real generated design image.

Run this test manually to generate image artifacts:

    VISUAL_BG_RUN=1 pytest tests/test_manual_background_visual.py -q -s

Set VISUAL_BG_OPEN=1 to request opening the generated images in the default viewer.
"""

import os
import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASS_PRODUCTION_ROOT = PROJECT_ROOT / "src" / "mass_production"
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from logger_config import log_action  # noqa: E402
import remove_bg as remove_bg_module  # noqa: E402

ARTIFACTS_DIR = PROJECT_ROOT / "tests" / "artifacts"


def _find_sample_design_png() -> Path | None:
    """Find one real design.png in data/images for visual testing.

    Returns:

        A path to the first available design.png, or None if not found.
    """
    log_action("Searching for a sample design.png under data/images")
    images_root = PROJECT_ROOT.parent / "data" / "images"
    for path in sorted(images_root.glob("*/design.png")):
        if path.is_file():
            return path
    return None


def test_manual_background_removal_visual_artifacts() -> None:
    """Create manual-only original and processed artifacts from a real design.png sample.

    The test passes when the artifact is successfully generated. It is intended
    as a manual visual check rather than a strict pixel-perfect assertion.
    """
    if os.getenv("VISUAL_BG_RUN", "0") != "1":
        pytest.skip("Manual-only visual test. Set VISUAL_BG_RUN=1 to run it.")

    log_action("Starting visual manual background-removal test")
    sample_path = _find_sample_design_png()
    if sample_path is None:
        pytest.skip("No design.png found under data/images")

    original_bytes = sample_path.read_bytes()
    remover = remove_bg_module.RemoveBgClient(
        api_key="",
        endpoint="",
        retries=1,
        removal_mode="manual",
    )
    processed_bytes = remover.remove_background(original_bytes)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    folder_name = sample_path.parent.name
    original_artifact = ARTIFACTS_DIR / f"manual_bg_original_{folder_name}.png"
    processed_artifact = ARTIFACTS_DIR / f"manual_bg_removed_{folder_name}.png"
    alpha_mask_artifact = ARTIFACTS_DIR / f"manual_bg_alpha_mask_{folder_name}.png"
    original_artifact.write_bytes(original_bytes)
    processed_artifact.write_bytes(processed_bytes)

    processed_image = Image.open(BytesIO(processed_bytes)).convert("RGBA")
    alpha_values = [pixel[3] for pixel in processed_image.getdata()]
    transparent_pixels = sum(1 for alpha in alpha_values if alpha == 0)
    alpha_mask = processed_image.getchannel("A")
    alpha_mask.save(alpha_mask_artifact)

    log_action(
        f"Saved visual artifacts to '{original_artifact}' and '{processed_artifact}'"
    )
    log_action(
        f"Manual removal transparency stats for '{folder_name}': "
        f"transparent_pixels={transparent_pixels}, total_pixels={len(alpha_values)}"
    )
    print(f"Saved original image: {original_artifact}")
    print(f"Saved processed image: {processed_artifact}")
    print(f"Saved alpha mask image: {alpha_mask_artifact}")
    print(
        "Transparency stats: "
        f"transparent_pixels={transparent_pixels}, total_pixels={len(alpha_values)}"
    )

    if os.getenv("VISUAL_BG_OPEN", "0") == "1":
        log_action("VISUAL_BG_OPEN=1 detected; requesting artifact image open")
        os.startfile(str(original_artifact))
        os.startfile(str(processed_artifact))
        os.startfile(str(alpha_mask_artifact))

    assert original_artifact.exists()
    assert processed_artifact.exists()
    assert alpha_mask_artifact.exists()
    assert transparent_pixels > 0
