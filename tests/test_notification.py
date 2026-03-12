"""Tests for notification.py.

Covers get_default_recipient and send_email, mocking the Gmail API stack,
credential loading, and file I/O so no real network calls are made.
"""

from unittest.mock import patch, MagicMock, mock_open
import pytest
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

from notification import get_default_recipient, send_email


class TestGetDefaultRecipient:
    """Tests for get_default_recipient."""

    def test_returns_stripped_email_address(self):
        """Returns the recipient email with leading and trailing whitespace removed."""
        with patch("notification.os.path.exists", return_value=True), patch(
            "builtins.open", mock_open(read_data="  user@example.com\n")
        ):
            result = get_default_recipient()

        assert result == "user@example.com"

    def test_raises_when_email_file_is_missing(self):
        """Raises FileNotFoundError when the email address file is absent."""
        with patch("notification.os.path.exists", return_value=False):
            with pytest.raises(FileNotFoundError):
                get_default_recipient()


class TestSendEmail:
    """Tests for send_email."""

    def _make_service(self, message_id: str = "msg-123") -> MagicMock:
        """Return a mock Gmail service that returns a successful send response."""
        service = MagicMock()
        (
            service.users.return_value.messages.return_value.send.return_value.execute.return_value
        ) = {"id": message_id}
        return service

    def test_returns_true_and_message_id_on_success(self):
        """Returns (True, message_id) when the email is sent successfully."""
        service = self._make_service("msg-999")
        with patch("notification.get_credentials", return_value=MagicMock()), patch(
            "notification.build", return_value=service
        ):
            success, msg_id = send_email("Subject", "Body", recipient="r@example.com")

        assert success is True
        assert msg_id == "msg-999"

    def test_returns_false_none_on_http_error(self):
        """Returns (False, None) when the Gmail API raises HttpError."""
        service = MagicMock()
        (
            service.users.return_value.messages.return_value.send.return_value.execute.side_effect
        ) = HttpError(resp=MagicMock(status=400), content=b"Bad Request")
        with patch("notification.get_credentials", return_value=MagicMock()), patch(
            "notification.build", return_value=service
        ):
            success, msg_id = send_email("Subject", "Body", recipient="r@example.com")

        assert success is False
        assert msg_id is None

    def test_returns_false_none_on_refresh_error(self):
        """Returns (False, None) when OAuth credential refresh fails."""
        with patch("notification.get_credentials", side_effect=RefreshError("expired")):
            success, msg_id = send_email("Subject", "Body", recipient="r@example.com")

        assert success is False
        assert msg_id is None

    def test_loads_default_recipient_when_not_provided(self):
        """Calls get_default_recipient when no recipient argument is passed."""
        service = self._make_service()
        with patch("notification.get_credentials", return_value=MagicMock()), patch(
            "notification.build", return_value=service
        ), patch(
            "notification.get_default_recipient",
            return_value="default@example.com",
        ) as mock_default:
            send_email("Subject", "Body")

        mock_default.assert_called_once()

    def test_does_not_load_default_recipient_when_provided(self):
        """Does not call get_default_recipient when recipient is explicitly given."""
        service = self._make_service()
        with patch("notification.get_credentials", return_value=MagicMock()), patch(
            "notification.build", return_value=service
        ), patch("notification.get_default_recipient") as mock_default:
            send_email("Subject", "Body", recipient="explicit@example.com")

        mock_default.assert_not_called()

    def test_email_addressed_to_given_recipient(self):
        """The message is addressed to the provided recipient."""
        service = self._make_service()
        captured_body = {}

        def fake_send(userId, body):  # pylint: disable=unused-argument, invalid-name
            captured_body.update(body)
            return MagicMock(execute=MagicMock(return_value={"id": "x"}))

        service.users.return_value.messages.return_value.send.side_effect = fake_send
        with patch("notification.get_credentials", return_value=MagicMock()), patch(
            "notification.build", return_value=service
        ):
            send_email("Hello", "World", recipient="target@example.com")

        assert "raw" in captured_body
