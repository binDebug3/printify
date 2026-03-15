"""Tests for the mass production CLI entrypoint."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src import mass_production as cli_module


class TestParseArgs:
    """Tests for parse_args."""

    def test_defaults_to_dry_run(self):
        """Uses dry-run defaults when no run mode argument is provided."""
        with patch.object(sys, "argv", ["mass_production.py"]):
            args = cli_module.parse_args()

        assert args.dry_run is True

    def test_accepts_real_run(self):
        """Parses explicit real-run mode."""
        with patch.object(
            sys,
            "argv",
            [
                "mass_production.py",
                "--real-run",
            ],
        ):
            args = cli_module.parse_args()

        assert args.dry_run is False


class TestMain:
    """Tests for main."""

    def test_main_configures_path_and_forwards_args_to_pipeline(self):
        """Forwards only dry_run to pipeline and uses constants for display settings."""
        fake_run_pipeline = MagicMock()
        fake_pipeline_module = SimpleNamespace(run_pipeline=fake_run_pipeline)
        fake_args = SimpleNamespace(dry_run=False)
        fake_constants_module = SimpleNamespace(
            REVIEW_DESIGNS=False,
            IDEAS_PER_KEYWORD=20,
            ENABLE_PROGRESS_UI=True,
            FILTERED_IDEAS_PER_KEYWORD=10,
            BACKGROUND_REMOVAL_MODE="manual",
        )

        with (
            patch.object(cli_module, "_configure_module_path") as mock_configure,
            patch.object(cli_module, "parse_args", return_value=fake_args),
            patch.object(
                cli_module,
                "_confirm_runtime_settings",
                return_value=True,
            ) as mock_confirm,
            patch.dict(
                sys.modules,
                {
                    "pipeline": fake_pipeline_module,
                    "constants": fake_constants_module,
                },
            ),
        ):
            cli_module.main()

        mock_configure.assert_called_once_with()
        mock_confirm.assert_called_once_with(
            {
                "REVIEW_DESIGNS": False,
                "IDEAS_PER_KEYWORD": 20,
                "ENABLE_PROGRESS_UI": True,
                "FILTERED_IDEAS_PER_KEYWORD": 10,
                "BACKGROUND_REMOVAL_MODE": "manual",
                "dry run": False,
            }
        )
        fake_run_pipeline.assert_called_once_with(
            dry_run=False,
        )

    def test_main_aborts_when_user_rejects_settings(self):
        """Stops before pipeline execution when runtime setting confirmation is rejected."""
        fake_run_pipeline = MagicMock()
        fake_pipeline_module = SimpleNamespace(run_pipeline=fake_run_pipeline)
        fake_args = SimpleNamespace(dry_run=True)
        fake_constants_module = SimpleNamespace(
            REVIEW_DESIGNS=True,
            IDEAS_PER_KEYWORD=20,
            ENABLE_PROGRESS_UI=True,
            FILTERED_IDEAS_PER_KEYWORD=10,
            BACKGROUND_REMOVAL_MODE="manual",
        )

        with (
            patch.object(cli_module, "_configure_module_path") as mock_configure,
            patch.object(cli_module, "parse_args", return_value=fake_args),
            patch.object(cli_module, "_confirm_runtime_settings", return_value=False),
            patch.dict(
                sys.modules,
                {
                    "pipeline": fake_pipeline_module,
                    "constants": fake_constants_module,
                },
            ),
        ):
            cli_module.main()

        mock_configure.assert_called_once_with()
        fake_run_pipeline.assert_not_called()
