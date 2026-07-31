"""Twilio auth-selection and send tests (no real network)."""
from __future__ import annotations

import pytest

import sms as sms_module

TWILIO_VARS = [
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
    "TWILIO_API_KEY_SID", "TWILIO_API_KEY_SECRET", "TWILIO_FROM_NUMBER",
]


class FakeMessages:
    def __init__(self, sink):
        self._sink = sink

    def create(self, to, from_, body):
        self._sink.append({"to": to, "from_": from_, "body": body})


class FakeClient:
    """Captures constructor args and message sends."""

    instances = []

    def __init__(self, *args):
        self.args = args
        self.sent = []
        self.messages = FakeMessages(self.sent)
        FakeClient.instances.append(self)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in TWILIO_VARS:
        monkeypatch.delenv(var, raising=False)
    FakeClient.instances = []
    monkeypatch.setattr(sms_module, "Client", FakeClient)


def test_api_key_auth_passes_account_sid(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK456")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "SpelloWater")

    assert sms_module.send_sms(["+393311194199"], "hi") is True
    client = FakeClient.instances[-1]
    # API key sid + secret + account sid (AC...) in the URL path
    assert client.args == ("SK456", "secret", "AC123")
    assert client.sent[0]["from_"] == "SpelloWater"


def test_account_token_auth(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15005550006")

    assert sms_module.send_sms(["+393311194199"], "hi") is True
    assert FakeClient.instances[-1].args == ("AC123", "tok")


def test_api_key_without_account_sid_is_rejected(monkeypatch):
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK456")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "SpelloWater")

    assert sms_module.send_sms(["+39331"], "hi") is False
    assert FakeClient.instances == []  # never constructed a client


def test_api_key_in_account_sid_slot_is_caught(monkeypatch):
    # The exact original misconfiguration: SK... in TWILIO_ACCOUNT_SID + token.
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "SK0de4df")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "SpelloWater")

    assert sms_module.send_sms(["+39331"], "hi") is False
    assert FakeClient.instances == []


def test_missing_from_number(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    assert sms_module.send_sms(["+39331"], "hi") is False


def test_no_credentials(monkeypatch):
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "SpelloWater")
    assert sms_module.send_sms(["+39331"], "hi") is False
    assert FakeClient.instances == []


def test_sms_configured(monkeypatch):
    assert sms_module.sms_configured() is False
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "SpelloWater")
    assert sms_module.sms_configured() is True
