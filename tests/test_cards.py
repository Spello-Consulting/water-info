"""Card mapping + status/colour rule tests."""
from __future__ import annotations

import datetime as dt

from cards import build_card, build_cards
from config import CardConfig
from models import WaterMonitorPayload

NOW = dt.datetime(2026, 7, 28, 12, 0, tzinfo=dt.timezone.utc)


class FakeDB:
    """Stub DB returning fixed 24h min/max."""

    def __init__(self, lo=10, hi=90):
        self._lo, self._hi = lo, hi

    def tank_minmax_24h(self, sensor, now):
        return (self._lo, self._hi)

    def temp_minmax_24h(self, sensor, now):
        return (self._lo, self._hi)


def _payload(sample_payload):
    return WaterMonitorPayload.model_validate(sample_payload)


def _water_card(**kw):
    base = dict(sensor="External Tank Water Level", type="water", display_name="Ext")
    base.update(kw)
    return CardConfig(**base)


def test_water_card_ok(sample_payload):
    card = build_card(_water_card(warning_percent=40, critical_percent=20), _payload(sample_payload), FakeDB(), True, NOW)
    assert card.present and card.value == 100
    assert card.value_class == "value-ok"
    assert card.status == "ok" and card.status_label == "OK"
    assert card.value_int == "100" and card.unit == "%"


def test_water_warning_colour(sample_payload):
    sample_payload["tank_sensors"][0]["percent_full"] = 30
    card = build_card(_water_card(warning_percent=40, critical_percent=20), _payload(sample_payload), FakeDB(), True, NOW)
    assert card.value_class == "value-warning"


def test_water_critical_colour(sample_payload):
    sample_payload["tank_sensors"][0]["percent_full"] = 15
    card = build_card(_water_card(warning_percent=40, critical_percent=20), _payload(sample_payload), FakeDB(), True, NOW)
    assert card.value_class == "value-critical"


def test_status_from_payload(sample_payload):
    sample_payload["tank_sensors"][0]["status"] = "warning"
    card = build_card(_water_card(), _payload(sample_payload), FakeDB(), True, NOW)
    assert card.status == "warning" and card.status_label == "Warning"


def test_api_down_forces_error(sample_payload):
    card = build_card(_water_card(), _payload(sample_payload), FakeDB(), False, NOW)
    assert card.status == "error"
    assert card.value == 100  # last value retained


def test_missing_sensor_renders_null_card(sample_payload):
    card = build_card(_water_card(sensor="Nonexistent Tank"), _payload(sample_payload), FakeDB(), True, NOW)
    assert not card.present
    assert card.value is None and card.value_int == "--"
    assert card.status == "error"


def test_temperature_card_splits_decimal(sample_payload):
    card = build_card(
        CardConfig(sensor="External Air Temperature", type="temperature", display_name="Air"),
        _payload(sample_payload), FakeDB(lo=20.0, hi=31.0), True, NOW,
    )
    assert card.value_int == "30" and card.value_dec == ".6" and card.unit == "°C"
    assert card.min_str == "20.0°C" and card.max_str == "31.0°C"


def test_extra_sensor_excluded_and_order_preserved(sample_payload):
    # Only the configured cards appear, in config order; the second tank is omitted.
    cards_cfg = [
        _water_card(sensor="Internal Tank Water Level", display_name="Int"),
        CardConfig(sensor="External Air Temperature", type="temperature", display_name="Air"),
    ]
    views = build_cards(cards_cfg, _payload(sample_payload), FakeDB(), True, NOW)
    assert [v.display_name for v in views] == ["Int", "Air"]
