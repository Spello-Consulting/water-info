"""Data-source tests: simulation (file) mode and error handling."""
from __future__ import annotations

import asyncio
import json

import httpx
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


def test_api_failure_resets_connection_pool(monkeypatch):
    """A failed API fetch discards the HTTP client so the pool is rebuilt."""

    async def run():
        client = WaterMonitorClient(SimConfig("unused", simulation_mode=False))
        original = client._client

        async def boom(*args, **kwargs):
            raise httpx.ConnectError("API down for maintenance")

        monkeypatch.setattr(client._client, "get", boom)
        with pytest.raises(WaterMonitorError):
            await client.fetch()
        # The dead client was replaced, so the next poll opens a fresh connection.
        assert client._client is not original
        await client.aclose()

    asyncio.run(run())


def test_api_recovers_after_outage(monkeypatch, sample_payload):
    """After the API is down (longer than the timeout), the next poll reconnects.

    Regression test for issue #1: the app must re-establish the connection on
    its own once the API returns, without a manual restart.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("API down for maintenance")
        return httpx.Response(200, json=sample_payload)

    # Every AsyncClient (the initial one and the one built on reset) talks to
    # the mock transport, so we exercise the real reset-and-recover path.
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real_async_client(transport=httpx.MockTransport(handler))
    )

    async def run():
        client = WaterMonitorClient(SimConfig("unused", simulation_mode=False))
        with pytest.raises(WaterMonitorError):
            await client.fetch()  # outage -> pool reset
        payload = await client.fetch()  # API back -> fresh client succeeds
        assert payload.tank_by_name("External Tank Water Level").percent_full == 100
        await client.aclose()

    asyncio.run(run())
