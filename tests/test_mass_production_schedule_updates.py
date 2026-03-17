"""Tests for mass_production.schedule_updates."""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

MASS_PRODUCTION_ROOT = (
    Path(__file__).resolve().parent.parent / "src" / "mass_production"
)
if str(MASS_PRODUCTION_ROOT) not in sys.path:
    sys.path.insert(0, str(MASS_PRODUCTION_ROOT))

import product.schedule_updates as schedule_updates_module  # noqa: E402
import config.constants as constants  # noqa: E402


class TestScheduleUpdates:
    """Tests for schedule update helper behavior."""

    def test_choose_publish_date_prefers_empty_day(self) -> None:
        """Chooses an unused date in range before any date that already has one row."""
        today = date(2026, 3, 15)
        occupied = today + timedelta(days=4)
        rows = [
            {"publish_date": occupied.strftime(schedule_updates_module.DATE_FORMAT)}
        ]

        result = schedule_updates_module.choose_publish_date(rows, today)

        assert result == (today + timedelta(days=5)).strftime(
            schedule_updates_module.DATE_FORMAT
        )

    def test_choose_publish_date_reuses_lowest_count_when_window_full(self) -> None:
        """When every day is occupied, picks earliest date with the minimum current count."""
        today = date(2026, 3, 15)
        window_start = today + timedelta(
            days=schedule_updates_module.MIN_PUBLISH_OFFSET_DAYS
        )
        window_end = today + timedelta(
            days=schedule_updates_module.MAX_PUBLISH_OFFSET_DAYS
        )

        rows = []
        current = window_start
        while current <= window_end:
            rows.append(
                {"publish_date": current.strftime(schedule_updates_module.DATE_FORMAT)}
            )
            current = current + timedelta(days=1)

        rows.append(
            {"publish_date": window_start.strftime(schedule_updates_module.DATE_FORMAT)}
        )

        result = schedule_updates_module.choose_publish_date(rows, today)

        assert result == (window_start + timedelta(days=1)).strftime(
            schedule_updates_module.DATE_FORMAT
        )

    def test_append_created_product_writes_both_csvs(self, tmp_path) -> None:
        """Appends one row to data and auto-publish schedules with balanced date selection."""
        data_schedule = tmp_path / "data_schedule.csv"
        auto_schedule = tmp_path / "auto_schedule.csv"
        data_schedule.write_text(
            (
                "nick_name,product_id,shop_id,publish_status,publish_date\n"
                "existing,p-0,s-0,False,03/20/2026\n"
            ),
            encoding="utf-8",
        )
        auto_schedule.write_text(
            "nick_name,product_id,shop_id,publish_status,publish_date\n",
            encoding="utf-8",
        )

        with (
            patch.object(
                schedule_updates_module,
                "DATA_SCHEDULE_PATH",
                data_schedule,
            ),
            patch.object(
                schedule_updates_module,
                "AUTO_PUBLISH_SCHEDULE_PATH",
                auto_schedule,
            ),
            patch.object(
                schedule_updates_module, "load_shop_id", return_value="shop-xyz"
            ),
            patch.object(
                schedule_updates_module,
                "choose_publish_date",
                return_value="03/21/2026",
            ),
            patch.object(
                constants,
                "SCHEDULE_NEW_PRODUCTS",
                True,
            ),
        ):
            appended = schedule_updates_module.append_created_product_to_schedules(
                product_title="Alpha Tee",
                product_id="prod-123",
            )

        assert appended is True

        with open(data_schedule, "r", encoding="utf-8", newline="") as file_handle:
            data_rows = list(csv.DictReader(file_handle))
        with open(auto_schedule, "r", encoding="utf-8", newline="") as file_handle:
            auto_rows = list(csv.DictReader(file_handle))

        assert data_rows[-1] == {
            "nick_name": "Alpha Tee",
            "product_id": "prod-123",
            "shop_id": "shop-xyz",
            "publish_status": "False",
            "publish_date": "03/21/2026",
        }
        assert auto_rows[-1] == data_rows[-1]

    def test_append_created_product_skips_existing_product_id(self, tmp_path) -> None:
        """Skips insertion when product_id already exists in data/schedule.csv."""
        data_schedule = tmp_path / "data_schedule.csv"
        auto_schedule = tmp_path / "auto_schedule.csv"
        data_schedule.write_text(
            (
                "nick_name,product_id,shop_id,publish_status,publish_date\n"
                "existing,prod-1,s-0,False,03/20/2026\n"
            ),
            encoding="utf-8",
        )
        auto_schedule.write_text(
            "nick_name,product_id,shop_id,publish_status,publish_date\n",
            encoding="utf-8",
        )

        with (
            patch.object(schedule_updates_module, "DATA_SCHEDULE_PATH", data_schedule),
            patch.object(
                schedule_updates_module,
                "AUTO_PUBLISH_SCHEDULE_PATH",
                auto_schedule,
            ),
            patch.object(
                schedule_updates_module, "load_shop_id", return_value="shop-xyz"
            ),
            patch.object(
                constants,
                "SCHEDULE_NEW_PRODUCTS",
                True,
            ),
        ):
            appended = schedule_updates_module.append_created_product_to_schedules(
                product_title="Alpha Tee",
                product_id="prod-1",
            )

        assert appended is False

        with open(data_schedule, "r", encoding="utf-8", newline="") as file_handle:
            data_rows = list(csv.DictReader(file_handle))
        with open(auto_schedule, "r", encoding="utf-8", newline="") as file_handle:
            auto_rows = list(csv.DictReader(file_handle))

        assert len(data_rows) == 1
        assert auto_rows == []

    def test_append_created_product_skips_when_scheduling_disabled(
        self, tmp_path
    ) -> None:
        """Skips insertion when scheduling is disabled by constants flag."""
        data_schedule = tmp_path / "data_schedule.csv"
        auto_schedule = tmp_path / "auto_schedule.csv"
        data_schedule.write_text(
            "nick_name,product_id,shop_id,publish_status,publish_date\n",
            encoding="utf-8",
        )
        auto_schedule.write_text(
            "nick_name,product_id,shop_id,publish_status,publish_date\n",
            encoding="utf-8",
        )

        with (
            patch.object(schedule_updates_module, "DATA_SCHEDULE_PATH", data_schedule),
            patch.object(
                schedule_updates_module,
                "AUTO_PUBLISH_SCHEDULE_PATH",
                auto_schedule,
            ),
            patch.object(
                constants,
                "SCHEDULE_NEW_PRODUCTS",
                False,
            ),
        ):
            appended = schedule_updates_module.append_created_product_to_schedules(
                product_title="Alpha Tee",
                product_id="prod-123",
            )

        assert appended is False

        with open(data_schedule, "r", encoding="utf-8", newline="") as file_handle:
            data_rows = list(csv.DictReader(file_handle))
        with open(auto_schedule, "r", encoding="utf-8", newline="") as file_handle:
            auto_rows = list(csv.DictReader(file_handle))

        assert data_rows == []
        assert auto_rows == []
