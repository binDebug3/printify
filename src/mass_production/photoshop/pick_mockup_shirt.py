"""Pick the best base mockup shirt color for a design image."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Dict, List, Tuple

import numpy as np
from colorspacious import cspace_convert
from PIL import Image
from sklearn.cluster import KMeans

try:
    from config.constants import DATA_DIR
    from schedule.logger_config import log_action
    from file_tools.io_utils import cut
except ModuleNotFoundError:
    MODULE_PATH: Path = Path(__file__).resolve()
    MASS_PRODUCTION_ROOT: Path = MODULE_PATH.parents[1]
    SRC_ROOT: Path = MODULE_PATH.parents[2]
    for candidate in (SRC_ROOT, MASS_PRODUCTION_ROOT):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

    from config.constants import DATA_DIR
    from schedule.logger_config import log_action


SHIRT_COLORS_PATH: Path = DATA_DIR / "base_mockups" / "_shirt_colors.json"
BASE_MOCKUPS_DIR: Path = DATA_DIR / "base_mockups"
MAX_CLUSTER_COUNT: int = 5
COLOR_COVERAGE_THRESHOLD: float = 0.90
DARK_LIGHTNESS_THRESHOLD: float = 50.0
FULLY_OPAQUE_ALPHA: int = 255
KMEANS_RANDOM_STATE: int = 42
KMEANS_N_INIT: int = 10
ANALOGOUS_HUE_LIMIT: float = 120.0
LOW_CHROMA_THRESHOLD: float = 12.0
MAX_DELTA_E_SCORE: float = 80.0
MAX_LIGHTNESS_GAP: float = 45.0
TONAL_LIGHTNESS_SCALE: float = 40.0
COLLISION_DELTA_E_THRESHOLD: float = 18.0
COLLISION_LIGHTNESS_THRESHOLD: float = 15.0
COLLISION_HUE_THRESHOLD: float = 35.0
READABILITY_WEIGHT: float = 0.55
HARMONY_WEIGHT: float = 0.30
TONAL_WEIGHT: float = 0.25
COLLISION_WEIGHT: float = 0.45
RED_POLICY_WEIGHT: float = 1.25
RED_HUE_WINDOW: float = 55.0
GREEN_HUE_CENTER: float = 120.0
GREEN_HUE_WINDOW: float = 50.0
RED_MIN_CHROMA: float = 12.0
NEUTRAL_MAX_CHROMA: float = 18.0
RED_POLICY_ACTIVATION: float = 0.18
RED_LIGHTNESS_SPLIT: float = 55.0
RED_LIGHTNESS_TRANSITION: float = 10.0
DARK_SHIRT_LIGHTNESS_MAX: float = 35.0
LIGHT_SHIRT_LIGHTNESS_MIN: float = 72.0
CHROMA_SCALE: float = 55.0


@dataclass(frozen=True)
class MatchComponents:
    """Normalized scoring components for a shirt/design color match.

    Attributes:
        readability: Perceptual separation between shirt and design colors.
        harmony: Analogous or neutral compatibility between colors.
        tonal: Bonus for darker analogous shirts under lighter designs.
        collision: Penalty for pairings that are too visually similar.
    """

    readability: float
    harmony: float
    tonal: float
    collision: float


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert a hex color string to an integer RGB tuple.

    Args:
        hex_color: Hex string such as '#1a2b3c' or '1a2b3c'.

    Returns:
        Integer RGB tuple with channels in [0, 255].
    """
    cleaned: str = hex_color.lstrip("#")
    return (int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16))


def _rgb_to_hex(rgb: np.ndarray) -> str:
    """Convert a float RGB array to a lowercase hex color string.

    Args:
        rgb: Float array with channel values nominally in [0, 255].

    Returns:
        Lowercase hex string prefixed with '#'.
    """
    r: int = max(0, min(255, int(round(float(rgb[0])))))
    g: int = max(0, min(255, int(round(float(rgb[1])))))
    b: int = max(0, min(255, int(round(float(rgb[2])))))
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb_to_lab(rgb_255: Tuple[int, int, int]) -> np.ndarray:
    """Convert an sRGB color (0–255) to CIE L*a*b* using colorspacious.

    Args:
        rgb_255: Integer RGB tuple with channels in [0, 255].

    Returns:
        Lab array of shape (3,) with L* nominally in [0, 100].
    """
    rgb_1: np.ndarray = np.array(rgb_255, dtype=float) / 255.0
    return cspace_convert(rgb_1, "sRGB1", "CIELab")


def _delta_e(lab1: np.ndarray, lab2: np.ndarray) -> float:
    """Compute Delta E 76 as Euclidean distance in CIE Lab space.

    Args:
        lab1: First CIE L*a*b* color array of shape (3,).
        lab2: Second CIE L*a*b* color array of shape (3,).

    Returns:
        Scalar Delta E distance (higher means more perceptual difference).
    """
    return float(np.sqrt(np.sum((np.asarray(lab1) - np.asarray(lab2)) ** 2)))


def _lab_to_lch(lab: np.ndarray) -> np.ndarray:
    """Convert a Lab color array to LCh values.

    Args:
        lab: CIE L*a*b* color array.

    Returns:
        Array with lightness, chroma, and hue angle in degrees.
    """
    lightness: float = float(lab[0])
    chroma: float = float(np.hypot(lab[1], lab[2]))
    hue: float = float((np.degrees(np.arctan2(lab[2], lab[1])) + 360.0) % 360.0)
    return np.array([lightness, chroma, hue], dtype=float)


def _hue_distance(hue1: float, hue2: float) -> float:
    """Return the minimum circular distance between two hue angles.

    Args:
        hue1: First hue angle in degrees.
        hue2: Second hue angle in degrees.

    Returns:
        Distance in degrees on the hue circle.
    """
    raw_distance: float = abs(hue1 - hue2)
    return min(raw_distance, 360.0 - raw_distance)


def _normalize(value: float, maximum: float) -> float:
    """Clamp a non-negative value into the unit interval.

    Args:
        value: Value to normalize.
        maximum: Upper bound corresponding to 1.0.

    Returns:
        Normalized value in [0.0, 1.0].
    """
    if maximum <= 0.0:
        return 0.0
    return max(0.0, min(value / maximum, 1.0))


def _hue_proximity(hue: float, center: float, window: float) -> float:
    """Compute normalized proximity of a hue to a target hue center.

    Args:
        hue: Hue angle in degrees.
        center: Target hue angle in degrees.
        window: Maximum distance to still receive non-zero score.

    Returns:
        Proximity score in [0.0, 1.0].
    """
    if window <= 0.0:
        return 0.0
    distance: float = _hue_distance(hue, center)
    return max(0.0, 1.0 - (distance / window))


def _red_policy_adjustment(
    shirt_lab: np.ndarray,
    design_lab_colors: List[Tuple[np.ndarray, float]],
    avg_design_l: float,
) -> float:
    """Return a red-specific score adjustment for a shirt candidate.

    For red-leaning designs, this term nudges outcomes toward:
    - darker neutral shirts when the design is light red,
    - lighter neutral or light-red shirts when the design is dark red,
    while penalizing green shirts in both regimes.

    Args:
        shirt_lab: Shirt color in CIE L*a*b*.
        design_lab_colors: Weighted design palette in CIE L*a*b*.
        avg_design_l: Coverage-weighted average design L* value.

    Returns:
        Adjustment term in approximately [-1.0, 1.0].
    """
    red_presence: float = 0.0
    for design_lab, coverage in design_lab_colors:
        design_lch: np.ndarray = _lab_to_lch(design_lab)
        design_hue: float = float(design_lch[2])
        design_chroma: float = float(design_lch[1])
        red_proximity: float = _hue_proximity(design_hue, 0.0, RED_HUE_WINDOW)
        chroma_factor: float = _normalize(
            max(0.0, design_chroma - RED_MIN_CHROMA), CHROMA_SCALE
        )
        red_presence += coverage * red_proximity * chroma_factor

    red_activation: float = _normalize(
        max(0.0, red_presence - RED_POLICY_ACTIVATION),
        1.0 - RED_POLICY_ACTIVATION,
    )
    if red_activation <= 0.0:
        return 0.0

    shirt_lch: np.ndarray = _lab_to_lch(shirt_lab)
    shirt_l: float = float(shirt_lch[0])
    shirt_c: float = float(shirt_lch[1])
    shirt_h: float = float(shirt_lch[2])

    neutral_factor: float = 1.0 - _normalize(shirt_c, NEUTRAL_MAX_CHROMA)
    green_factor: float = _hue_proximity(shirt_h, GREEN_HUE_CENTER, GREEN_HUE_WINDOW)
    green_factor *= _normalize(shirt_c, CHROMA_SCALE)

    dark_factor: float = _normalize(max(0.0, DARK_SHIRT_LIGHTNESS_MAX - shirt_l), 35.0)
    light_factor: float = _normalize(
        max(0.0, shirt_l - LIGHT_SHIRT_LIGHTNESS_MIN),
        100.0 - LIGHT_SHIRT_LIGHTNESS_MIN,
    )
    shirt_red_factor: float = _hue_proximity(shirt_h, 0.0, RED_HUE_WINDOW)
    shirt_red_factor *= _normalize(shirt_c, CHROMA_SCALE)
    lighter_than_design: float = _normalize(max(0.0, shirt_l - avg_design_l), 35.0)

    light_design_strength: float = _normalize(
        avg_design_l - (RED_LIGHTNESS_SPLIT - RED_LIGHTNESS_TRANSITION),
        2.0 * RED_LIGHTNESS_TRANSITION,
    )
    dark_design_strength: float = 1.0 - light_design_strength

    light_design_term: float = (0.85 * dark_factor * neutral_factor) - (
        1.05 * green_factor
    )
    dark_design_term: float = (0.75 * light_factor * neutral_factor) - (
        0.45 * dark_factor
    )
    dark_design_term += 0.60 * shirt_red_factor * lighter_than_design
    dark_design_term -= 0.95 * green_factor

    regime_term: float = light_design_strength * light_design_term
    regime_term += dark_design_strength * dark_design_term
    adjustment: float = red_activation * regime_term
    log_action(
        "Red policy: red_presence=%.2f activation=%.2f regime=%.2f adjustment=%.2f"
        % (red_presence, red_activation, regime_term, adjustment)
    )
    return adjustment


def _score_color_pair(design_lab: np.ndarray, shirt_lab: np.ndarray) -> MatchComponents:
    """Score a single design/shirt color pairing.

    Args:
        design_lab: Design color in CIE L*a*b*.
        shirt_lab: Shirt color in CIE L*a*b*.

    Returns:
        Normalized match components for the pair.
    """
    log_action("Scoring a single design/shirt color pairing")
    design_lch: np.ndarray = _lab_to_lch(design_lab)
    shirt_lch: np.ndarray = _lab_to_lch(shirt_lab)
    delta_e_value: float = _delta_e(design_lab, shirt_lab)
    lightness_gap: float = abs(float(design_lch[0]) - float(shirt_lch[0]))

    chromatic_pair: bool = float(design_lch[1]) >= LOW_CHROMA_THRESHOLD
    chromatic_pair = chromatic_pair and (float(shirt_lch[1]) >= LOW_CHROMA_THRESHOLD)
    hue_gap: float = (
        _hue_distance(float(design_lch[2]), float(shirt_lch[2]))
        if chromatic_pair
        else 0.0
    )
    analogous_score: float = max(0.0, 1.0 - (hue_gap / ANALOGOUS_HUE_LIMIT))
    neutral_bonus: float = 0.35 if not chromatic_pair else 0.0
    harmony: float = min(1.0, analogous_score + neutral_bonus)

    darker_shirt_gap: float = max(0.0, float(design_lch[0]) - float(shirt_lch[0]))
    tonal: float = analogous_score * _normalize(darker_shirt_gap, TONAL_LIGHTNESS_SCALE)
    readability: float = max(
        _normalize(delta_e_value, MAX_DELTA_E_SCORE),
        _normalize(lightness_gap, MAX_LIGHTNESS_GAP),
    )

    collision: float = 0.0
    candidate_collision: bool = delta_e_value < COLLISION_DELTA_E_THRESHOLD
    candidate_collision = candidate_collision and (
        lightness_gap < COLLISION_LIGHTNESS_THRESHOLD
    )
    if candidate_collision:
        delta_closeness: float = 1.0 - _normalize(
            delta_e_value, COLLISION_DELTA_E_THRESHOLD
        )
        lightness_closeness: float = 1.0 - _normalize(
            lightness_gap, COLLISION_LIGHTNESS_THRESHOLD
        )
        if chromatic_pair:
            hue_closeness: float = 1.0 - _normalize(hue_gap, COLLISION_HUE_THRESHOLD)
        else:
            hue_closeness = 1.0
        collision = (
            delta_closeness * lightness_closeness * max(hue_closeness, analogous_score)
        )

    return MatchComponents(
        readability=readability,
        harmony=harmony,
        tonal=tonal,
        collision=collision,
    )


def _is_dark(lab: np.ndarray) -> bool:
    """Return True when a Lab color's L* falls below the dark threshold.

    Args:
        lab: CIE L*a*b* color array.

    Returns:
        True when L* < DARK_LIGHTNESS_THRESHOLD.
    """
    return float(lab[0]) < DARK_LIGHTNESS_THRESHOLD


def _score_shirt_color(
    shirt_lab: np.ndarray,
    design_lab_colors: List[Tuple[np.ndarray, float]],
) -> MatchComponents:
    """Aggregate weighted compatibility metrics from a design palette to a shirt.

    Args:
        shirt_lab: CIE L*a*b* array for the shirt color.
        design_lab_colors: List of (lab_array, coverage_fraction) for design clusters.

    Returns:
        Coverage-weighted normalized match components.
    """
    log_action("Scoring shirt color by weighted harmony and readability")
    readability: float = 0.0
    harmony: float = 0.0
    tonal: float = 0.0
    collision: float = 0.0
    for design_lab, coverage in design_lab_colors:
        pair_score: MatchComponents = _score_color_pair(design_lab, shirt_lab)
        readability += coverage * pair_score.readability
        harmony += coverage * pair_score.harmony
        tonal += coverage * pair_score.tonal
        collision += coverage * pair_score.collision

    return MatchComponents(
        readability=readability,
        harmony=harmony,
        tonal=tonal,
        collision=collision,
    )


def _combine_match_components(components: MatchComponents) -> float:
    """Combine normalized match components into a final ranking score.

    Args:
        components: Weighted compatibility components for a shirt candidate.

    Returns:
        Final ranking score where larger is better.
    """
    score: float = READABILITY_WEIGHT * components.readability
    score += HARMONY_WEIGHT * components.harmony
    score += TONAL_WEIGHT * components.tonal
    score -= COLLISION_WEIGHT * components.collision
    return score


def find_predominant_colors(image_path: Path) -> List[Tuple[str, float]]:
    """Extract 1–5 predominant hex colors from the fully opaque pixels of an image.

    Runs k-means clustering with k=5 on pixels where alpha=255, then returns
    the smallest set of clusters whose cumulative share of opaque pixels reaches
    COLOR_COVERAGE_THRESHOLD (default 90 %), sorted by coverage descending.

    Args:
        image_path: Path to the source image file.

    Returns:
        List of (hex_color, coverage_fraction) pairs sorted by coverage descending.

    Raises:
        ValueError: If the image contains no fully opaque pixels.
    """
    log_action(f"Extracting predominant colors from '{image_path.name}'")
    with Image.open(image_path) as image:
        rgba: np.ndarray = np.array(image.convert("RGBA"), dtype=np.uint8)

    opaque_rgb: np.ndarray = rgba[rgba[:, :, 3] == FULLY_OPAQUE_ALPHA, :3].astype(float)
    if len(opaque_rgb) == 0:
        raise ValueError(f"No fully opaque pixels found in '{image_path}'")

    k: int = min(MAX_CLUSTER_COUNT, len(opaque_rgb))
    kmeans = KMeans(
        n_clusters=k, random_state=KMEANS_RANDOM_STATE, n_init=KMEANS_N_INIT
    )
    labels: np.ndarray = kmeans.fit_predict(opaque_rgb)

    counts: np.ndarray = np.bincount(labels, minlength=k)
    total: int = len(opaque_rgb)
    sorted_indices: List[int] = [int(index) for index in np.argsort(counts)[::-1]]

    selected: List[Tuple[str, float]] = []
    cumulative: int = 0
    for idx in sorted_indices:
        if cumulative / total >= COLOR_COVERAGE_THRESHOLD:
            break
        coverage: float = float(counts[idx]) / float(total)
        selected.append((_rgb_to_hex(kmeans.cluster_centers_[idx]), coverage))
        cumulative += int(counts[idx])

    log_action(
        f"Identified {len(selected)} predominant color(s) covering "
        f"{cumulative / total:.0%} of opaque pixels in '{image_path.name}'"
    )
    return selected


def _load_selected_shirt_colors() -> Dict[str, str]:
    """Load the curated 'selected' shirt colors from the shirt colors JSON.

    Returns:
        Dict mapping shirt name to hex color string.

    Raises:
        FileNotFoundError: If SHIRT_COLORS_PATH does not exist.
        KeyError: If the JSON does not contain a 'selected' key.
    """
    log_action(f"Loading selected shirt colors from '{cut(SHIRT_COLORS_PATH)}'")
    if not SHIRT_COLORS_PATH.exists():
        raise FileNotFoundError(f"Shirt colors file not found: '{SHIRT_COLORS_PATH}'")

    with open(SHIRT_COLORS_PATH, "r", encoding="utf-8") as file_obj:
        data: Dict = json.load(file_obj)

    if "selected" not in data:
        raise KeyError("'selected' key not found in shirt colors JSON")

    return data["selected"]


def rank_shirt_colors(
    design_colors: List[Tuple[str, float]],
    shirt_colors: Dict[str, str],
) -> str:
    """Rank shirt colors by harmony-aware contrast and return the best matching name.

    Converts all colors to CIE Lab/LCh, applies a hard dark-on-dark exclusion,
    then ranks remaining shirts using a composite score that balances
    readability, analogous color harmony, tonal depth, and a similarity penalty.

    Args:
        design_colors: List of (hex_color, coverage_fraction) from the design.
        shirt_colors: Dict mapping shirt name to hex color from the selected set.

    Returns:
        Name of the best-matching shirt color.

    Raises:
        ValueError: If no valid candidates remain after dark-on-dark filtering.
    """
    log_action("Ranking available shirt colors against design palette")
    design_lab_list: List[Tuple[np.ndarray, float]] = [
        (np.array(_rgb_to_lab(_hex_to_rgb(h))), cov) for h, cov in design_colors
    ]
    avg_design_l: float = sum(float(lab[0]) * cov for lab, cov in design_lab_list)
    design_is_dark: bool = avg_design_l < DARK_LIGHTNESS_THRESHOLD

    candidates: Dict[str, float] = {}
    for name, hex_color in shirt_colors.items():
        shirt_lab: np.ndarray = np.array(_rgb_to_lab(_hex_to_rgb(hex_color)))
        if design_is_dark and _is_dark(shirt_lab):
            log_action(f"Excluding dark-on-dark shirt '{name}' (L*={shirt_lab[0]:.1f})")
            continue
        components: MatchComponents = _score_shirt_color(shirt_lab, design_lab_list)
        red_adjustment: float = _red_policy_adjustment(
            shirt_lab=shirt_lab,
            design_lab_colors=design_lab_list,
            avg_design_l=avg_design_l,
        )
        final_score: float = _combine_match_components(components)
        final_score += RED_POLICY_WEIGHT * red_adjustment
        log_action(
            "Candidate shirt '%s': readability=%.2f harmony=%.2f tonal=%.2f "
            "collision=%.2f red_adjust=%.2f final=%.2f"
            % (
                name,
                components.readability,
                components.harmony,
                components.tonal,
                components.collision,
                red_adjustment,
                final_score,
            )
        )
        candidates[name] = final_score

    if not candidates:
        raise ValueError(
            "No valid shirt color candidates remain after dark-on-dark exclusion"
        )

    best: str = max(candidates, key=lambda n: candidates[n])
    log_action(f"Selected shirt color '{best}' (score={candidates[best]:.2f})")
    return best


def pick_mockup_shirt(image_path: Path) -> Path:
    """Pick the best base mockup PNG for a design image.

    Extracts the design's predominant colors from fully opaque pixels, applies
    a hard dark-on-dark filter, then ranks remaining shirt options by
    coverage-weighted Delta E contrast and returns the matching mockup path.

    Args:
        image_path: Path to the design image (transparent PNG recommended).

    Returns:
        Path to the best-matching base mockup PNG in data/base_mockups/.

    Raises:
        ValueError: If no opaque pixels are found or no valid shirt survives filtering.
        FileNotFoundError: If the shirt colors JSON or chosen mockup PNG is missing.
    """
    log_action(f"Picking mockup shirt color for design '{image_path.name}'")
    design_colors: List[Tuple[str, float]] = find_predominant_colors(image_path)
    shirt_options: Dict[str, str] = _load_selected_shirt_colors()
    best_color: str = rank_shirt_colors(design_colors, shirt_options)

    mockup_path: Path = BASE_MOCKUPS_DIR / f"{best_color}.png"
    if not mockup_path.exists():
        raise FileNotFoundError(
            f"Base mockup PNG not found for color '{best_color}': '{mockup_path}'"
        )

    log_action(f"Picked shirt color '{best_color}': '{mockup_path}'")
    return mockup_path


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for shirt color picking.

    Returns:
        Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Pick the best shirt color base mockup for a design image."
    )
    parser.add_argument(
        "image_path",
        type=Path,
        help="Path to the design PNG image.",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point for shirt color picking."""
    log_action("Running pick_mockup_shirt.py as a CLI tool")
    args = _parse_args()
    result_path = pick_mockup_shirt(args.image_path)
    print(f"Best shirt mockup: {result_path}")


if __name__ == "__main__":
    main()
