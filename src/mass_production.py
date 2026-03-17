"""CLI entrypoint for the mass production automation workflow."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from schedule.logger_config import log_action


def _open_actions_log_in_vscode() -> None:
    """Open meta/actions.log in VS Code and try to focus latest entries.

    This is best-effort behavior and does nothing if the `code` CLI is unavailable.
    """
    code_cli = shutil.which("code")
    if code_cli is None:
        log_action("VS Code CLI not found; skipping actions.log auto-open")
        return

    actions_log = Path(__file__).resolve().parents[2] / "meta" / "actions.log"
    try:
        # Jumping to a very large line opens at/near the bottom of the file.
        subprocess.run(
            [code_cli, "--reuse-window", "--goto", f"{actions_log}:999999"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Best effort: close the primary side bar if this CLI flag is supported.
        subprocess.run(
            [code_cli, "--reuse-window", "--command", "workbench.action.closeSidebar"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        log_action(f"Failed to trigger VS Code actions.log focus: {exc}")


def _configure_module_path() -> None:
    log_action("Configuring module path for mass production workflow")
    """Expose src/mass_production modules to the runtime import path."""
    module_dir = Path(__file__).resolve().parent / "mass_production"
    sys.path.insert(0, str(module_dir))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the mass production pipeline.

    Returns:
        Parsed argument namespace.
    """
    log_action("Parsing command-line arguments for mass production pipeline")
    parser = argparse.ArgumentParser(description="Run the mass production pipeline")
    run_mode = parser.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Skip Printify draft creation and only save the generated payloads",
    )
    run_mode.add_argument(
        "--real-run",
        dest="dry_run",
        action="store_false",
        help="Upload artwork to Printify and create draft products",
    )
    parser.set_defaults(dry_run=True)
    parser.add_argument(
        "--keyword-limit",
        type=int,
        default=25,
        help="Maximum number of keywords to process from data/ideas.csv",
    )
    parser.add_argument(
        "--ideas-per-keyword",
        type=int,
        default=2,
        help="Number of generated ideas per keyword",
    )
    return parser.parse_args()


def _confirm_runtime_settings(settings: dict[str, Any]) -> bool:
    """Print selected runtime settings and require explicit user confirmation.

    Args:
        settings: Mapping of setting names to values to display.

    Returns:
        True when user confirms with y/yes, else False.
    """
    log_action("Displaying runtime settings and waiting for confirmation")
    header = "Mass Production Runtime Settings"
    separator = "=" * 52
    print(f"\n{separator}")
    print(header)
    print(separator)
    for key, value in settings.items():
        print(f"{key:<32} : {value}")
    print(separator)

    user_input = input("Confirm these settings? (yes to continue): ").strip().lower()
    is_confirmed = user_input in {"y", "yes"}
    if is_confirmed:
        log_action("Runtime settings confirmed by user")
        return True

    log_action("Runtime settings rejected by user; aborting run")
    print("Aborted by user.")
    return False


def main() -> None:
    """Run the pipeline using command-line arguments."""
    _configure_module_path()
    import config.constants as constants
    from pipeline import Orchestrator

    args = parse_args()
    settings_to_confirm: dict[str, Any] = {
        "REVIEW_DESIGNS": constants.REVIEW_DESIGNS,
        "IDEAS_PER_KEYWORD": constants.IDEAS_PER_KEYWORD,
        "ENABLE_PROGRESS_UI": constants.ENABLE_PROGRESS_UI,
        "SCHEDULE_NEW_PRODUCTS": constants.SCHEDULE_NEW_PRODUCTS,
        "FILTERED_IDEAS_PER_KEYWORD": constants.FILTERED_IDEAS_PER_KEYWORD,
        "BACKGROUND_REMOVAL_MODE": constants.BACKGROUND_REMOVAL_MODE,
        "dry run": args.dry_run,
    }
    if not _confirm_runtime_settings(settings_to_confirm):
        return

    pipeline: Orchestrator = Orchestrator(dry_run=args.dry_run)
    pipeline.run_pipeline()


if __name__ == "__main__":
    log_action("'MASS PRODUCTION' -------------------------------\n")
    _open_actions_log_in_vscode()
    main()
