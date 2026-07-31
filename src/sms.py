"""SMS sending via Twilio.

Isolated in its own module so this functionality can later migrate into
SCLogging without touching the alert logic. Credentials come from the
environment (loaded from .env by scripts/launch.sh).

Two authentication styles are supported:

* **Account SID + Auth Token** (simplest):
    TWILIO_ACCOUNT_SID   = AC...           (your account SID)
    TWILIO_AUTH_TOKEN    = <account auth token>

* **API Key** (recommended by Twilio; revocable without changing the account):
    TWILIO_ACCOUNT_SID   = AC...           (still your account SID)
    TWILIO_API_KEY_SID   = SK...           (the API key SID)
    TWILIO_API_KEY_SECRET= <api key secret>

In both cases the account SID must be the ``AC...`` value — an API key (``SK...``)
is not an account SID and cannot be used in its place.

    TWILIO_FROM_NUMBER   = an E.164 number (+15005550006) or an alphanumeric
                           sender ID (<= 11 chars, e.g. "SpelloWater")

If credentials are missing, sending is skipped with a warning (email alerts
still function). This keeps the app runnable before Twilio is configured.
"""
from __future__ import annotations

import os

from twilio.base.exceptions import TwilioException
from twilio.rest import Client


def _build_client() -> tuple[Client | None, str | None]:
    """Construct a Twilio client from env vars, or return (None, reason)."""
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    api_key_sid = os.environ.get("TWILIO_API_KEY_SID")
    api_key_secret = os.environ.get("TWILIO_API_KEY_SECRET")

    # API-key auth: SK sid + secret authenticate, but the AC account SID is still
    # required for the resource path (/Accounts/{AccountSid}/Messages.json).
    if api_key_sid and api_key_secret:
        if not account_sid:
            return None, (
                "SMS not sent: TWILIO_API_KEY_SID/SECRET are set but "
                "TWILIO_ACCOUNT_SID (the AC... account SID) is missing — "
                "API-key auth still needs the account SID."
            )
        return Client(api_key_sid, api_key_secret, account_sid), None

    if account_sid and auth_token:
        # Catch the common mistake of putting an API key (SK...) in the SID slot.
        if account_sid.startswith("SK"):
            return None, (
                "SMS not sent: TWILIO_ACCOUNT_SID looks like an API key (SK...). "
                "Set it to your account SID (AC...) and put the API key in "
                "TWILIO_API_KEY_SID / TWILIO_API_KEY_SECRET."
            )
        return Client(account_sid, auth_token), None

    return None, "SMS not sent: Twilio credentials not configured in environment."


def sms_configured() -> bool:
    """True when Twilio credentials and a sender ID are present and consistent."""
    client, _ = _build_client()
    return client is not None and bool(os.environ.get("TWILIO_FROM_NUMBER"))


def send_sms(to_numbers: list[str], body: str, logger=None) -> bool:
    """Send ``body`` to each number in ``to_numbers``.

    Returns True if at least one message was accepted by Twilio. Returns False
    (and logs a warning) if credentials are missing or every send fails.
    """
    def _log(message: str, verbosity: str = "warning") -> None:
        if logger is not None:
            logger.log_message(message, verbosity)

    if not to_numbers:
        return False

    from_id = os.environ.get("TWILIO_FROM_NUMBER")
    if not from_id:
        _log("SMS not sent: TWILIO_FROM_NUMBER not configured.")
        return False

    client, error = _build_client()
    if client is None:
        _log(error)
        return False

    any_sent = False
    for number in to_numbers:
        try:
            client.messages.create(to=number, from_=from_id, body=body)
            any_sent = True
            _log(f"SMS alert sent to {number}.", "summary")
        except TwilioException as exc:
            _log(f"Failed to send SMS to {number}: {exc}", "error")
    return any_sent
