"""Payload parsing tests."""
from __future__ import annotations

from models import WaterMonitorPayload


def test_parses_sample_payload(sample_payload):
    payload = WaterMonitorPayload.model_validate(sample_payload)
    assert payload.device.name == "water-monitor"
    assert len(payload.tank_sensors) == 2
    assert payload.tank_by_name("External Tank Water Level").percent_full == 100
    assert payload.probe_by_name("External Air Temperature").temperature_c == 30.6


def test_ignores_unknown_fields(sample_payload):
    sample_payload["device"]["some_new_field"] = "surprise"
    sample_payload["tank_sensors"][0]["future_key"] = 42
    payload = WaterMonitorPayload.model_validate(sample_payload)  # must not raise
    assert payload.device.firmware_version == "1.28.0"


def test_missing_optional_values_become_none():
    minimal = {"device": {"name": "d"}, "tank_sensors": [{"name": "T"}], "temperature_probes": []}
    payload = WaterMonitorPayload.model_validate(minimal)
    assert payload.tank_by_name("T").percent_full is None
    assert payload.probe_by_name("nope") is None


def test_non_finite_readings_become_none(sample_payload):
    # A faulty probe/sensor can report NaN/Infinity (Python's json.loads accepts
    # these tokens). Left as floats they crash card formatting and serialise to
    # invalid JSON, so the model must coerce them to None.
    sample_payload["tank_sensors"][0]["percent_full"] = float("nan")
    sample_payload["tank_sensors"][0]["level_mm"] = float("inf")
    sample_payload["temperature_probes"][0]["temperature_c"] = float("-inf")
    payload = WaterMonitorPayload.model_validate(sample_payload)

    tank = payload.tank_by_name("External Tank Water Level")
    assert tank.percent_full is None
    assert tank.level_mm is None
    assert payload.probe_by_name("External Tank Water Temperature").temperature_c is None
