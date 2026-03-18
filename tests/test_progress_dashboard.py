"""Tests for the progress dashboard timing display."""

import sys
import time
from pathlib import Path
from unittest.mock import patch


MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import ui.progress_dashboard as progress_dashboard_module  # noqa: E402


class _ValueHolder:
    """Simple stand-in for a Tkinter StringVar."""

    def __init__(self) -> None:
        """Initialize the value holder."""
        self.value: str = ""

    def set(self, value: str) -> None:
        """Store the last assigned value.

        Args:
            value: String value assigned by the dashboard.
        """
        self.value = value


class TestPipelineProgressDashboard:
    """Tests for dashboard timing state."""

    def test_refresh_timing_widgets_shows_estimated_finish_time(self) -> None:
        """Formats ETA as a projected clock time instead of remaining duration."""
        dashboard = progress_dashboard_module.PipelineProgressDashboard(enabled=False)
        dashboard._eta_var = _ValueHolder()
        dashboard._start_time = 100.0
        dashboard._finished_ideas = 1
        dashboard._total_ideas = 4

        eta_struct_time = time.struct_time((2026, 3, 17, 10, 6, 0, 1, 76, -1))

        with (
            patch.object(
                progress_dashboard_module.time,
                "monotonic",
                return_value=220.0,
            ),
            patch.object(progress_dashboard_module.time, "time", return_value=1000.0),
            patch.object(
                progress_dashboard_module.time,
                "localtime",
                return_value=eta_struct_time,
            ),
        ):
            dashboard._refresh_timing_widgets()

        assert dashboard._eta_var.value == (
            "Elapsed: 2:00 | Avg/Product: 2:00 | ETA: 10:06"
        )

    def test_refresh_timing_widgets_hides_eta_without_completed_ideas(self) -> None:
        """Leaves ETA blank until enough progress exists to estimate completion."""
        dashboard = progress_dashboard_module.PipelineProgressDashboard(enabled=False)
        dashboard._eta_var = _ValueHolder()
        dashboard._start_time = 100.0
        dashboard._finished_ideas = 0
        dashboard._total_ideas = 4

        with patch.object(
            progress_dashboard_module.time, "monotonic", return_value=190.0
        ):
            dashboard._refresh_timing_widgets()

        assert dashboard._eta_var.value == (
            "Elapsed: 1:30 | Avg/Product: --:-- | ETA: --:--"
        )
