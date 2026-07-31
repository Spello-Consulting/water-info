"""Async data source for the water-monitor payload.

Normally polls the live REST API over HTTP. When ``SimulationMode`` is enabled
in config, payloads are read from a local JSON file (``SimulationFile``) instead
— useful for testing card colours and low-water alerts without the hardware.
Editing the file between polls is picked up live.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from pydantic import ValidationError

from config import AppConfig
from models import WaterMonitorPayload


class WaterMonitorError(Exception):
    """Raised when the water-monitor data cannot be obtained or is invalid."""


class WaterMonitorClient:
    """Fetches and validates the water-monitor payload.

    Reads mode/URL/timeout/file from :class:`AppConfig` on each call so config
    hot-reloads (including toggling simulation mode) take effect immediately.
    """

    def __init__(self, app_config: AppConfig) -> None:
        self._cfg = app_config
        self._client = httpx.AsyncClient()

    async def fetch(self) -> WaterMonitorPayload:
        if self._cfg.simulation_mode:
            return await asyncio.to_thread(self._fetch_from_file, self._cfg.simulation_file)
        return await self._fetch_from_api()

    async def _fetch_from_api(self) -> WaterMonitorPayload:
        url = self._cfg.api_url
        timeout = self._cfg.request_timeout_seconds
        try:
            response = await self._client.get(url, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Discard the connection pool on any failure. During an outage the
            # pool can be left holding half-open/stale keep-alive connections;
            # reusing those makes every later attempt fail even once the API is
            # back, so a fresh client is created for the next poll. This is how
            # the app re-establishes the connection after the API has been down
            # for longer than RequestTimeoutSeconds.
            await self._reset_client()
            raise WaterMonitorError(f"Failed to fetch water-monitor API at {url}: {exc}") from exc
        return self._validate(data, f"API {url}")

    async def _reset_client(self) -> None:
        """Replace the HTTP client so the next request opens a fresh connection."""
        old, self._client = self._client, httpx.AsyncClient()
        try:
            await old.aclose()
        except Exception:  # noqa: BLE001 - best-effort cleanup of the dead client
            pass

    def _fetch_from_file(self, path: str) -> WaterMonitorPayload:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WaterMonitorError(f"Failed to read simulation file {path}: {exc}") from exc
        return self._validate(data, f"simulation file {path}")

    @staticmethod
    def _validate(data: object, source: str) -> WaterMonitorPayload:
        try:
            return WaterMonitorPayload.model_validate(data)
        except ValidationError as exc:
            raise WaterMonitorError(f"Invalid water-monitor payload from {source}: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()
