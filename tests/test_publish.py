"""Tests for publish.py.

Covers main(): missing schedule, today's filter, skip-published logic,
API call routing, email notification, CSV write-back, and summary output.
"""

from datetime import datetime
import sys
from types import ModuleType
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

import schedule.publish as publish_module


TODAY = datetime.now().strftime("%m/%d/%Y")
OTHER_DAY = "01/01/2000"


def make_schedule(tmp_path, rows: list) -> str:
    """Write a schedule DataFrame to a CSV in tmp_path and return the path string."""
    path = tmp_path / "schedule.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def row(
    publish_date: str = TODAY,
    product_id: str = "p1",
    shop_id: str = "s1",
    nick_name: str = "Test Shirt",
    publish_status: bool = False,
) -> dict:
    """Return a schedule row dict with sensible defaults."""
    return {
        "publish_date": publish_date,
        "product_id": product_id,
        "shop_id": shop_id,
        "nick_name": nick_name,
        "publish_status": publish_status,
    }


@pytest.fixture(autouse=True)
def stub_etsy_sync(request):
    """Stub Etsy mockup sync by default so publish tests do not sleep for one minute."""
    if (
        request.node.name == "test_waits_then_syncs_etsy_mockup_for_successful_publishes"
    ):
        yield
        return

    with patch("schedule.publish._sync_etsy_mockups_after_publish"):
        yield


class TestMain:
    """Tests for publish.main."""

    def test_prints_error_when_schedule_missing(self, tmp_path, capsys):
        """Prints an error message and returns early when the schedule file is absent."""
        missing = str(tmp_path / "nonexistent.csv")
        with patch("schedule.publish.load_api_token", return_value="tok"):
            publish_module.main(schedule_file=missing)

        assert "not found" in capsys.readouterr().out.lower()

    def test_does_not_publish_when_no_rows_match_today(self, tmp_path):
        """Does not call publish_product when no rows have today's date."""
        csv = make_schedule(tmp_path, [row(publish_date=OTHER_DAY)])
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product") as mock_pub,
            patch("schedule.publish.send_email"),
        ):
            publish_module.main(schedule_file=csv)

        mock_pub.assert_not_called()

    def test_publishes_todays_unpublished_product(self, tmp_path):
        """Calls publish_product with the correct arguments for an unpublished row."""
        csv = make_schedule(tmp_path, [row(product_id="p1", shop_id="s1")])
        mock_resp = MagicMock(status_code=200)
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch(
                "schedule.publish.publish_product", return_value=mock_resp
            ) as mock_pub,
            patch("schedule.publish.send_email"),
        ):
            publish_module.main(schedule_file=csv)

        mock_pub.assert_called_once_with("p1", "s1", "tok")

    def test_publishes_all_unpublished_products_for_today(self, tmp_path):
        """Calls publish_product for every unpublished product scheduled today."""
        rows = [row(product_id="p1"), row(product_id="p2")]
        csv = make_schedule(tmp_path, rows)
        mock_resp = MagicMock(status_code=200)
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch(
                "schedule.publish.publish_product", return_value=mock_resp
            ) as mock_pub,
            patch("schedule.publish.send_email"),
        ):
            publish_module.main(schedule_file=csv)

        assert mock_pub.call_count == 2
        mock_pub.assert_any_call("p1", "s1", "tok")
        mock_pub.assert_any_call("p2", "s1", "tok")

    def test_skips_already_published_product(self, tmp_path):
        """Does not call publish_product when publish_status is True."""
        csv = make_schedule(tmp_path, [row(publish_status=True)])
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product") as mock_pub,
            patch("schedule.publish.send_email"),
        ):
            publish_module.main(schedule_file=csv)

        mock_pub.assert_not_called()

    def test_sends_email_on_successful_publish(self, tmp_path):
        """Calls send_email once for each successfully published product."""
        csv = make_schedule(tmp_path, [row()])
        mock_resp = MagicMock(status_code=200)
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product", return_value=mock_resp),
            patch("schedule.publish.send_email") as mock_email,
        ):
            publish_module.main(schedule_file=csv)

        mock_email.assert_called_once()

    def test_does_not_send_email_on_failed_publish(self, tmp_path):
        """Does not call send_email when publish returns a non-200 status code."""
        csv = make_schedule(tmp_path, [row()])
        mock_resp = MagicMock(status_code=422, text="Unprocessable")
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product", return_value=mock_resp),
            patch("schedule.publish.send_email") as mock_email,
        ):
            publish_module.main(schedule_file=csv)

        mock_email.assert_not_called()

    def test_updates_csv_publish_status_to_true_on_success(self, tmp_path):
        """Writes True to publish_status in the CSV for a successfully published product."""
        csv = make_schedule(tmp_path, [row(product_id="p1")])
        mock_resp = MagicMock(status_code=200)
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product", return_value=mock_resp),
            patch("schedule.publish.send_email"),
        ):
            publish_module.main(schedule_file=csv)

        updated = pd.read_csv(csv)
        assert bool(updated.loc[0, "publish_status"]) is True

    def test_does_not_update_csv_status_on_failed_publish(self, tmp_path):
        """Leaves publish_status False in the CSV when publish fails."""
        csv = make_schedule(tmp_path, [row(product_id="p1")])
        mock_resp = MagicMock(status_code=500, text="Server Error")
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product", return_value=mock_resp),
            patch("schedule.publish.send_email"),
        ):
            publish_module.main(schedule_file=csv)

        updated = pd.read_csv(csv)
        assert bool(updated.loc[0, "publish_status"]) is False

    def test_prints_done_summary_with_counts(self, tmp_path, capsys):
        """Prints a summary line reporting how many products were published."""
        csv = make_schedule(tmp_path, [row(), row(product_id="p2")])
        mock_resp = MagicMock(status_code=200)
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product", return_value=mock_resp),
            patch("schedule.publish.send_email"),
        ):
            publish_module.main(schedule_file=csv)

        out = capsys.readouterr().out
        assert "2/2" in out

    def test_mixed_rows_only_publishes_unpublished(self, tmp_path):
        """Publishes only the unpublished product when one row is already done."""
        rows = [row(product_id="p1", publish_status=True), row(product_id="p2")]
        csv = make_schedule(tmp_path, rows)
        mock_resp = MagicMock(status_code=200)
        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch(
                "schedule.publish.publish_product", return_value=mock_resp
            ) as mock_pub,
            patch("schedule.publish.send_email"),
        ):
            publish_module.main(schedule_file=csv)

        mock_pub.assert_called_once_with("p2", "s1", "tok")

    def test_waits_then_syncs_etsy_mockup_for_successful_publishes(self, tmp_path):
        """Waits one minute and invokes Etsy mockup sync for products published this run."""
        csv = make_schedule(
            tmp_path, [row(product_id="p1", shop_id="s1", nick_name="Folder One")]
        )
        mock_resp = MagicMock(status_code=200)
        fake_sync = MagicMock()
        fake_clients_pkg = ModuleType("clients")
        fake_add_etsy_mockup_module = ModuleType("clients.add_etsy_mockup")
        setattr(
            fake_add_etsy_mockup_module,
            "add_mockups_for_published_products",
            fake_sync,
        )

        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product", return_value=mock_resp),
            patch("schedule.publish.send_email"),
            patch("schedule.publish.time.sleep") as mock_sleep,
            patch.dict(
                sys.modules,
                {
                    "clients": fake_clients_pkg,
                    "clients.add_etsy_mockup": fake_add_etsy_mockup_module,
                },
                clear=False,
            ),
            patch.object(
                publish_module,
                "_configure_mass_production_module_path",
            ) as mock_configure,
        ):
            publish_module.main(schedule_file=csv)

        mock_sleep.assert_called_once_with(60)
        mock_configure.assert_called_once_with()
        fake_sync.assert_called_once_with(
            [{"product_id": "p1", "shop_id": "s1", "nick_name": "Folder One"}]
        )

    def test_does_not_wait_for_etsy_mockup_sync_when_nothing_published(self, tmp_path):
        """Skips the Etsy mockup sync branch when no products were published successfully."""
        csv = make_schedule(tmp_path, [row(product_id="p1", publish_status=True)])

        with (
            patch("schedule.publish.load_api_token", return_value="tok"),
            patch("schedule.publish.publish_product") as mock_publish,
            patch("schedule.publish.send_email"),
            patch("schedule.publish.time.sleep") as mock_sleep,
        ):
            publish_module.main(schedule_file=csv)

        mock_publish.assert_not_called()
        mock_sleep.assert_not_called()
