"""Shared test fixtures."""
from __future__ import annotations

import copy

import pytest

# The design.md sample payload, reused across tests.
SAMPLE_PAYLOAD = {
    "device": {
        "firmware_version": "1.28.0", "app_version": "0.1.0", "api_request_count": 1,
        "uptime_seconds": 29, "name": "water-monitor", "reset_cause": "HARD_RESET",
        "free_heap_bytes": 98256, "status": "ok", "wifi_rssi_dbm": -83, "boot_count": 13,
    },
    "tank_sensors": [
        {"distance_mm": 134, "volume_litres": 1994, "connected": True, "gpio_tx_pin": 4,
         "level_mm": 1596, "percent_full": 100, "age_seconds": 5, "raw_hex": "ff 00 86 85",
         "name": "External Tank Water Level", "status": "ok", "gpio_rx_pin": 16, "consecutive_failures": 0},
        {"distance_mm": 150, "volume_litres": 400, "connected": True, "gpio_tx_pin": 23,
         "level_mm": 800, "percent_full": 100, "age_seconds": 4, "raw_hex": "ff 00 96 95",
         "name": "Internal Tank Water Level", "status": "ok", "gpio_rx_pin": 17, "consecutive_failures": 0},
    ],
    "temperature_probes": [
        {"rom_registered": True, "status": "ok", "name": "External Tank Water Temperature",
         "connected": True, "age_seconds": 3, "temperature_c": 23.5, "gpio_pin": 18, "rom_id": "28977122000000fd",
         "raw_hex": "78 01 4b 46 7f ff 0c 10 1c"},
        {"rom_registered": True, "status": "ok", "name": "External Air Temperature",
         "connected": True, "age_seconds": 3, "temperature_c": 30.6, "gpio_pin": 18, "rom_id": "280fd7ca00000017",
         "raw_hex": "a6 01 4b 46 7f ff 0c 10 5f"},
    ],
    "errors": [],
}


@pytest.fixture
def sample_payload() -> dict:
    return copy.deepcopy(SAMPLE_PAYLOAD)
