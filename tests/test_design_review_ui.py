"""Tests for the browser-based manual design review UI."""

import sys
from pathlib import Path


MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import design_review_ui as review_ui_module  # noqa: E402


class TestBuildHtml:
    """Tests for the generated review page HTML."""

    def test_build_html_includes_expand_modal_and_submitting_state(self):
        """Renders expanded image modal and submitting button text state."""
        html = review_ui_module._build_html("alpha")

        assert "Submitting" in html
        assert 'id="image-modal"' in html
        assert 'id="modal-image"' in html
        assert "cursor: move;" in html
        assert 'navigator.sendBeacon("/api/closed")' in html
        assert "click image to expand" in html

    def test_build_html_includes_stronger_selected_state_styles(self):
        """Includes explicit card and button styling hooks for selected decisions."""
        html = review_ui_module._build_html("alpha")

        assert ".card.selected-keep" in html
        assert ".card.selected-reject" in html
        assert "button.action.active.keep::after" in html
        assert "button.action.active.reject::after" in html
