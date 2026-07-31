"""Pydantic models for the water-monitor REST API payload.

Models are intentionally lenient (``extra="ignore"``) so that firmware changes
that add fields don't break parsing. Only the fields this app consumes are
declared with types.
"""
from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, field_validator


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("*", mode="before")
    @classmethod
    def _non_finite_to_none(cls, value):
        """Treat a non-finite reading (NaN/Infinity) as no reading.

        A faulty probe can report these; left as floats they crash card
        formatting (``int(NaN)``) and serialise to invalid JSON (bare ``NaN``),
        which would freeze every live update. Coercing to None makes them render
        as "no value" throughout (cards, DB, diagnostics).
        """
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value


class DeviceInfo(_Lenient):
    firmware_version: str | None = None
    app_version: str | None = None
    api_request_count: int | None = None
    uptime_seconds: int | None = None
    name: str | None = None
    reset_cause: str | None = None
    free_heap_bytes: int | None = None
    status: str | None = None
    wifi_rssi_dbm: int | None = None
    boot_count: int | None = None


class TankSensor(_Lenient):
    name: str
    status: str | None = None
    connected: bool | None = None
    percent_full: float | None = None
    level_mm: float | None = None
    volume_litres: float | None = None
    distance_mm: float | None = None
    raw_hex: str | None = None  # last raw sensor frame (hex), for diagnostics
    age_seconds: int | None = None
    consecutive_failures: int | None = None


class TemperatureProbe(_Lenient):
    name: str
    status: str | None = None
    connected: bool | None = None
    temperature_c: float | None = None
    raw_hex: str | None = None  # last raw DS18B20 scratchpad (hex), for diagnostics
    rom_id: str | None = None
    rom_registered: bool | None = None
    age_seconds: int | None = None


class WaterMonitorPayload(_Lenient):
    device: DeviceInfo
    tank_sensors: list[TankSensor] = []
    temperature_probes: list[TemperatureProbe] = []
    errors: list = []

    def tank_by_name(self, name: str) -> TankSensor | None:
        for sensor in self.tank_sensors:
            if sensor.name == name:
                return sensor
        return None

    def probe_by_name(self, name: str) -> TemperatureProbe | None:
        for probe in self.temperature_probes:
            if probe.name == name:
                return probe
        return None
