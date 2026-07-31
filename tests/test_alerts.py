"""Alert hysteresis state-machine tests."""
from __future__ import annotations

import pytest

import alerts as alerts_module
from alerts import EMAIL, SMS, AlertManager
from config import CardConfig
from models import WaterMonitorPayload


class FakeLogger:
    def __init__(self):
        self.emails = []

    def send_email(self, subject, body):
        self.emails.append((subject, body))
        return True

    def log_message(self, message, verbosity="summary"):
        pass


class FakeConfig:
    """Minimal AppConfig stand-in exposing what AlertManager uses."""

    def __init__(self, cards, sms_enabled=False, sms_numbers=None):
        self._cards = cards
        self.sms_enabled = sms_enabled
        self.sms_to_numbers = sms_numbers or []

    def cards(self):
        return self._cards


def _payload(pct):
    return WaterMonitorPayload.model_validate({
        "device": {"name": "d"},
        "tank_sensors": [{"name": "Ext", "percent_full": pct, "status": "ok"}],
        "temperature_probes": [],
    })


def _card(**kw):
    base = dict(sensor="Ext", type="water", display_name="Ext",
                email_alert_percent=20, email_recovery_percent=30)
    base.update(kw)
    return CardConfig(**base)


@pytest.fixture
def sms_spy(monkeypatch):
    calls = []
    monkeypatch.setattr(alerts_module.sms, "send_sms", lambda numbers, body, logger=None: calls.append((numbers, body)) or True)
    return calls


def test_email_fires_once_then_holds():
    logger = FakeLogger()
    mgr = AlertManager(FakeConfig([_card()]), logger)

    mgr.evaluate(_payload(50), True)   # above alert -> nothing
    assert logger.emails == []
    mgr.evaluate(_payload(15), True)   # below alert -> fire
    assert len(logger.emails) == 1
    mgr.evaluate(_payload(12), True)   # still low -> no repeat
    assert len(logger.emails) == 1
    assert mgr.is_alerted("Ext", EMAIL)


def test_email_rearms_after_recovery():
    logger = FakeLogger()
    mgr = AlertManager(FakeConfig([_card()]), logger)

    mgr.evaluate(_payload(15), True)   # fire alert
    assert len(logger.emails) == 1
    assert "fallen" in logger.emails[-1][1].lower()
    mgr.evaluate(_payload(25), True)   # above alert but below recovery(30) -> stays alerted, no mail
    assert len(logger.emails) == 1
    mgr.evaluate(_payload(35), True)   # >= recovery -> recovery notification + re-arm
    assert len(logger.emails) == 2
    assert "recovered" in logger.emails[-1][1].lower()
    assert not mgr.is_alerted("Ext", EMAIL)
    mgr.evaluate(_payload(15), True)   # drops again -> alert again
    assert len(logger.emails) == 3
    assert "fallen" in logger.emails[-1][1].lower()


def test_recovery_notification_on_both_channels(sms_spy):
    logger = FakeLogger()
    card = _card(email_alert_percent=20, email_recovery_percent=30, sms_alert_percent=20, sms_recovery_percent=30)
    mgr = AlertManager(FakeConfig([card], sms_enabled=True, sms_numbers=["+61400"]), logger)

    mgr.evaluate(_payload(10), True)   # alert on both channels
    assert len(logger.emails) == 1 and len(sms_spy) == 1
    mgr.evaluate(_payload(30), True)   # recover on both channels -> one recovery notice each
    assert len(logger.emails) == 2 and len(sms_spy) == 2
    assert "recovered" in logger.emails[-1][1].lower()
    assert "recovered" in sms_spy[-1][1].lower()
    assert not mgr.is_alerted("Ext", EMAIL) and not mgr.is_alerted("Ext", SMS)
    # no duplicate recovery while it stays high
    mgr.evaluate(_payload(40), True)
    assert len(logger.emails) == 2 and len(sms_spy) == 2


def test_no_alert_when_api_down_or_value_missing():
    logger = FakeLogger()
    mgr = AlertManager(FakeConfig([_card()]), logger)
    mgr.evaluate(_payload(5), False)   # API down -> no fire, no state change
    assert logger.emails == []
    assert not mgr.is_alerted("Ext", EMAIL)
    mgr.evaluate(None, True)           # no payload -> no fire
    assert logger.emails == []


def test_sms_only_when_enabled(sms_spy):
    logger = FakeLogger()
    card = _card(sms_alert_percent=15, sms_recovery_percent=25)

    # SMS disabled -> no SMS even below threshold
    mgr = AlertManager(FakeConfig([card], sms_enabled=False), logger)
    mgr.evaluate(_payload(10), True)
    assert sms_spy == []

    # SMS enabled -> fires
    mgr2 = AlertManager(FakeConfig([card], sms_enabled=True, sms_numbers=["+61400"]), logger)
    mgr2.evaluate(_payload(10), True)
    assert len(sms_spy) == 1
    assert mgr2.is_alerted("Ext", SMS)


def test_channels_independent(sms_spy):
    logger = FakeLogger()
    # email alert at 20, sms alert at 15
    card = _card(email_alert_percent=20, email_recovery_percent=30, sms_alert_percent=15, sms_recovery_percent=25)
    mgr = AlertManager(FakeConfig([card], sms_enabled=True, sms_numbers=["+61400"]), logger)

    mgr.evaluate(_payload(18), True)   # below email(20) not sms(15) -> email only
    assert len(logger.emails) == 1 and sms_spy == []
    assert mgr.is_alerted("Ext", EMAIL) and not mgr.is_alerted("Ext", SMS)

    mgr.evaluate(_payload(12), True)   # now below sms too -> sms fires, email holds
    assert len(logger.emails) == 1 and len(sms_spy) == 1
