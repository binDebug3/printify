"""
Gmail notification module for sending emails through the Gmail API.
This module provides functionality to authenticate with Google's Gmail API,
retrieve email credentials, and send emails. It handles OAuth2 authentication,
credential storage and refresh, and includes error handling for failed email sends.
The module uses the Google Auth library for authentication and the Gmail API
for sending messages. Credentials are cached locally to avoid repeated authentication.
Typical usage example:
    # Send email to default recipient
    success, message_id = send_email(
        subject="Test Subject",
        message_text="Test message body"
    )
    # Send email to specific recipient
    success, message_id = send_email(
        subject="Test Subject",
        message_text="Test message body",
        recipient="user@example.com"
    )
Configuration:
    - Requires credentials.json file for initial OAuth2 setup
    - Uses mail_token.pickle for caching credentials
    - Requires email_address.txt for default recipient email
"""


import base64
import os.path
from typing import Tuple, Optional, Dict, Any
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.discovery import Resource

from logger_config import log_action


# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']


def get_credentials() -> Credentials:
    """
    Gets valid user credentials from storage.
    If this function doesn't work, delete the token.json file and try again
    Returns:
        creds: The obtained credentials.
    """
    creds: Credentials = None  # type: ignore
    mail_token: str = "../meta/mail_token.pickle"
    mail_credentials: str = "../meta/cal_credentials.json"
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists(mail_token):
        creds = Credentials.from_authorized_user_file(mail_token, SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                mail_credentials, SCOPES)
            creds = flow.run_local_server(port=0)  # type: ignore

        # Save the credentials for the next run
        with open(mail_token, 'w', encoding='utf-8') as token:
            token.write(creds.to_json())
    return creds


def get_default_recipient() -> str:
    """
    Reads the default email recipient from a local text file.
    Returns:
        recipient: The email address of the default recipient.
    """
    recipient_file: str = "../meta/email_address.txt"
    if not os.path.exists(recipient_file):
        err_msg: str = f"Error: Recipient file not found at '{recipient_file}'."
        log_action(err_msg)
        raise FileNotFoundError(err_msg)
    
    with open(recipient_file, 'r', encoding='utf-8') as f:
        recipient: str = f.read().strip()
    log_action(f"Default email recipient loaded from '{recipient_file}'")
    return recipient


def send_email(subject: str, 
               message_text: str, 
               recipient: Optional[str] = None
               ) -> Tuple[bool, str | None]:
    """
    Send an email from the user's account.
    :param
        subject: (string) The subject of the email message.
        message_text: (string) The text of the email message.
        recipient: (string) The email address of the recipient.
    :return:
        success: (bool) True if the email was sent successfully, False otherwise.
        message_id: (string) The ID of the sent message if successful, None otherwise.
    """
    log_action("Loading credentials for sending an email")
    try:
        creds: Credentials = get_credentials()
    except RefreshError as e:
        log_action(f"Credential refresh failed: {e}")
        log_action("Credentials might be expired. "
                   "Delete the file 'mail_token.pickle' and try again.")
        return False, None
    
    if recipient is None:
        log_action("No recipient provided, loading default recipient from file")
        recipient = get_default_recipient()

    try:
        # Call the Gmail API
        log_action("Building Gmail service")
        service: Resource = build('gmail', 'v1', credentials=creds, cache_discovery=False)

        # Create the email message
        message: MIMEText = MIMEText(message_text)
        message['to'] = recipient
        message['subject'] = subject

        # Send the email message
        log_action(f"Sending email to {recipient} with subject '{subject}'")
        create_message: Dict[str, Any] = {
            'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        send_message = (service.users().messages().send(  # pylint: disable=no-member #type: ignore
            userId='me', 
            body=create_message).execute())
        return True, send_message['id']

    except HttpError as error:
        err_msg: str = f'An error occurred while sending email: {error}'
        log_action(err_msg)
        print(err_msg)
        return False, None


if __name__ == "__main__":
    # Example usage
    log_action("'NOTIFICATION' script started --------------------------------------")
    success, message_id = send_email(
        subject="Test Email from Printify Automation",
        message_text="This is a test email sent from the Printify automation tool."
    )
    if success:
        print(f"Email sent successfully with message ID: {message_id}")
    else:
        print("Failed to send email.")
