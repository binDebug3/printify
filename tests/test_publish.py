"""Tests for publish.py.

Covers main(): missing schedule, today's filter, skip-published logic,
API call routing, email notification, CSV write-back, and summary output.
"""

from datetime import datetime
from unittest.mock import patch, MagicMock
import pandas as pd

from publish import main


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


class TestMain:
    """Tests for publish.main."""

    def test_prints_error_when_schedule_missing(self, tmp_path, capsys):
        """Prints an error message and returns early when the schedule file is absent."""
        missing = str(tmp_path / "nonexistent.csv")
        with patch("publish.load_api_token", return_value="tok"):
            main(schedule_file=missing)

        assert "not found" in capsys.readouterr().out.lower()

    def test_does_not_publish_when_no_rows_match_today(self, tmp_path):
        """Does not call publish_product when no rows have today's date."""
        csv = make_schedule(tmp_path, [row(publish_date=OTHER_DAY)])
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product"
        ) as mock_pub, patch("publish.send_email"):
            main(schedule_file=csv)

        mock_pub.assert_not_called()

    def test_publishes_todays_unpublished_product(self, tmp_path):
        """Calls publish_product with the correct arguments for an unpublished row."""
        csv = make_schedule(tmp_path, [row(product_id="p1", shop_id="s1")])
        mock_resp = MagicMock(status_code=200)
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product", return_value=mock_resp
        ) as mock_pub, patch("publish.send_email"):
            main(schedule_file=csv)

        mock_pub.assert_called_once_with("p1", "s1", "tok")

    def test_publishes_all_unpublished_products_for_today(self, tmp_path):
        """Calls publish_product for every unpublished product scheduled today."""
        rows = [row(product_id="p1"), row(product_id="p2")]
        csv = make_schedule(tmp_path, rows)
        mock_resp = MagicMock(status_code=200)
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product", return_value=mock_resp
        ) as mock_pub, patch("publish.send_email"):
            main(schedule_file=csv)

        assert mock_pub.call_count == 2
        mock_pub.assert_any_call("p1", "s1", "tok")
        mock_pub.assert_any_call("p2", "s1", "tok")

    def test_skips_already_published_product(self, tmp_path):
        """Does not call publish_product when publish_status is True."""
        csv = make_schedule(tmp_path, [row(publish_status=True)])
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product"
        ) as mock_pub, patch("publish.send_email"):
            main(schedule_file=csv)

        mock_pub.assert_not_called()

    def test_sends_email_on_successful_publish(self, tmp_path):
        """Calls send_email once for each successfully published product."""
        csv = make_schedule(tmp_path, [row()])
        mock_resp = MagicMock(status_code=200)
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product", return_value=mock_resp
        ), patch("publish.send_email") as mock_email:
            main(schedule_file=csv)

        mock_email.assert_called_once()

    def test_does_not_send_email_on_failed_publish(self, tmp_path):
        """Does not call send_email when publish returns a non-200 status code."""
        csv = make_schedule(tmp_path, [row()])
        mock_resp = MagicMock(status_code=422, text="Unprocessable")
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product", return_value=mock_resp
        ), patch("publish.send_email") as mock_email:
            main(schedule_file=csv)

        mock_email.assert_not_called()

    def test_updates_csv_publish_status_to_true_on_success(self, tmp_path):
        """Writes True to publish_status in the CSV for a successfully published product."""
        csv = make_schedule(tmp_path, [row(product_id="p1")])
        mock_resp = MagicMock(status_code=200)
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product", return_value=mock_resp
        ), patch("publish.send_email"):
            main(schedule_file=csv)

        updated = pd.read_csv(csv)
        assert bool(updated.loc[0, "publish_status"]) is True

    def test_does_not_update_csv_status_on_failed_publish(self, tmp_path):
        """Leaves publish_status False in the CSV when publish fails."""
        csv = make_schedule(tmp_path, [row(product_id="p1")])
        mock_resp = MagicMock(status_code=500, text="Server Error")
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product", return_value=mock_resp
        ), patch("publish.send_email"):
            main(schedule_file=csv)

        updated = pd.read_csv(csv)
        assert bool(updated.loc[0, "publish_status"]) is False

    def test_prints_done_summary_with_counts(self, tmp_path, capsys):
        """Prints a summary line reporting how many products were published."""
        csv = make_schedule(tmp_path, [row(), row(product_id="p2")])
        mock_resp = MagicMock(status_code=200)
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product", return_value=mock_resp
        ), patch("publish.send_email"):
            main(schedule_file=csv)

        out = capsys.readouterr().out
        assert "2/2" in out

    def test_mixed_rows_only_publishes_unpublished(self, tmp_path):
        """Publishes only the unpublished product when one row is already done."""
        rows = [row(product_id="p1", publish_status=True), row(product_id="p2")]
        csv = make_schedule(tmp_path, rows)
        mock_resp = MagicMock(status_code=200)
        with patch("publish.load_api_token", return_value="tok"), patch(
            "publish.publish_product", return_value=mock_resp
        ) as mock_pub, patch("publish.send_email"):
            main(schedule_file=csv)

        mock_pub.assert_called_once_with("p2", "s1", "tok")
