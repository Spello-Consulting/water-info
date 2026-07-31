"""Data-source tests: simulation (file) mode and error handling."""
from __future__ import annotations

import asyncio
import json

import pytest

from api_client import WaterMonitorClient, WaterMonitorError


class SimConfig:
    """Minimal AppConfig stand-in for the client (simulation mode)."""

    def __init__(self, simulation_file, simulation_mode=True):
        self.simulation_mode = simulation_mode
        self.simulation_file = str(simulation_file)
        self.api_url = "http://unused/"
        self.request_timeout_seconds = 5


def _fetch(config):
    """Run one fetch to completion, always closing the client."""
    async def run():
        client = WaterMonitorClient(config)
        try:
            return await client.fetch()
        finally:
            await client.aclose()

    return asyncio.run(run())


def test_fetch_from_simulation_file(tmp_path, sample_payload):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(sample_payload))
    payload = _fetch(SimConfig(path))
    assert payload.tank_by_name("External Tank Water Level").percent_full == 100


def test_editing_simulation_file_is_picked_up(tmp_path, sample_payload):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(sample_payload))

    async def run():
        client = WaterMonitorClient(SimConfig(path))
        try:
            first = await client.fetch()
            assert first.tank_by_name("External Tank Water Level").percent_full == 100
            sample_payload["tank_sensors"][0]["percent_full"] = 12
            path.write_text(json.dumps(sample_payload))
            second = await client.fetch()
            assert second.tank_by_name("External Tank Water Level").percent_full == 12
        finally:
            await client.aclose()

    asyncio.run(run())


def test_missing_simulation_file_raises(tmp_path):
    with pytest.raises(WaterMonitorError):
        _fetch(SimConfig(tmp_path / "nope.json"))


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json")
    with pytest.raises(WaterMonitorError):
        _fetch(SimConfig(path))
