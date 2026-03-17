"""Manual viewer for shirt color selection mockups.

Run manually from the printify directory:
python tests/manual/manual_test_shirt_picker.py

This manual script:
1. Deep-searches data/products for design_transparent.png files.
2. Selects a shirt color with pick_mockup_shirt.
3. Generates a default pasted mockup via create_default_color_mockup.
4. Shows generated mockups beside existing mockup_*_cropped.png images in a
   keyboard-friendly Tkinter review UI.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import ttk
from typing import List, Optional

from PIL import Image, ImageTk


PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT: Path = PROJECT_ROOT.parent
SRC_ROOT: Path = PROJECT_ROOT / "src"
MASS_PRODUCTION_ROOT: Path = SRC_ROOT / "mass_production"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

from photoshop.design_crop import create_default_color_mockup  # noqa: E402
from photoshop.pick_mockup_shirt import pick_mockup_shirt  # noqa: E402
from schedule.logger_config import log_action  # noqa: E402
from file_tools.io_utils import cut  # noqa: E402


DESIGN_FILE_NAME: str = "design_transparent.png"
DEFAULT_OUTPUT_DIR: Path = PROJECT_ROOT / "tests" / "artifacts" / "color_selection"
CANVAS_MARGIN_PX: int = 24
MIN_CANVAS_DIMENSION: int = 100
WINDOW_WIDTH_RATIO: float = 0.94
WINDOW_HEIGHT_RATIO: float = 0.90
TITLE_FONT: tuple[str, int, str] = ("Segoe UI", 16, "bold")
META_FONT: tuple[str, int] = ("Segoe UI", 10)
SUBTITLE_FONT: tuple[str, int, str] = ("Segoe UI", 10, "bold")
BG_COLOR: str = "#f7f9fc"
CARD_BG_COLOR: str = "#ffffff"
TEXT_COLOR: str = "#1f2937"
ACCENT_COLOR: str = "#2563eb"


@dataclass
class ShirtReviewItem:
    """Container holding assets and metadata for one design review row.

    Attributes:
        design_name: Human-readable design name.
        design_path: Path to design_transparent.png.
        selected_shirt_color: Selected shirt color key from base mockup stem.
        generated_mockup_path: Generated pasted mockup image path.
        existing_cropped_path: Existing mockup_*_cropped.png path in same folder.
        folder_path: Product idea folder path.
    """

    design_name: str
    design_path: Path
    selected_shirt_color: str
    generated_mockup_path: Path
    existing_cropped_path: Optional[Path]
    folder_path: Path


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for manual shirt review generation.

    Returns:
        Parsed command-line arguments.
    """
    log_action("Parsing arguments for manual shirt picker review")
    parser = argparse.ArgumentParser(
        description=(
            "Build shirt-selection mockups for every design_transparent.png and "
            "launch a Tkinter review viewer."
        )
    )
    parser.add_argument(
        "--products-dir",
        type=Path,
        default=WORKSPACE_ROOT / "data" / "products",
        help="Root data/products directory to search recursively.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Destination for generated color-selection mockups.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max number of designs to process (0 means all).",
    )
    return parser.parse_args()


def _slugify(text: str) -> str:
    """Convert text into a lowercase underscore slug.

    Args:
        text: Source text.

    Returns:
        Lowercase slug suitable for filenames.
    """
    log_action(f"Slugifying design name '{text}' for artifact naming")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return cleaned or "unnamed_design"


def _discover_design_paths(products_dir: Path, limit: int) -> List[Path]:
    """Find all design_transparent.png files in products folder hierarchy.

    Args:
        products_dir: Root products directory.
        limit: Maximum files to include; 0 means no limit.

    Returns:
        Sorted list of matching design paths.

    Raises:
        FileNotFoundError: If products directory does not exist.
    """
    log_action(f"Discovering '{cut(DESIGN_FILE_NAME)}' files under '{cut(products_dir)}'")
    if not products_dir.exists():
        raise FileNotFoundError(f"Products directory does not exist: '{cut(products_dir)}'")

    discovered: List[Path] = sorted(products_dir.rglob(DESIGN_FILE_NAME))
    if limit > 0:
        discovered = discovered[:limit]
    log_action(f"Discovered {len(discovered)} design_transparent file(s)")
    return discovered


def _resolve_existing_cropped_mockup(
    folder_path: Path,
    selected_shirt_color: str,
) -> Optional[Path]:
    """Choose an existing cropped mockup from the same product folder.

    Prefers color-matching files when possible and falls back to the first
    mockup_*_cropped.png from that same folder.

    Args:
        folder_path: Folder that contains design_transparent.png.
        selected_shirt_color: Chosen shirt color key.

    Returns:
        Matched cropped mockup path, or None when unavailable.
    """
    log_action(
        "Resolving sibling cropped mockup in "
        f"'{folder_path.name}' for color '{selected_shirt_color}'"
    )
    candidates: List[Path] = sorted(folder_path.glob("mockup_*_cropped.png"))
    if not candidates:
        return None

    color_slug = _slugify(selected_shirt_color)
    for candidate in candidates:
        candidate_slug = _slugify(candidate.stem)
        if color_slug and color_slug in candidate_slug:
            return candidate

    return candidates[0]


def _build_review_item(design_path: Path, output_dir: Path) -> ShirtReviewItem:
    """Generate one review item with selected shirt and composed mockup.

    Args:
        design_path: Path to design_transparent.png.
        output_dir: Destination folder for generated artifacts.

    Returns:
        Prepared ShirtReviewItem with generated and existing image paths.
    """
    log_action(f"Building review item for design '{cut(design_path)}'")
    folder_path: Path = design_path.parent
    design_name: str = folder_path.name

    mockup_shirt_path: Path = pick_mockup_shirt(design_path)
    selected_shirt_color: str = mockup_shirt_path.stem

    generated_default_path: Path = create_default_color_mockup(
        design_path=design_path,
        mockup_shirt=mockup_shirt_path,
        output_dir=output_dir,
    )
    final_output_path: Path = output_dir / (
        f"{_slugify(design_name)}_{_slugify(selected_shirt_color)}.png"
    )
    generated_default_path.replace(final_output_path)

    existing_cropped_path: Optional[Path] = _resolve_existing_cropped_mockup(
        folder_path=folder_path,
        selected_shirt_color=selected_shirt_color,
    )

    return ShirtReviewItem(
        design_name=design_name,
        design_path=design_path,
        selected_shirt_color=selected_shirt_color,
        generated_mockup_path=final_output_path,
        existing_cropped_path=existing_cropped_path,
        folder_path=folder_path,
    )


def _prepare_review_items(
    products_dir: Path,
    output_dir: Path,
    limit: int,
) -> List[ShirtReviewItem]:
    """Prepare generated artifacts and metadata for all discovered designs.

    Args:
        products_dir: Root products directory.
        output_dir: Destination directory for generated mockups.
        limit: Maximum number of designs to process; 0 means all.

    Returns:
        List of generated review items.

    Raises:
        RuntimeError: If no design files are discovered.
    """
    log_action("Preparing review items for manual shirt picker UI")
    output_dir.mkdir(parents=True, exist_ok=True)
    design_paths: List[Path] = _discover_design_paths(products_dir, limit)
    if not design_paths:
        raise RuntimeError(
            f"No '{DESIGN_FILE_NAME}' files found under '{products_dir}'"
        )

    items: List[ShirtReviewItem] = []
    for design_path in design_paths:
        try:
            items.append(_build_review_item(design_path, output_dir))
        except Exception as exc:  # noqa: BLE001
            log_action(f"Skipping '{design_path}' due to generation error: {exc}")

    if not items:
        raise RuntimeError("No review items could be generated")

    log_action(f"Prepared {len(items)} review item(s)")
    return items


def _fit_image_to_box(image: Image.Image, width: int, height: int) -> Image.Image:
    """Resize image to fit within target dimensions while preserving aspect ratio.

    Args:
        image: Source image.
        width: Max width.
        height: Max height.

    Returns:
        Resized Pillow image.
    """
    log_action(f"Resizing image to fit box {width}x{height}")
    target_width: int = max(MIN_CANVAS_DIMENSION, width)
    target_height: int = max(MIN_CANVAS_DIMENSION, height)
    scale = min(target_width / image.width, target_height / image.height)
    resized_width = max(1, int(image.width * scale))
    resized_height = max(1, int(image.height * scale))
    return image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)


class ShirtPickerViewer:
    """Interactive Tkinter viewer for generated shirt selection mockups."""

    def __init__(self, items: List[ShirtReviewItem]):
        """Initialize the viewer window and UI widgets.

        Args:
            items: Ordered review items to display.
        """
        log_action("Initializing shirt picker manual review UI")
        self.items: List[ShirtReviewItem] = items
        self.index: int = 0
        self.generated_photo: Optional[ImageTk.PhotoImage] = None
        self.existing_photo: Optional[ImageTk.PhotoImage] = None

        self.root = tk.Tk()
        self.root.title("Shirt Picker Review")
        self.root.configure(bg=BG_COLOR)

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = int(screen_width * WINDOW_WIDTH_RATIO)
        height = int(screen_height * WINDOW_HEIGHT_RATIO)
        x_offset = max(0, (screen_width - width) // 2)
        y_offset = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x_offset}+{y_offset}")
        self.root.minsize(900, 600)

        self._build_layout()
        self._bind_events()
        self.root.after(50, self.render_current_item)

    def _build_layout(self) -> None:
        """Construct a balanced layout that keeps controls visible on screen."""
        log_action("Building Tkinter layout for shirt picker review")
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Title.TLabel", font=TITLE_FONT, foreground=TEXT_COLOR)
        style.configure("Meta.TLabel", font=META_FONT, foreground=TEXT_COLOR)
        style.configure("Subtitle.TLabel", font=SUBTITLE_FONT, foreground=TEXT_COLOR)

        header = ttk.Frame(container)
        header.pack(fill=tk.X, pady=(0, 8))

        self.title_label = ttk.Label(header, style="Title.TLabel")
        self.title_label.pack(side=tk.LEFT, anchor=tk.W)

        self.counter_label = ttk.Label(header, style="Meta.TLabel")
        self.counter_label.pack(side=tk.RIGHT, anchor=tk.E)

        meta = ttk.Frame(container)
        meta.pack(fill=tk.X, pady=(0, 8))

        self.color_label = ttk.Label(meta, style="Meta.TLabel")
        self.color_label.pack(side=tk.LEFT, padx=(0, 16))

        self.path_label = ttk.Label(meta, style="Meta.TLabel")
        self.path_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        images_row = ttk.Frame(container)
        images_row.pack(fill=tk.BOTH, expand=True)
        images_row.columnconfigure(0, weight=1)
        images_row.columnconfigure(1, weight=1)
        images_row.rowconfigure(1, weight=1)

        generated_title = ttk.Label(
            images_row,
            text="Generated Pasted Mockup",
            style="Subtitle.TLabel",
        )
        generated_title.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))

        existing_title = ttk.Label(
            images_row,
            text="Existing Folder Cropped Mockup",
            style="Subtitle.TLabel",
        )
        existing_title.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 4))

        self.generated_canvas = tk.Canvas(
            images_row,
            bg=CARD_BG_COLOR,
            highlightthickness=1,
            highlightbackground="#d6dbe4",
        )
        self.generated_canvas.grid(row=1, column=0, sticky="nsew", padx=(0, 8))

        self.existing_canvas = tk.Canvas(
            images_row,
            bg=CARD_BG_COLOR,
            highlightthickness=1,
            highlightbackground="#d6dbe4",
        )
        self.existing_canvas.grid(row=1, column=1, sticky="nsew", padx=(8, 0))

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X, pady=(10, 0))

        self.prev_button = tk.Button(
            controls,
            text="< Previous",
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT_COLOR,
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            command=self.show_previous,
        )
        self.prev_button.pack(side=tk.LEFT)

        self.next_button = tk.Button(
            controls,
            text="Next >",
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT_COLOR,
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            command=self.show_next,
        )
        self.next_button.pack(side=tk.LEFT, padx=(8, 0))

        self.hint_label = ttk.Label(
            controls,
            text="Use Left and Right arrow keys to navigate",
            style="Meta.TLabel",
        )
        self.hint_label.pack(side=tk.RIGHT)

    def _bind_events(self) -> None:
        """Bind keyboard and resize events for responsive navigation."""
        log_action("Binding keyboard and resize events for review UI")
        self.root.bind("<Left>", lambda _event: self.show_previous())
        self.root.bind("<Right>", lambda _event: self.show_next())
        self.root.bind("<Configure>", lambda _event: self.render_current_item())

    def _draw_image_on_canvas(
        self,
        canvas: tk.Canvas,
        path: Optional[Path],
    ) -> Optional[ImageTk.PhotoImage]:
        """Draw an image on the given canvas, scaled to fit.

        Args:
            canvas: Target Tkinter canvas.
            path: Optional source image path.

        Returns:
            Tk photo handle when an image is drawn; otherwise None.
        """
        canvas.delete("all")
        canvas_width = max(
            MIN_CANVAS_DIMENSION, canvas.winfo_width() - CANVAS_MARGIN_PX
        )
        canvas_height = max(
            MIN_CANVAS_DIMENSION, canvas.winfo_height() - CANVAS_MARGIN_PX
        )

        if path is None or not path.exists():
            canvas.create_text(
                max(40, canvas.winfo_width() // 2),
                max(40, canvas.winfo_height() // 2),
                text="No matching image in folder",
                fill="#6b7280",
                font=("Segoe UI", 11),
            )
            return None

        with Image.open(path) as image:
            resized = _fit_image_to_box(
                image.convert("RGBA"), canvas_width, canvas_height
            )
        photo = ImageTk.PhotoImage(resized)
        canvas.create_image(
            max(40, canvas.winfo_width() // 2),
            max(40, canvas.winfo_height() // 2),
            image=photo,
            anchor=tk.CENTER,
        )
        return photo

    def render_current_item(self) -> None:
        """Render metadata and both images for the current index."""
        if not self.items:
            return

        item = self.items[self.index]
        self.title_label.configure(text=f"Design: {item.design_name}")
        self.counter_label.configure(text=f"{self.index + 1} / {len(self.items)}")
        self.color_label.configure(text=f"Selected Shirt: {cut(item.selected_shirt_color)}")
        self.path_label.configure(text=f"Folder: {item.folder_path}")

        self.generated_photo = self._draw_image_on_canvas(
            self.generated_canvas,
            item.generated_mockup_path,
        )
        self.existing_photo = self._draw_image_on_canvas(
            self.existing_canvas,
            item.existing_cropped_path,
        )

    def show_previous(self) -> None:
        """Show the previous review item."""
        if not self.items:
            return
        self.index = (self.index - 1) % len(self.items)
        self.render_current_item()

    def show_next(self) -> None:
        """Show the next review item."""
        if not self.items:
            return
        self.index = (self.index + 1) % len(self.items)
        self.render_current_item()

    def run(self) -> None:
        """Start the Tkinter event loop."""
        log_action("Starting Tkinter main loop for shirt picker review")
        self.root.mainloop()


def main() -> None:
    """Generate artifacts for shirt selection and launch manual review UI."""
    log_action("Starting manual_test_shirt_picker workflow")
    args = _parse_args()
    items = _prepare_review_items(
        products_dir=args.products_dir,
        output_dir=args.output_dir,
        limit=max(0, int(args.limit)),
    )
    print(f"Generated {len(items)} color-selection mockup(s) in: {args.output_dir}")
    viewer = ShirtPickerViewer(items)
    viewer.run()


if __name__ == "__main__":
    main()
