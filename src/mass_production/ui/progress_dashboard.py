"""Tkinter dashboard for live mass production pipeline progress."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from schedule.logger_config import log_action
from photoshop.io_utils import cut


IMAGE_SLOT_LABELS: Dict[str, str] = {
    "raw_design": "Raw Design",
    "transparent_design": "Transparent Design",
    "default_mockup": "Default Mockup",
    "generated_mockup": "Generated Mockup",
    "cropped_mockup": "Cropped Mockup",
}
MAX_RECENT_ERRORS: int = 8
POLL_INTERVAL_MS: int = 180
THUMBNAIL_SIZE: Tuple[int, int] = (236, 236)


class PipelineProgressDashboard:
    """Live desktop dashboard for the mass production pipeline.

    The pipeline thread publishes events into an in-memory queue while a dedicated
    Tkinter UI thread reads those events and updates widgets. This keeps the
    pipeline responsive and avoids blocking on GUI operations.
    """

    def __init__(self, enabled: bool) -> None:
        """Initialize and optionally start the dashboard.

        Args:
            enabled: Whether GUI updates should be rendered.
        """
        log_action(f"Initializing pipeline progress dashboard (enabled={enabled})")
        self._enabled: bool = enabled
        self._start_time: float = time.monotonic()
        self._events: queue.Queue[Tuple[str, Any]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._is_running: bool = False
        self._ui_ready: threading.Event = threading.Event()

        self._finished_ideas: int = 0
        self._successful_ideas: int = 0
        self._failed_ideas: int = 0
        self._total_ideas: int = 0

        if not self._enabled:
            return

        self._thread = threading.Thread(
            target=self._run_ui,
            name="pipeline-progress-ui",
            daemon=False,
        )
        self._thread.start()
        self._ui_ready.wait(timeout=3.0)

    def set_keyword(self, keyword: str, keyword_index: int, keyword_total: int) -> None:
        """Set active keyword and keyword progress state.

        Args:
            keyword: Keyword currently being processed.
            keyword_index: One-based keyword index.
            keyword_total: Total keywords for this run.
        """
        log_action(
            f"Updating UI keyword progress to {keyword_index}/{keyword_total}: '{keyword}'"
        )
        self._emit(
            "keyword",
            {
                "keyword": keyword,
                "keyword_index": keyword_index,
                "keyword_total": keyword_total,
            },
        )

    def set_total_ideas(self, total_ideas: int) -> None:
        """Update known total number of ideas to complete.

        Args:
            total_ideas: Total ideas expected to reach terminal status.
        """
        log_action(f"Updating UI total ideas to {total_ideas}")
        self._emit("total_ideas", max(0, int(total_ideas)))

    def set_stage(self, stage: str) -> None:
        """Set current stage text.

        Args:
            stage: Human-readable stage label.
        """
        log_action(f"Updating UI stage to '{stage}'")
        self._emit("stage", stage)

    def set_idea_name(self, idea_name: str) -> None:
        """Set the current idea title displayed in UI.

        Args:
            idea_name: Active idea title.
        """
        log_action(f"Updating UI active idea to '{idea_name}'")
        self._emit("idea_name", idea_name)

    def update_image(self, image_slot: str, image_path: Path) -> None:
        """Update one image panel to show the latest generated asset.

        Args:
            image_slot: Slot key from IMAGE_SLOT_LABELS.
            image_path: Path to the generated image.
        """
        path: str = str(image_path)
        log_action(f"Updating UI image slot '{cut(image_slot)}' with '{path}'")
        self._emit("image", {"slot": image_slot, "path": path})

    def add_error(self, message: str) -> None:
        """Append an error message to the recent error list.

        Args:
            message: Error message to display.
        """
        log_action(f"Adding UI error message: {message}")
        self._emit("error", message)

    def mark_idea_finished(self, succeeded: bool) -> None:
        """Increment completed idea counters.

        Args:
            succeeded: True for successful completion, False for failure/rejection.
        """
        status: str = "success" if succeeded else "failed"
        log_action(f"Marking UI idea as finished with status '{status}'")
        self._emit("idea_finished", succeeded)

    def close(self) -> None:
        """Close the dashboard and join its UI thread."""
        log_action("Closing pipeline progress dashboard")
        if not self._enabled:
            return
        if not self._is_running:
            return
        self._emit("close", True)
        if self._thread is not None:
            self._thread.join(timeout=8.0)

    def _emit(self, event_type: str, payload: Any) -> None:
        """Send an event to the UI thread when enabled.

        Args:
            event_type: Event discriminator string.
            payload: Event payload object.
        """
        log_action(f"Queueing dashboard event '{event_type}'")
        if not self._enabled:
            return
        self._events.put((event_type, payload))

    def _run_ui(self) -> None:
        """Start Tkinter UI loop and process queued events."""
        log_action("Starting Tkinter UI thread for progress dashboard")
        try:
            import tkinter as tk
            from tkinter import ttk
            from PIL import Image, ImageOps, ImageTk
        except Exception as exc:  # noqa: BLE001
            log_action(f"UI dependencies unavailable; dashboard disabled: {exc}")
            self._ui_ready.set()
            return

        self._is_running = True
        self._tk = tk
        self._ttk = ttk
        self._pil_image = Image
        self._pil_image_ops = ImageOps
        self._pil_image_tk = ImageTk

        self._root = tk.Tk()
        self._root.title("Mass Production Progress")
        self._root.geometry("1420x900")
        self._root.configure(bg="#F4F1EA")
        self._root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._keyword_var = tk.StringVar(value="Keyword: waiting...")
        self._idea_var = tk.StringVar(value="Idea: waiting...")
        self._stage_var = tk.StringVar(value="Stage: initializing")
        self._eta_var = tk.StringVar(value="Elapsed: 0:00 | ETA: --:--")
        self._summary_var = tk.StringVar(value="Finished 0/0 | Success 0 | Failed 0")

        self._image_labels: Dict[str, Any] = {}
        self._image_refs: Dict[str, Any] = {}
        self._image_path_vars: Dict[str, Any] = {}

        self._build_layout()
        self._ui_ready.set()
        try:
            self._root.after(POLL_INTERVAL_MS, self._poll_events)
            self._root.mainloop()
        finally:
            self._dispose_ui_objects()
            self._is_running = False
            log_action("Tkinter UI thread finished")

    def _build_layout(self) -> None:
        """Build all dashboard widgets."""
        log_action("Building progress dashboard widgets")
        tk = self._tk
        ttk = self._ttk

        style = ttk.Style(self._root)
        style.theme_use("clam")
        style.configure("Pipeline.Horizontal.TProgressbar", troughcolor="#DBD6CB")
        style.configure("Pipeline.Horizontal.TProgressbar", background="#246B5A")

        root_frame = tk.Frame(self._root, bg="#F4F1EA", padx=16, pady=14)
        root_frame.pack(fill="both", expand=True)

        header = tk.Frame(root_frame, bg="#F4F1EA")
        header.pack(fill="x", pady=(0, 10))

        tk.Label(
            header,
            text="Mass Production Pipeline",
            font=("Segoe UI Semibold", 20),
            bg="#F4F1EA",
            fg="#17201E",
        ).pack(anchor="w")
        tk.Label(
            header,
            textvariable=self._keyword_var,
            font=("Segoe UI", 12),
            bg="#F4F1EA",
            fg="#22302D",
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(
            header,
            textvariable=self._idea_var,
            font=("Segoe UI", 12),
            bg="#F4F1EA",
            fg="#22302D",
        ).pack(anchor="w")
        tk.Label(
            header,
            textvariable=self._stage_var,
            font=("Segoe UI", 11),
            bg="#F4F1EA",
            fg="#3D4A47",
        ).pack(anchor="w", pady=(2, 0))

        progress_card = tk.Frame(root_frame, bg="#FFFFFF", padx=14, pady=12)
        progress_card.pack(fill="x", pady=(0, 10))

        self._progress = ttk.Progressbar(
            progress_card,
            orient="horizontal",
            mode="determinate",
            style="Pipeline.Horizontal.TProgressbar",
            maximum=1,
            value=0,
        )
        self._progress.pack(fill="x")

        footer_stats = tk.Frame(progress_card, bg="#FFFFFF")
        footer_stats.pack(fill="x", pady=(8, 0))
        tk.Label(
            footer_stats,
            textvariable=self._summary_var,
            font=("Consolas", 11),
            bg="#FFFFFF",
            fg="#2C3735",
        ).pack(side="left")
        tk.Label(
            footer_stats,
            textvariable=self._eta_var,
            font=("Consolas", 11),
            bg="#FFFFFF",
            fg="#2C3735",
        ).pack(side="right")

        panels_frame = tk.Frame(root_frame, bg="#F4F1EA")
        panels_frame.pack(fill="both", expand=True)

        for slot, display_name in IMAGE_SLOT_LABELS.items():
            panel = tk.Frame(
                panels_frame,
                bg="#FFFFFF",
                padx=8,
                pady=8,
                relief="ridge",
                borderwidth=1,
            )
            panel.pack(side="left", fill="both", expand=True, padx=4)
            tk.Label(
                panel,
                text=display_name,
                font=("Segoe UI Semibold", 11),
                bg="#FFFFFF",
                fg="#17201E",
            ).pack(anchor="w")

            image_label = tk.Label(
                panel,
                text="Waiting for image...",
                font=("Segoe UI", 10),
                bg="#EEF1EC",
                fg="#4D5855",
                width=30,
                height=14,
                wraplength=220,
                justify="center",
            )
            image_label.pack(fill="both", expand=True, pady=(6, 6))

            path_var = tk.StringVar(value="-")
            tk.Label(
                panel,
                textvariable=path_var,
                font=("Consolas", 8),
                bg="#FFFFFF",
                fg="#68716F",
                wraplength=250,
                justify="left",
            ).pack(anchor="w")

            self._image_labels[slot] = image_label
            self._image_path_vars[slot] = path_var

        errors_frame = tk.Frame(root_frame, bg="#FFFFFF", padx=10, pady=8)
        errors_frame.pack(fill="x", pady=(10, 0))
        tk.Label(
            errors_frame,
            text="Recent Errors",
            font=("Segoe UI Semibold", 11),
            bg="#FFFFFF",
            fg="#7B2638",
        ).pack(anchor="w")

        self._errors_listbox = tk.Listbox(
            errors_frame,
            height=6,
            font=("Consolas", 10),
            bg="#FBF8F9",
            fg="#5F1E2D",
            activestyle="none",
            relief="flat",
            borderwidth=0,
        )
        self._errors_listbox.pack(fill="x", pady=(6, 0))

    def _poll_events(self) -> None:
        """Process queued events and refresh timing/progress labels."""
        if not self._is_running:
            return

        handled_any: bool = False
        while True:
            try:
                event_type, payload = self._events.get_nowait()
            except queue.Empty:
                break
            handled_any = True
            self._handle_event(event_type, payload)

        if handled_any:
            self._refresh_progress_widgets()
        self._refresh_timing_widgets()
        self._root.after(POLL_INTERVAL_MS, self._poll_events)

    def _handle_event(self, event_type: str, payload: Any) -> None:
        """Dispatch one UI event.

        Args:
            event_type: Event discriminator string.
            payload: Event payload.
        """
        log_action(f"Handling dashboard event '{event_type}'")
        if event_type == "keyword":
            keyword = str(payload.get("keyword", ""))
            keyword_index = int(payload.get("keyword_index", 0))
            keyword_total = int(payload.get("keyword_total", 0))
            self._keyword_var.set(
                f"Keyword: {keyword_index}/{keyword_total} - {keyword}"
            )
            return
        if event_type == "total_ideas":
            self._total_ideas = max(0, int(payload))
            return
        if event_type == "stage":
            self._stage_var.set(f"Stage: {str(payload)}")
            return
        if event_type == "idea_name":
            self._idea_var.set(f"Idea: {str(payload)}")
            return
        if event_type == "image":
            image_slot = str(payload.get("slot", ""))
            path = str(payload.get("path", "")).strip()
            self._update_image_slot(image_slot=image_slot, image_path=path)
            return
        if event_type == "error":
            self._append_error(str(payload))
            return
        if event_type == "idea_finished":
            succeeded = bool(payload)
            self._finished_ideas += 1
            if succeeded:
                self._successful_ideas += 1
            else:
                self._failed_ideas += 1
            return
        if event_type == "close":
            self._root.after(0, self._shutdown_ui)
            return

    def _shutdown_ui(self) -> None:
        """Stop the Tk main loop and destroy the root window safely."""
        log_action("Stopping dashboard UI loop")
        if not self._is_running:
            return
        self._is_running = False
        try:
            self._root.quit()
        except Exception as exc:  # noqa: BLE001
            log_action(f"Dashboard quit skipped: {exc}")
        try:
            self._root.destroy()
        except Exception as exc:  # noqa: BLE001
            log_action(f"Dashboard destroy skipped: {exc}")

    def _dispose_ui_objects(self) -> None:
        """Release Tk object references on the UI thread before thread exit."""
        log_action("Disposing dashboard UI object references")

        for attr_name in [
            "_keyword_var",
            "_idea_var",
            "_stage_var",
            "_eta_var",
            "_summary_var",
        ]:
            setattr(self, attr_name, None)

        for attr_name in ["_image_refs", "_image_labels", "_image_path_vars"]:
            attr_value = getattr(self, attr_name, None)
            if isinstance(attr_value, dict):
                attr_value.clear()
            setattr(self, attr_name, None)

        for attr_name in ["_errors_listbox", "_progress", "_root"]:
            setattr(self, attr_name, None)

        for attr_name in [
            "_tk",
            "_ttk",
            "_pil_image",
            "_pil_image_ops",
            "_pil_image_tk",
        ]:
            setattr(self, attr_name, None)

    def _update_image_slot(self, image_slot: str, image_path: str) -> None:
        """Render an image thumbnail in the selected image panel.

        Args:
            image_slot: Slot key from IMAGE_SLOT_LABELS.
            image_path: Full image path string.
        """
        log_action(f"Rendering dashboard image for slot '{image_slot}'")
        label = self._image_labels.get(image_slot)
        path_var = self._image_path_vars.get(image_slot)
        if label is None or path_var is None:
            return

        path_var.set(image_path)
        path = Path(image_path)
        if not path.exists():
            label.configure(
                image="",
                text="Image path missing",
                bg="#FDEBEC",
                fg="#8F1F34",
            )
            return

        try:
            with self._pil_image.open(path) as image_obj:
                converted = image_obj.convert("RGBA")
                resized = self._pil_image_ops.contain(converted, THUMBNAIL_SIZE)
                tk_image = self._pil_image_tk.PhotoImage(resized)
        except Exception as exc:  # noqa: BLE001
            label.configure(
                image="",
                text=f"Failed to load image\n{exc}",
                bg="#FDEBEC",
                fg="#8F1F34",
            )
            return

        self._image_refs[image_slot] = tk_image
        label.configure(image=tk_image, text="", bg="#EEF1EC")

    def _append_error(self, message: str) -> None:
        """Append one error line into the recent error list.

        Args:
            message: Error message to append.
        """
        log_action("Appending message into dashboard recent errors")
        existing_size = int(self._errors_listbox.size())
        if existing_size >= MAX_RECENT_ERRORS:
            self._errors_listbox.delete(0)
        self._errors_listbox.insert("end", message)
        self._errors_listbox.see("end")

    def _refresh_progress_widgets(self) -> None:
        """Refresh progress bar and progress summary labels."""
        total = max(0, self._total_ideas)
        finished = min(self._finished_ideas, total) if total else self._finished_ideas
        self._progress.configure(maximum=max(1, total), value=finished)
        self._summary_var.set(
            f"Finished {self._finished_ideas}/{total} | "
            f"Success {self._successful_ideas} | Failed {self._failed_ideas}"
        )

    def _refresh_timing_widgets(self) -> None:
        """Refresh elapsed and ETA labels."""
        elapsed_seconds = max(0.0, time.monotonic() - self._start_time)
        elapsed_minutes = int(elapsed_seconds) // 60
        elapsed_remainder = int(elapsed_seconds) % 60

        eta_text = "--:--"
        if self._finished_ideas > 0 and self._total_ideas > self._finished_ideas:
            average_seconds = elapsed_seconds / float(self._finished_ideas)
            eta_seconds = average_seconds * float(
                self._total_ideas - self._finished_ideas
            )
            eta_minutes = int(eta_seconds) // 60
            eta_remainder = int(eta_seconds) % 60
            eta_text = f"{eta_minutes}:{eta_remainder:02d}"

        self._eta_var.set(
            f"Elapsed: {elapsed_minutes}:{elapsed_remainder:02d} | ETA: {eta_text}"
        )

    def _on_window_close(self) -> None:
        """Handle user-initiated window close safely."""
        log_action("User closed the progress dashboard window")
        self._shutdown_ui()


# End of module.
