"""Tests for the mass production CLI entrypoint."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src import mass_production as cli_module


class TestParseArgs:
    """Tests for parse_args."""

    def test_defaults_to_dry_run_with_expected_limits(self):
        """Uses the documented default CLI values when no flags are provided."""
        with patch.object(sys, "argv", ["mass_production.py"]):
            args = cli_module.parse_args()

        assert args.dry_run is True
        assert args.keyword_limit == 25
        assert args.ideas_per_keyword == 2

    def test_accepts_real_run_and_custom_limits(self):
        """Parses explicit run-mode and limit overrides from the command line."""
        with patch.object(
            sys,
            "argv",
            [
                "mass_production.py",
                "--real-run",
                "--keyword-limit",
                "3",
                "--ideas-per-keyword",
                "4",
            ],
        ):
            args = cli_module.parse_args()

        assert args.dry_run is False
        assert args.keyword_limit == 3
        assert args.ideas_per_keyword == 4


class TestMain:
    """Tests for main."""

    def test_main_configures_path_and_forwards_args_to_pipeline(self):
        """Loads the pipeline module and forwards parsed CLI arguments unchanged."""
        fake_run_pipeline = MagicMock()
        fake_pipeline_module = SimpleNamespace(run_pipeline=fake_run_pipeline)
        fake_args = SimpleNamespace(dry_run=False, keyword_limit=7, ideas_per_keyword=5)

        with (
            patch.object(cli_module, "_configure_module_path") as mock_configure,
            patch.object(cli_module, "parse_args", return_value=fake_args),
            patch.dict(sys.modules, {"pipeline": fake_pipeline_module}),
        ):
            cli_module.main()

        mock_configure.assert_called_once_with()
        fake_run_pipeline.assert_called_once_with(
            dry_run=False,
            keyword_limit=7,
            ideas_per_keyword=5,
        )
