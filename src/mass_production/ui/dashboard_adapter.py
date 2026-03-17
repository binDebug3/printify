"""
This module provides an adapter for the mass production pipeline to interact with an optional
progress dashboard UI. It defines functions to create the dashboard and safely call its methods
without impacting the core pipeline execution if the UI is unavailable or encounters errors.
"""

from typing import Any, Optional
from config import constants
from schedule.logger_config import log_action


def create_progress_dashboard() -> Optional[Any]:
    """Create the optional pipeline progress dashboard.

    Returns:
        Dashboard instance when enabled, else None.
    """
    if not constants.ENABLE_PROGRESS_UI:
        return None
    try:
        from ui.progress_dashboard import PipelineProgressDashboard

        return PipelineProgressDashboard(enabled=True)
    except Exception as exc:  # noqa: BLE001
        log_action(f"Progress dashboard is unavailable; continuing without UI: {exc}")
        return None


def safe_dashboard_call(
    dashboard: Optional[Any],
    method_name: str,
    *args: Any,
) -> None:
    """Invoke one dashboard method and suppress UI errors.

    Args:
        dashboard: Dashboard object or None.
        method_name: Method to call.
        args: Positional args for the dashboard method.
    """
    if dashboard is None:
        return
    try:
        method = getattr(dashboard, method_name)
        method(*args)
    except Exception as exc:  # noqa: BLE001
        log_action(f"Dashboard update failed for method '{method_name}': {exc}")
