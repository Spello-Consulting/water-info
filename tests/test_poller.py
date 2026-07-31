"""Tests for the poller's diagnostics builder."""
from __future__ import annotations

from config import CardConfig
from models import WaterMonitorPayload
from poller import build_diagnostics

CARDS = [
    CardConfig(sensor="External Tank Water Level", type="water", display_name="External Water %"),
    CardConfig(sensor="External Tank Water Temperature", type="temperature", display_name="External Water Temp"),
]


class FakeConfig:
    """Minimal stand-in exposing only ``cards()`` (all build_diagnostics uses)."""

    def cards(self):
        return CARDS


def test_build_diagnostics_none_payload():
    assert build_diagnostics(FakeConfig(), None) == []


def test_build_diagnostics_maps_names_and_fields(sample_payload):
    payload = WaterMonitorPayload.model_validate(sample_payload)
    rows = build_diagnostics(FakeConfig(), payload)

    # One row per tank sensor + temperature probe.
    assert len(rows) == len(payload.tank_sensors) + len(payload.temperature_probes)

    by_sensor = {row["sensor"]: row for row in rows}

    # Configured sensors resolve their friendly name and type.
    ext_tank = by_sensor["External Tank Water Level"]
    assert ext_tank["display_name"] == "External Water %"
    assert ext_tank["type"] == "water"
    # ``name`` is the key, not a field; other modeled fields are present.
    assert "name" not in ext_tank["fields"]
    assert ext_tank["fields"]["percent_full"] == 100
    # The raw sensor frame is carried through for the diagnostics page.
    assert ext_tank["fields"]["raw_hex"] == "ff 00 86 85"
    assert by_sensor["External Tank Water Temperature"]["fields"]["raw_hex"] == "78 01 4b 46 7f ff 0c 10 1c"

    # Unconfigured sensors fall back to the raw name / "unknown" type.
    unconfigured = by_sensor["Internal Tank Water Level"]
    assert unconfigured["display_name"] == "Internal Tank Water Level"
    assert unconfigured["type"] == "unknown"


def test_build_diagnostics_filters_to_one_sensor(sample_payload):
    payload = WaterMonitorPayload.model_validate(sample_payload)
    rows = build_diagnostics(FakeConfig(), payload, sensor="External Tank Water Level")

    assert len(rows) == 1
    assert rows[0]["sensor"] == "External Tank Water Level"
    assert rows[0]["display_name"] == "External Water %"


def test_build_diagnostics_unknown_sensor_is_empty(sample_payload):
    payload = WaterMonitorPayload.model_validate(sample_payload)
    assert build_diagnostics(FakeConfig(), payload, sensor="Nope") == []


def test_build_diagnostics_has_no_non_finite_floats(sample_payload):
    # A faulty probe can report NaN/Infinity; the model coerces these to None so
    # they never reach the (bare-NaN-emitting) JSON encoder or card formatting.
    sample_payload["temperature_probes"][0]["temperature_c"] = float("nan")
    sample_payload["tank_sensors"][0]["level_mm"] = float("inf")
    payload = WaterMonitorPayload.model_validate(sample_payload)
    rows = {row["sensor"]: row for row in build_diagnostics(FakeConfig(), payload)}

    assert rows["External Tank Water Temperature"]["fields"]["temperature_c"] is None
    assert rows["External Tank Water Level"]["fields"]["level_mm"] is None
