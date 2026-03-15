"""
Interactive bounding box editor for base mockup images.

This tool opens a desktop UI for selecting and adjusting a bounding box on
`data/base_mockups/white.png`, then saves the result to
`data/base_mockups/bbox.json` in pixel `xywh` format.

Controls:
- Mouse drag on rectangle: move bbox.
- Mouse drag on corner handles: resize bbox.
- Mouse drag on empty area: draw new bbox.
- Arrow keys: nudge bbox by 1 px.
- Shift + Arrow keys: resize bbox by 5 px.
- Key `c`: center bbox horizontally.
- Button "Center Horizontally": center bbox horizontally.
- Button "Save (Ctrl+S)": save and exit.
- Button "Reset": reset to default centered bbox.
"""

import json
import sys
import tkinter as tk
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image, ImageTk

try:
    from logger_config import log_action
except ModuleNotFoundError:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from logger_config import log_action


AUTOMATION_ROOT: Path = Path(__file__).resolve().parents[3]
IMAGE_PATH: Path = AUTOMATION_ROOT / "data" / "base_mockups" / "white.png"
OUTPUT_PATH: Path = AUTOMATION_ROOT / "data" / "base_mockups" / "bbox.json"
DEFAULT_BBOX_RATIO: float = 0.6
HANDLE_HALF_SIZE: int = 5
MIN_BBOX_SIZE: int = 10
NUDGE_STEP: int = 1
RESIZE_STEP: int = 5
WINDOW_MARGIN_X: int = 80
WINDOW_MARGIN_Y: int = 140


class BBoxEditor:
    """Interactive editor for selecting a bounding box on an image.

    Attributes:
        root: Tk root window.
        image_path: Source image path.
        output_path: Destination bbox JSON path.
    """

    def __init__(self, root: tk.Tk, image_path: Path, output_path: Path) -> None:
        """Initialize editor state and UI.

        Args:
            root: Tk root window.
            image_path: Path to source image.
            output_path: Path to output JSON.
        """
        log_action("Initializing BBoxEditor")
        self.root: tk.Tk = root
        self.image_path: Path = image_path
        self.output_path: Path = output_path

        self.image = Image.open(image_path)
        self.image_width: int = self.image.width
        self.image_height: int = self.image.height

        screen_w: int = root.winfo_screenwidth()
        screen_h: int = root.winfo_screenheight()
        max_canvas_w: int = max(200, screen_w - WINDOW_MARGIN_X)
        max_canvas_h: int = max(200, screen_h - WINDOW_MARGIN_Y)
        self.display_scale: float = min(
            1.0,
            max_canvas_w / self.image_width,
            max_canvas_h / self.image_height,
        )
        self.display_width: int = max(1, int(self.image_width * self.display_scale))
        self.display_height: int = max(1, int(self.image_height * self.display_scale))

        if self.display_scale < 1.0:
            display_image = self.image.resize(
                (self.display_width, self.display_height),
                Image.Resampling.LANCZOS,
            )
        else:
            display_image = self.image

        self.tk_image = ImageTk.PhotoImage(display_image)

        self.canvas: tk.Canvas = tk.Canvas(
            root,
            width=self.display_width,
            height=self.display_height,
            bg="#111111",
            highlightthickness=0,
        )
        self.canvas.grid(row=0, column=0, columnspan=4, padx=8, pady=8)
        self.canvas.create_image(0, 0, image=self.tk_image, anchor="nw")

        self.status_var: tk.StringVar = tk.StringVar(value="Ready")
        status_label = tk.Label(root, textvariable=self.status_var, anchor="w")
        status_label.grid(row=1, column=0, columnspan=4, sticky="we", padx=8)

        center_button = tk.Button(
            root,
            text="Center Horizontally (C)",
            command=self.center_horizontally,
        )
        center_button.grid(row=2, column=0, padx=8, pady=8, sticky="we")

        reset_button = tk.Button(root, text="Reset", command=self.reset_bbox)
        reset_button.grid(row=2, column=1, padx=8, pady=8, sticky="we")

        save_button = tk.Button(root, text="Save (Ctrl+S)", command=self.save_and_exit)
        save_button.grid(row=2, column=2, padx=8, pady=8, sticky="we")

        cancel_button = tk.Button(root, text="Cancel", command=self.cancel)
        cancel_button.grid(row=2, column=3, padx=8, pady=8, sticky="we")

        for col in range(4):
            root.grid_columnconfigure(col, weight=1)

        self.x: int = 0
        self.y: int = 0
        self.w: int = 0
        self.h: int = 0

        self.rect_id: Optional[int] = None
        self.handle_ids: Dict[str, int] = {}

        self.drag_mode: Optional[str] = None
        self.active_handle: Optional[str] = None
        self.drag_start: Tuple[int, int] = (0, 0)
        self.start_bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)

        self.reset_bbox()
        self._bind_events()

    def _to_image_x(self, display_x: int) -> int:
        """Convert display x coordinate to original image coordinate."""
        log_action("Converting display x to image x")
        return int(max(0, min(self.image_width, round(display_x / self.display_scale))))

    def _to_image_y(self, display_y: int) -> int:
        """Convert display y coordinate to original image coordinate."""
        log_action("Converting display y to image y")
        return int(
            max(0, min(self.image_height, round(display_y / self.display_scale)))
        )

    def _to_display_x(self, image_x: int) -> int:
        """Convert original image x coordinate to display coordinate."""
        log_action("Converting image x to display x")
        return int(round(image_x * self.display_scale))

    def _to_display_y(self, image_y: int) -> int:
        """Convert original image y coordinate to display coordinate."""
        log_action("Converting image y to display y")
        return int(round(image_y * self.display_scale))

    def _bind_events(self) -> None:
        """Bind mouse and keyboard handlers."""
        log_action("Binding editor events")
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

        self.root.bind("<Left>", lambda _event: self.nudge(-NUDGE_STEP, 0))
        self.root.bind("<Right>", lambda _event: self.nudge(NUDGE_STEP, 0))
        self.root.bind("<Up>", lambda _event: self.nudge(0, -NUDGE_STEP))
        self.root.bind("<Down>", lambda _event: self.nudge(0, NUDGE_STEP))

        self.root.bind("<Shift-Left>", lambda _event: self.resize_by(-RESIZE_STEP, 0))
        self.root.bind("<Shift-Right>", lambda _event: self.resize_by(RESIZE_STEP, 0))
        self.root.bind("<Shift-Up>", lambda _event: self.resize_by(0, -RESIZE_STEP))
        self.root.bind("<Shift-Down>", lambda _event: self.resize_by(0, RESIZE_STEP))

        self.root.bind("c", lambda _event: self.center_horizontally())
        self.root.bind("<Control-s>", lambda _event: self.save_and_exit())
        self.root.bind("<Return>", lambda _event: self.save_and_exit())

    def _update_status(self) -> None:
        """Update on-screen bbox status text."""
        log_action("Updating bbox status text")
        self.status_var.set(
            f"bbox xywh: x={self.x}, y={self.y}, w={self.w}, h={self.h} | "
            f"scale={self.display_scale:.2f} | "
            "Arrows=move, Shift+Arrows=resize, C=center, Ctrl+S=save"
        )

    def _draw_bbox(self) -> None:
        """Render bbox rectangle and corner handles."""
        log_action("Drawing bbox and resize handles")
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)

        for handle_id in self.handle_ids.values():
            self.canvas.delete(handle_id)
        self.handle_ids = {}

        x1 = self._to_display_x(self.x)
        y1 = self._to_display_y(self.y)
        x2 = self._to_display_x(self.x + self.w)
        y2 = self._to_display_y(self.y + self.h)

        self.rect_id = self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            outline="#00E5FF",
            width=2,
        )

        self.handle_ids["nw"] = self._draw_handle(x1, y1)
        self.handle_ids["ne"] = self._draw_handle(x2, y1)
        self.handle_ids["sw"] = self._draw_handle(x1, y2)
        self.handle_ids["se"] = self._draw_handle(x2, y2)

        self._update_status()

    def _draw_handle(self, cx: int, cy: int) -> int:
        """Draw one corner handle.

        Args:
            cx: Center x coordinate.
            cy: Center y coordinate.

        Returns:
            Canvas id for the handle shape.
        """
        log_action("Drawing a corner handle")
        hs = max(HANDLE_HALF_SIZE, int(HANDLE_HALF_SIZE * self.display_scale) + 1)
        return self.canvas.create_rectangle(
            cx - hs,
            cy - hs,
            cx + hs,
            cy + hs,
            fill="#00E5FF",
            outline="#FFFFFF",
            width=1,
        )

    def _clamp_bbox(self, x: int, y: int, w: int, h: int) -> Tuple[int, int, int, int]:
        """Clamp bbox to valid bounds and minimum size.

        Args:
            x: Proposed left coordinate.
            y: Proposed top coordinate.
            w: Proposed width.
            h: Proposed height.

        Returns:
            Clamped bbox tuple (x, y, w, h).
        """
        log_action("Clamping bbox to image bounds")
        w = max(MIN_BBOX_SIZE, min(w, self.image_width))
        h = max(MIN_BBOX_SIZE, min(h, self.image_height))
        x = max(0, min(x, self.image_width - w))
        y = max(0, min(y, self.image_height - h))
        return x, y, w, h

    def _hit_test_handle(self, x: int, y: int) -> Optional[str]:
        """Return handle key if pointer is over a handle.

        Args:
            x: Pointer x coordinate.
            y: Pointer y coordinate.

        Returns:
            Handle key string or None.
        """
        log_action("Running handle hit test")
        hs = int((HANDLE_HALF_SIZE + 3) / self.display_scale)
        handle_points = {
            "nw": (self.x, self.y),
            "ne": (self.x + self.w, self.y),
            "sw": (self.x, self.y + self.h),
            "se": (self.x + self.w, self.y + self.h),
        }
        for key, (hx, hy) in handle_points.items():
            if (hx - hs) <= x <= (hx + hs) and (hy - hs) <= y <= (hy + hs):
                return key
        return None

    def _inside_bbox(self, x: int, y: int) -> bool:
        """Check whether a point is inside the current bbox.

        Args:
            x: Pointer x coordinate.
            y: Pointer y coordinate.

        Returns:
            True if inside bbox, otherwise False.
        """
        log_action("Checking whether pointer is inside bbox")
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h

    def on_mouse_down(self, event: tk.Event) -> None:
        """Handle mouse button press and begin an interaction mode.

        Args:
            event: Tk mouse event.
        """
        log_action("Mouse down event received")
        mx = self._to_image_x(int(event.x))
        my = self._to_image_y(int(event.y))

        self.drag_start = (mx, my)
        self.start_bbox = (self.x, self.y, self.w, self.h)

        handle_key = self._hit_test_handle(mx, my)
        if handle_key is not None:
            self.drag_mode = "resize"
            self.active_handle = handle_key
            return

        if self._inside_bbox(mx, my):
            self.drag_mode = "move"
            self.active_handle = None
            return

        self.drag_mode = "draw"
        self.active_handle = None
        self.x, self.y, self.w, self.h = self._clamp_bbox(
            mx,
            my,
            MIN_BBOX_SIZE,
            MIN_BBOX_SIZE,
        )
        self._draw_bbox()

    def on_mouse_drag(self, event: tk.Event) -> None:
        """Handle mouse drag for draw, move, and resize actions.

        Args:
            event: Tk mouse event.
        """
        log_action("Mouse drag event received")
        if self.drag_mode is None:
            return

        mx = self._to_image_x(int(event.x))
        my = self._to_image_y(int(event.y))

        if self.drag_mode == "move":
            self._drag_move(mx, my)
        elif self.drag_mode == "resize":
            self._drag_resize(mx, my)
        elif self.drag_mode == "draw":
            self._drag_draw(mx, my)

        self._draw_bbox()

    def on_mouse_up(self, _event: tk.Event) -> None:
        """Finish active drag operation.

        Args:
            _event: Tk mouse event.
        """
        log_action("Mouse up event received")
        self.drag_mode = None
        self.active_handle = None

    def _drag_move(self, mx: int, my: int) -> None:
        """Move bbox based on drag delta.

        Args:
            mx: Mouse x coordinate.
            my: Mouse y coordinate.
        """
        log_action("Processing bbox move drag")
        sx, sy = self.drag_start
        start_x, start_y, start_w, start_h = self.start_bbox

        dx = mx - sx
        dy = my - sy
        new_x = start_x + dx
        new_y = start_y + dy
        self.x, self.y, self.w, self.h = self._clamp_bbox(
            new_x,
            new_y,
            start_w,
            start_h,
        )

    def _drag_resize(self, mx: int, my: int) -> None:
        """Resize bbox from the active corner handle.

        Args:
            mx: Mouse x coordinate.
            my: Mouse y coordinate.
        """
        log_action("Processing bbox resize drag")
        if self.active_handle is None:
            return

        start_x, start_y, start_w, start_h = self.start_bbox
        left = start_x
        top = start_y
        right = start_x + start_w
        bottom = start_y + start_h

        if "n" in self.active_handle:
            top = my
        if "s" in self.active_handle:
            bottom = my
        if "w" in self.active_handle:
            left = mx
        if "e" in self.active_handle:
            right = mx

        if right < left:
            left, right = right, left
        if bottom < top:
            top, bottom = bottom, top

        new_x = left
        new_y = top
        new_w = right - left
        new_h = bottom - top
        self.x, self.y, self.w, self.h = self._clamp_bbox(
            new_x,
            new_y,
            new_w,
            new_h,
        )

    def _drag_draw(self, mx: int, my: int) -> None:
        """Draw bbox from drag-start anchor to current pointer.

        Args:
            mx: Mouse x coordinate.
            my: Mouse y coordinate.
        """
        log_action("Processing bbox draw drag")
        sx, sy = self.drag_start
        left = min(sx, mx)
        top = min(sy, my)
        right = max(sx, mx)
        bottom = max(sy, my)
        self.x, self.y, self.w, self.h = self._clamp_bbox(
            left,
            top,
            max(MIN_BBOX_SIZE, right - left),
            max(MIN_BBOX_SIZE, bottom - top),
        )

    def nudge(self, dx: int, dy: int) -> None:
        """Move bbox by small keyboard increments.

        Args:
            dx: Delta x.
            dy: Delta y.
        """
        log_action(f"Nudging bbox by dx={dx}, dy={dy}")
        self.x, self.y, self.w, self.h = self._clamp_bbox(
            self.x + dx,
            self.y + dy,
            self.w,
            self.h,
        )
        self._draw_bbox()

    def resize_by(self, dw: int, dh: int) -> None:
        """Resize bbox around its center by keyboard increments.

        Args:
            dw: Delta width.
            dh: Delta height.
        """
        log_action(f"Resizing bbox by dw={dw}, dh={dh}")
        center_x = self.x + self.w // 2
        center_y = self.y + self.h // 2
        new_w = self.w + dw
        new_h = self.h + dh
        new_x = center_x - new_w // 2
        new_y = center_y - new_h // 2
        self.x, self.y, self.w, self.h = self._clamp_bbox(
            new_x,
            new_y,
            new_w,
            new_h,
        )
        self._draw_bbox()

    def center_horizontally(self) -> None:
        """Center bbox horizontally while preserving current size and y."""
        log_action("Centering bbox horizontally")
        centered_x = (self.image_width - self.w) // 2
        self.x, self.y, self.w, self.h = self._clamp_bbox(
            centered_x,
            self.y,
            self.w,
            self.h,
        )
        self._draw_bbox()

    def reset_bbox(self) -> None:
        """Reset bbox to a centered default size."""
        log_action("Resetting bbox to default centered size")
        default_w = max(MIN_BBOX_SIZE, int(self.image_width * DEFAULT_BBOX_RATIO))
        default_h = max(MIN_BBOX_SIZE, int(self.image_height * DEFAULT_BBOX_RATIO))
        default_x = (self.image_width - default_w) // 2
        default_y = (self.image_height - default_h) // 2
        self.x, self.y, self.w, self.h = self._clamp_bbox(
            default_x,
            default_y,
            default_w,
            default_h,
        )
        self._draw_bbox()

    def save_and_exit(self) -> None:
        """Save bbox to JSON and exit the application."""
        log_action("Saving bbox and exiting editor")
        payload = {
            "image": str(self.image_path),
            "format": "xywh",
            "units": "pixels",
            "bbox": {
                "x": int(self.x),
                "y": int(self.y),
                "width": int(self.w),
                "height": int(self.h),
            },
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, indent=2)

        self.root.destroy()

    def cancel(self) -> None:
        """Close the editor without writing bbox.json."""
        log_action("Cancelling bbox edit session")
        self.root.destroy()


def main() -> None:
    """Run the interactive bbox editor."""
    log_action("Starting decide_bbox interactive tool")
    if not IMAGE_PATH.exists():
        raise FileNotFoundError(
            f"Image not found at '{IMAGE_PATH}'. Create data/base_mockups/white.png first."
        )

    root = tk.Tk()
    root.title("BBox Editor - white.png")
    editor = BBoxEditor(root, IMAGE_PATH, OUTPUT_PATH)

    window_w = editor.display_width + 20
    window_h = editor.display_height + 110
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    pos_x = max(0, (screen_w - window_w) // 2)
    pos_y = max(0, (screen_h - window_h) // 2)
    root.geometry(f"{window_w}x{window_h}+{pos_x}+{pos_y}")
    root.resizable(False, False)

    root.mainloop()


if __name__ == "__main__":
    main()
