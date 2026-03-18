"""Interactive smart background simplifier with bucket-remove editing.

This tool loads an image, applies the smart background removal mode from
mass_production.photoshop.remove_bg, then opens a UI for click-based bucket
removal. Each edit is snapshotted under data/images/bgr_ui as an immutable
history file for safe undo and auditability.
"""

import argparse
from collections import deque
from io import BytesIO
import random
import string
from pathlib import Path
import sys
from typing import Optional

from PIL import Image
from PIL import ImageTk
from PIL import UnidentifiedImageError
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox

try:
    from schedule.logger_config import log_action
    from remove_bg import RemoveBgClient
    from file_tools.io_utils import cut
except ModuleNotFoundError:
    SRC_ROOT = Path(__file__).resolve().parents[2]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from schedule.logger_config import log_action
    from remove_bg import RemoveBgClient
    from file_tools.io_utils import cut


DEFAULT_TOLERANCE: int = 40
DEFAULT_OUTPUT_SUFFIX: str = "_simplified"
HISTORY_DIR_PARTS: tuple[str, str, str] = ("data", "images", "bgr_ui")
FILE_DIALOG_TITLE: str = "Select an image for background simplification"
CANVAS_MAX_WIDTH: int = 1200
CANVAS_MAX_HEIGHT: int = 800
MIN_VISIBLE_ALPHA_RATIO: float = 0.003
CHECKER_TILE_SIZE: int = 12
MIN_ZOOM: float = 0.2
MAX_ZOOM: float = 8.0
ZOOM_STEP: float = 1.12
PAN_DRAG_THRESHOLD: int = 5
IMAGE_FILE_TYPES: list[tuple[str, str]] = [
    (
        "Image files",
        "*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff;*.webp;*.gif",
    ),
    ("All files", "*.*"),
]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """
    Parse command line arguments.

    Args:
        argv: Optional argument list for tests.

    Returns:
        Parsed CLI namespace.
    """
    log_action("Parsing CLI arguments for remove_bg_ui")
    parser = argparse.ArgumentParser(
        description=(
            "Open an interactive smart background simplifier with click bucket removal."
        )
    )
    parser.add_argument(
        "image_path",
        nargs="?",
        help="Path to an image. If omitted, a file picker will open.",
    )
    parser.add_argument(
        "--tolerance",
        type=int,
        default=DEFAULT_TOLERANCE,
        help="Per-channel color tolerance for bucket remove (default: 30).",
    )
    return parser.parse_args(argv)


def prompt_for_image_path() -> Optional[Path]:
    """
    Prompt the user to select an input image.

    Returns:
        Selected image path or None if canceled.
    """
    log_action("Opening file dialog for remove_bg_ui input image selection")
    root: Optional[tk.Tk] = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_path: str = filedialog.askopenfilename(
            title=FILE_DIALOG_TITLE,
            filetypes=IMAGE_FILE_TYPES,
        )
        if not selected_path:
            log_action("Image selection canceled by user")
            return None
        return Path(selected_path)
    finally:
        if root is not None:
            root.destroy()


def validate_image_path(image_path: Path) -> Path:
    """
    Validate and normalize an input path.

    Args:
        image_path: Candidate image path.

    Returns:
        Resolved file path.

    Raises:
        FileNotFoundError: If path is missing.
        IsADirectoryError: If path points to directory.
        ValueError: If file is empty.
    """
    log_action(f"Validating remove_bg_ui input path '{image_path}'")
    resolved_path: Path = image_path.expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Input path does not exist: '{resolved_path}'")
    if not resolved_path.is_file():
        raise IsADirectoryError(f"Input path is not a file: '{resolved_path}'")
    if resolved_path.stat().st_size == 0:
        raise ValueError(f"Input image is empty: '{resolved_path}'")
    return resolved_path


def _resolve_workspace_root() -> Path:
    """
    Resolve workspace root containing the shared data directory.

    Returns:
        Workspace root path.
    """
    module_path: Path = Path(__file__).resolve()
    for parent in module_path.parents:
        if (parent / "data").exists() and (parent / "printify").exists():
            log_action(f"Resolved workspace root to '{parent}'")
            return parent

    fallback: Path = module_path.parents[5]
    log_action(f"Falling back workspace root to '{fallback}'")
    return fallback


def _safe_save_image(image: Image.Image, output_path: Path) -> None:
    """
    Save an image to disk with mode coercion when target extension requires it.

    Args:
        image: PIL image to save.
        output_path: Destination path.

    Returns:
        None
    """
    log_action(f"Saving image to '{cut(output_path)}'")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    extension: str = output_path.suffix.lower()
    if extension in {".jpg", ".jpeg", ".bmp"}:
        image.convert("RGB").save(output_path)
        return
    image.save(output_path)


class RemoveBgUiApp:
    """Tkinter app for smart remove + bucket simplification edits."""

    def __init__(
        self,
        original_path: Path,
        initial_image: Image.Image,
        tolerance: int,
        history_dir: Path,
    ) -> None:
        log_action("Initializing RemoveBgUiApp")
        self.original_path: Path = original_path
        self.original_name: str = original_path.stem
        self.tolerance: int = max(0, min(255, tolerance))
        self.history_dir: Path = history_dir
        self.change_index: int = 0
        self.history_paths: list[Path] = []
        self.saved_output_path: Optional[Path] = None

        self.current_image: Image.Image = initial_image.convert("RGBA")
        self.display_image: Optional[ImageTk.PhotoImage] = None
        self.display_scale: float = 1.0
        self.user_zoom: float = 1.0
        self.pan_offset_x: float = 0.0
        self.pan_offset_y: float = 0.0
        self.render_origin_x: float = 0.0
        self.render_origin_y: float = 0.0
        self.render_width: int = 1
        self.render_height: int = 1
        self.drag_start_canvas: Optional[tuple[int, int]] = None
        self.drag_last_canvas: Optional[tuple[int, int]] = None
        self.is_dragging: bool = False

        self.root: tk.Tk = tk.Tk()
        self.root.title("Background Simplifier UI")

        self.remove_mode_var: tk.StringVar = tk.StringVar(value="flood")
        self.header_var: tk.StringVar = tk.StringVar(value="Preparing UI...")
        self.status_var: tk.StringVar = tk.StringVar(value="")

        self._build_layout()
        self._bind_shortcuts()
        self._snapshot_current_state()
        self.root.after(10, self._render_image)

    def _build_layout(self) -> None:
        """
        Build top-level UI widgets.

        Returns:
            None
        """
        log_action("Building remove_bg_ui layout")
        container = tk.Frame(self.root, padx=12, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            container,
            textvariable=self.header_var,
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 10, "bold"),
        ).pack(fill=tk.X)

        button_row = tk.Frame(container, pady=6)
        button_row.pack(fill=tk.X)

        self.undo_button = tk.Button(
            button_row,
            text="Undo (Ctrl+Z)",
            command=self.undo,
        )
        self.undo_button.pack(side=tk.LEFT)

        tk.Button(
            button_row,
            text="Save (Ctrl+S)",
            command=self.save_and_close,
        ).pack(side=tk.LEFT, padx=8)

        tk.Radiobutton(
            button_row,
            text="Flood Fill",
            value="flood",
            variable=self.remove_mode_var,
            command=self._on_mode_changed,
        ).pack(side=tk.LEFT, padx=(16, 0))

        tk.Radiobutton(
            button_row,
            text="Global Similar",
            value="global",
            variable=self.remove_mode_var,
            command=self._on_mode_changed,
        ).pack(side=tk.LEFT, padx=(8, 0))

        tk.Button(
            button_row,
            text="Zoom Reset",
            command=self._reset_view,
        ).pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(
            container,
            bg="#222222",
            width=min(self.current_image.width, CANVAS_MAX_WIDTH),
            height=min(self.current_image.height, CANVAS_MAX_HEIGHT),
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_left_press)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>", self._on_mouse_wheel)
        self.canvas.bind("<Button-5>", self._on_mouse_wheel)

        tk.Label(
            container,
            textvariable=self.status_var,
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 9),
        ).pack(fill=tk.X, pady=(8, 0))

    def _bind_shortcuts(self) -> None:
        """
        Bind keyboard shortcuts for undo and save.

        Returns:
            None
        """
        log_action("Binding keyboard shortcuts for remove_bg_ui")
        self.root.bind_all("<Control-z>", self._on_undo_shortcut)
        self.root.bind_all("<Control-s>", self._on_save_shortcut)
        self.root.bind_all("<Control-0>", self._on_reset_view_shortcut)

    def _history_path_for_index(self, change_idx: int) -> Path:
        """
        Build immutable history output path for a change index.

        Args:
            change_idx: Monotonic change counter.

        Returns:
            Snapshot file path.
        """
        log_action(f"Resolving history path for change index {change_idx}")
        file_name: str = f"{self.original_name}_{change_idx}.png"
        return self.history_dir / file_name

    def _snapshot_current_state(self) -> None:
        """
        Persist current image to history and register it for undo.

        Returns:
            None
        """
        log_action("Snapshotting current image state to history")
        snapshot_path: Path = self._history_path_for_index(self.change_index)
        _safe_save_image(self.current_image, snapshot_path)
        self.history_paths.append(snapshot_path)
        self.status_var.set(
            f"Saved change #{self.change_index} -> {snapshot_path.name}"
        )
        self.change_index += 1
        self._update_header()

    def _update_header(self) -> None:
        """
        Update header and undo button state.

        Returns:
            None
        """
        log_action("Updating remove_bg_ui header and button state")
        self.header_var.set(
            "Click to remove color. Drag to pan. Mouse wheel/touchpad to zoom. "
            f"Mode: {self.remove_mode_var.get()} | Tolerance: {self.tolerance} | "
            f"Zoom: {self.user_zoom:.2f}x | Changes: {len(self.history_paths) - 1}"
        )
        self.undo_button.configure(
            state=tk.NORMAL if len(self.history_paths) > 1 else tk.DISABLED
        )

    def _fit_scale(self, canvas_width: int, canvas_height: int) -> float:
        """
        Compute scale that fits current image into the canvas.

        Args:
            canvas_width: Canvas width in pixels.
            canvas_height: Canvas height in pixels.

        Returns:
            Fit-to-canvas scale factor.
        """
        log_action("Computing fit scale for current canvas size")
        width_scale: float = canvas_width / max(1, self.current_image.width)
        height_scale: float = canvas_height / max(1, self.current_image.height)
        return max(0.0001, min(width_scale, height_scale))

    def _render_image(self) -> None:
        """
        Render current image into the canvas with fit-to-window scaling.

        Returns:
            None
        """
        log_action("Rendering current image in remove_bg_ui canvas")
        self.canvas.update_idletasks()
        canvas_width: int = max(1, self.canvas.winfo_width())
        canvas_height: int = max(1, self.canvas.winfo_height())

        fit_scale: float = self._fit_scale(canvas_width, canvas_height)
        self.display_scale = fit_scale * self.user_zoom
        if self.display_scale <= 0:
            self.display_scale = 1.0

        display_width: int = max(1, int(self.current_image.width * self.display_scale))
        display_height: int = max(
            1, int(self.current_image.height * self.display_scale)
        )
        resized = self.current_image.resize(
            (display_width, display_height),
            Image.Resampling.NEAREST,
        )
        display_rgba: Image.Image = resized.convert("RGBA")
        checkerboard: Image.Image = self._build_checkerboard_background(
            width=display_width,
            height=display_height,
        )
        composited: Image.Image = Image.alpha_composite(checkerboard, display_rgba)

        self.display_image = ImageTk.PhotoImage(composited)
        self.canvas.delete("all")
        x_offset: int = int((canvas_width - display_width) / 2 + self.pan_offset_x)
        y_offset: int = int((canvas_height - display_height) / 2 + self.pan_offset_y)
        self.render_origin_x = x_offset
        self.render_origin_y = y_offset
        self.render_width = display_width
        self.render_height = display_height
        self.canvas.create_image(
            x_offset, y_offset, image=self.display_image, anchor=tk.NW
        )

    def _build_checkerboard_background(self, width: int, height: int) -> Image.Image:
        """
        Build a checkerboard background so transparent areas are visible.

        Args:
            width: Background width.
            height: Background height.

        Returns:
            RGBA checkerboard image.
        """
        log_action("Building checkerboard transparency background")
        background = Image.new("RGBA", (width, height), (188, 188, 188, 255))
        pixels = background.load()
        if pixels is None:
            raise RuntimeError("Checkerboard pixels could not be loaded")

        for y_coord in range(height):
            for x_coord in range(width):
                tile_x = x_coord // CHECKER_TILE_SIZE
                tile_y = y_coord // CHECKER_TILE_SIZE
                if (tile_x + tile_y) % 2 == 0:
                    pixels[x_coord, y_coord] = (224, 224, 224, 255)
        return background

    def _on_canvas_resize(self, _: tk.Event) -> None:
        """
        Re-render image content when canvas size changes.

        Returns:
            None
        """
        log_action("Canvas resize detected; re-rendering image")
        self._render_image()

    def _on_mode_changed(self) -> None:
        """
        Update status when removal mode is toggled.

        Returns:
            None
        """
        mode = self.remove_mode_var.get()
        log_action(f"Removal mode changed to '{mode}'")
        self.status_var.set(f"Removal mode: {mode}")
        self._update_header()

    def _reset_view(self) -> None:
        """
        Reset zoom and pan to default view.

        Returns:
            None
        """
        log_action("Resetting zoom and pan view")
        self.user_zoom = 1.0
        self.pan_offset_x = 0.0
        self.pan_offset_y = 0.0
        self._update_header()
        self._render_image()

    def _on_reset_view_shortcut(self, _: tk.Event) -> str:
        """
        Handle Ctrl+0 keyboard shortcut.

        Returns:
            Tkinter break token.
        """
        log_action("Ctrl+0 detected in remove_bg_ui")
        self._reset_view()
        return "break"

    def _to_image_coordinates(
        self, event_x: int, event_y: int
    ) -> Optional[tuple[int, int]]:
        """
        Map canvas click coordinates to source image coordinates.

        Args:
            event_x: Click x in canvas space.
            event_y: Click y in canvas space.

        Returns:
            Source image (x, y) or None if click is outside rendered image.
        """
        log_action("Mapping canvas coordinates to source image coordinates")
        if event_x < self.render_origin_x or event_y < self.render_origin_y:
            return None
        local_x: int = int(event_x - self.render_origin_x)
        local_y: int = int(event_y - self.render_origin_y)
        if local_x >= self.render_width or local_y >= self.render_height:
            return None

        image_x: int = min(
            self.current_image.width - 1, int(local_x / self.display_scale)
        )
        image_y: int = min(
            self.current_image.height - 1, int(local_y / self.display_scale)
        )
        return image_x, image_y

    def _on_mouse_wheel(self, event: tk.Event) -> None:
        """
        Zoom in/out based on mouse wheel or touchpad scroll gesture.

        Args:
            event: Tkinter wheel event.

        Returns:
            None
        """
        log_action("Mouse wheel event received for zoom")
        delta: int = 0
        if hasattr(event, "delta") and event.delta != 0:
            delta = 1 if event.delta > 0 else -1
        elif hasattr(event, "num") and event.num in {4, 5}:
            delta = 1 if event.num == 4 else -1

        if delta == 0:
            return

        zoom_multiplier: float = ZOOM_STEP if delta > 0 else 1.0 / ZOOM_STEP
        self._zoom_at(event.x, event.y, zoom_multiplier)

    def _zoom_at(self, canvas_x: int, canvas_y: int, zoom_multiplier: float) -> None:
        """
        Apply zoom centered around a canvas point.

        Args:
            canvas_x: Cursor x coordinate in canvas space.
            canvas_y: Cursor y coordinate in canvas space.
            zoom_multiplier: Multiplicative zoom step.

        Returns:
            None
        """
        log_action(
            f"Applying zoom at ({canvas_x}, {canvas_y}) with factor {zoom_multiplier:.3f}"
        )
        focus_point = self._to_image_coordinates(canvas_x, canvas_y)
        new_zoom: float = max(MIN_ZOOM, min(MAX_ZOOM, self.user_zoom * zoom_multiplier))
        if abs(new_zoom - self.user_zoom) < 1e-9:
            return
        self.user_zoom = new_zoom

        if focus_point is not None:
            image_x, image_y = focus_point
            canvas_width: int = max(1, self.canvas.winfo_width())
            canvas_height: int = max(1, self.canvas.winfo_height())
            fit_scale: float = self._fit_scale(canvas_width, canvas_height)
            new_scale: float = fit_scale * self.user_zoom

            centered_origin_x = (
                canvas_width - self.current_image.width * new_scale
            ) / 2
            centered_origin_y = (
                canvas_height - self.current_image.height * new_scale
            ) / 2
            target_origin_x = canvas_x - image_x * new_scale
            target_origin_y = canvas_y - image_y * new_scale
            self.pan_offset_x = target_origin_x - centered_origin_x
            self.pan_offset_y = target_origin_y - centered_origin_y

        self._update_header()
        self._render_image()

    def _bucket_remove_connected(self, x_coord: int, y_coord: int) -> bool:
        """
        Flood-fill remove connected pixels similar to clicked color.

        Args:
            x_coord: Source image x coordinate.
            y_coord: Source image y coordinate.

        Returns:
            True when at least one pixel alpha was changed.
        """
        log_action(f"Running bucket remove from click point ({x_coord}, {y_coord})")
        pixels = self.current_image.load()
        if pixels is None:
            raise RuntimeError("Image pixels could not be loaded")

        start_pixel = pixels[x_coord, y_coord]
        target_rgb = (start_pixel[0], start_pixel[1], start_pixel[2])
        if start_pixel[3] == 0:
            log_action("Clicked pixel is already transparent; skipping bucket remove")
            return False

        queue: deque[tuple[int, int]] = deque([(x_coord, y_coord)])
        visited: set[tuple[int, int]] = set()
        changed: bool = False

        width: int = self.current_image.width
        height: int = self.current_image.height
        tolerance: int = self.tolerance

        while queue:
            cur_x, cur_y = queue.popleft()
            if (cur_x, cur_y) in visited:
                continue
            visited.add((cur_x, cur_y))

            pixel = pixels[cur_x, cur_y]
            if pixel[3] == 0:
                continue

            out_of_tolerance: bool = any(
                abs(pixel[channel] - target_rgb[channel]) > tolerance
                for channel in range(3)
            )
            if out_of_tolerance:
                continue

            pixels[cur_x, cur_y] = (pixel[0], pixel[1], pixel[2], 0)
            changed = True

            if cur_x > 0:
                queue.append((cur_x - 1, cur_y))
            if cur_x < width - 1:
                queue.append((cur_x + 1, cur_y))
            if cur_y > 0:
                queue.append((cur_x, cur_y - 1))
            if cur_y < height - 1:
                queue.append((cur_x, cur_y + 1))

        return changed

    def _remove_global_similar(self, x_coord: int, y_coord: int) -> bool:
        """
        Remove all non-transparent pixels similar to clicked color globally.

        Args:
            x_coord: Source image x coordinate.
            y_coord: Source image y coordinate.

        Returns:
            True when at least one pixel alpha was changed.
        """
        log_action(
            f"Running global similar-color remove from click point ({x_coord}, {y_coord})"
        )
        pixels = self.current_image.load()
        if pixels is None:
            raise RuntimeError("Image pixels could not be loaded")

        start_pixel = pixels[x_coord, y_coord]
        if start_pixel[3] == 0:
            return False
        target_rgb = (start_pixel[0], start_pixel[1], start_pixel[2])

        changed: bool = False
        for cur_y in range(self.current_image.height):
            for cur_x in range(self.current_image.width):
                pixel = pixels[cur_x, cur_y]
                if pixel[3] == 0:
                    continue
                out_of_tolerance: bool = any(
                    abs(pixel[channel] - target_rgb[channel]) > self.tolerance
                    for channel in range(3)
                )
                if out_of_tolerance:
                    continue
                pixels[cur_x, cur_y] = (pixel[0], pixel[1], pixel[2], 0)
                changed = True
        return changed

    def _apply_remove_action(self, canvas_x: int, canvas_y: int) -> None:
        """
        Apply selected removal action at a canvas coordinate.

        Args:
            canvas_x: X coordinate in canvas space.
            canvas_y: Y coordinate in canvas space.

        Returns:
            None
        """
        log_action("Applying remove action from canvas interaction")
        point = self._to_image_coordinates(canvas_x, canvas_y)
        if point is None:
            self.status_var.set("Clicked outside the image bounds")
            return

        if self.remove_mode_var.get() == "global":
            changed = self._remove_global_similar(*point)
        else:
            changed = self._bucket_remove_connected(*point)

        if not changed:
            self.status_var.set("No matching pixels were removed for that click")
            return

        self._snapshot_current_state()
        self._render_image()

    def _on_left_press(self, event: tk.Event) -> None:
        """
        Start a potential pan-or-click interaction.

        Args:
            event: Tkinter button press event.

        Returns:
            None
        """
        log_action("Left mouse button pressed")
        self.drag_start_canvas = (event.x, event.y)
        self.drag_last_canvas = (event.x, event.y)
        self.is_dragging = False

    def _on_left_drag(self, event: tk.Event) -> None:
        """
        Pan image while dragging.

        Args:
            event: Tkinter drag event.

        Returns:
            None
        """
        if self.drag_start_canvas is None or self.drag_last_canvas is None:
            return

        start_x, start_y = self.drag_start_canvas
        if not self.is_dragging:
            below_threshold: bool = all(
                distance < PAN_DRAG_THRESHOLD
                for distance in (abs(event.x - start_x), abs(event.y - start_y))
            )
            if below_threshold:
                return
            self.is_dragging = True
            log_action("Drag threshold exceeded; entering pan mode")

        last_x, last_y = self.drag_last_canvas
        delta_x: int = event.x - last_x
        delta_y: int = event.y - last_y
        self.pan_offset_x += delta_x
        self.pan_offset_y += delta_y
        self.drag_last_canvas = (event.x, event.y)
        self._render_image()

    def _on_left_release(self, event: tk.Event) -> None:
        """
        Finish pan-or-click interaction and apply remove on click.

        Args:
            event: Tkinter button release event.

        Returns:
            None
        """
        log_action("Left mouse button released")
        dragged: bool = self.is_dragging
        self.drag_start_canvas = None
        self.drag_last_canvas = None
        self.is_dragging = False

        if dragged:
            self.status_var.set("Panned view")
            return

        self._apply_remove_action(event.x, event.y)

    def _on_undo_shortcut(self, _: tk.Event) -> str:
        """
        Handle Ctrl+Z keyboard shortcut.

        Returns:
            Tkinter break token.
        """
        log_action("Ctrl+Z detected in remove_bg_ui")
        self.undo()
        return "break"

    def _on_save_shortcut(self, _: tk.Event) -> str:
        """
        Handle Ctrl+S keyboard shortcut.

        Returns:
            Tkinter break token.
        """
        log_action("Ctrl+S detected in remove_bg_ui")
        self.save_and_close()
        return "break"

    def undo(self) -> None:
        """
        Revert to the previous saved snapshot state.

        Returns:
            None
        """
        log_action("Undo requested in remove_bg_ui")
        if len(self.history_paths) <= 1:
            self.status_var.set("Nothing to undo")
            return

        self.history_paths.pop()
        restore_path: Path = self.history_paths[-1]
        with Image.open(restore_path) as restore_image:
            self.current_image = restore_image.convert("RGBA")

        self.status_var.set(f"Undo applied -> {restore_path.name}")
        self._update_header()
        self._render_image()

    def _generate_simplified_output_path(self) -> Path:
        """
        Build non-conflicting output path beside original image.

        Returns:
            Output path with collision-safe suffix handling.
        """
        log_action("Generating simplified output path with collision checks")
        suffix: str = self.original_path.suffix
        base_stem: str = f"{self.original_path.stem}{DEFAULT_OUTPUT_SUFFIX}"
        candidate: Path = self.original_path.with_name(f"{base_stem}{suffix}")
        if not candidate.exists():
            return candidate

        alphabet: str = string.ascii_lowercase + string.digits
        while True:
            random_char: str = random.choice(alphabet)
            candidate = self.original_path.with_name(
                f"{base_stem}_{random_char}{suffix}"
            )
            if not candidate.exists():
                return candidate

    def save_and_close(self) -> None:
        """
        Save simplified image and close the UI.

        Returns:
            None
        """
        log_action("Save requested in remove_bg_ui")
        output_path: Path = self._generate_simplified_output_path()
        try:
            _safe_save_image(self.current_image, output_path)
        except OSError as exc:
            self.status_var.set(f"Failed to save simplified image: {exc}")
            log_action(f"Failed to save simplified image: {exc}")
            return

        self.saved_output_path = output_path
        messagebox.showinfo("Saved", f"Saved simplified image to:\n{output_path}")
        log_action(f"Saved simplified image to '{output_path}'")
        self.root.destroy()

    def run(self) -> None:
        """
        Start the Tkinter event loop.

        Returns:
            None
        """
        log_action("Starting remove_bg_ui main loop")
        self.root.mainloop()


def _run_smart_remove(image_path: Path) -> Image.Image:
    """
    Run smart remove mode from remove_bg.py on the source image.

    Args:
        image_path: Input image path.

    Returns:
        Smart-removed RGBA image.
    """
    log_action(f"Applying smart remove pre-processing for '{image_path}'")
    source_bytes: bytes = image_path.read_bytes()
    client = RemoveBgClient(
        api_key="",
        endpoint="",
        retries=1,
        removal_mode="smart",
    )
    smart_bytes: bytes = client.remove_background(source_bytes)
    with Image.open(BytesIO(smart_bytes)) as smart_image:
        processed_image: Image.Image = smart_image.convert("RGBA")

    alpha_channel = processed_image.getchannel("A")
    total_pixels: int = processed_image.width * processed_image.height
    non_transparent_pixels: int = sum(1 for value in alpha_channel.getdata() if value)
    alpha_ratio: float = non_transparent_pixels / max(1, total_pixels)

    if alpha_ratio < MIN_VISIBLE_ALPHA_RATIO:
        log_action("Smart remove created near-empty alpha output; using original image")
        with Image.open(image_path) as source_image:
            return source_image.convert("RGBA")

    return processed_image


def run_interactive_background_removal(
    image_path: Path,
    tolerance: int = DEFAULT_TOLERANCE,
) -> Optional[Path]:
    """Open the background-removal UI and return the saved output path.

    Args:
        image_path: Source image that should be preloaded into the editor.
        tolerance: Per-channel color tolerance for bucket removal.

    Returns:
        Saved output path, or None if the window is closed without saving.
    """
    log_action(f"Launching interactive background removal for '{image_path}'")
    input_path: Path = validate_image_path(image_path)
    initial_image: Image.Image = _run_smart_remove(input_path)

    workspace_root: Path = _resolve_workspace_root()
    history_dir: Path = workspace_root
    for part in HISTORY_DIR_PARTS:
        history_dir = history_dir / part

    app = RemoveBgUiApp(
        original_path=input_path,
        initial_image=initial_image,
        tolerance=tolerance,
        history_dir=history_dir,
    )
    app.run()
    return app.saved_output_path


def main(argv: Optional[list[str]] = None) -> int:
    """
    Run smart remove UI workflow.

    Args:
        argv: Optional argument list.

    Returns:
        Process exit code.
    """
    log_action("Starting remove_bg_ui CLI workflow")
    args = parse_args(argv)

    raw_path: Optional[Path] = Path(args.image_path) if args.image_path else None
    if raw_path is None:
        raw_path = prompt_for_image_path()
        if raw_path is None:
            log_action("No image selected for remove_bg_ui")
            print("No image selected.")
            return 1

    try:
        input_path = validate_image_path(raw_path)
    except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
        log_action(f"Input validation failed for remove_bg_ui: {exc}")
        print(f"Error: {exc}")
        return 1
    except UnidentifiedImageError:
        log_action(f"Input file is not a recognized image: {raw_path}")
        print(f"Error: not a recognized image: {raw_path}")
        return 1
    except OSError as exc:
        log_action(f"Image processing failed in remove_bg_ui: {exc}")
        print(f"Error: {exc}")
        return 1

    try:
        run_interactive_background_removal(
            image_path=input_path,
            tolerance=args.tolerance,
        )
    except UnidentifiedImageError:
        log_action(f"Input file is not a recognized image: {raw_path}")
        print(f"Error: not a recognized image: {raw_path}")
        return 1
    except OSError as exc:
        log_action(f"Image processing failed in remove_bg_ui: {exc}")
        print(f"Error: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
