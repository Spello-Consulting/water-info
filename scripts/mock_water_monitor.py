"""Local mock of the water-monitor REST API for development/verification.

Serves the design.md sample payload at ``/`` and lets you drive tank levels to
exercise card colours and alert hysteresis:

    GET /                      -> current payload (JSON)
    GET /set?external=15&internal=45  -> update tank percent_full, returns OK

Run:  uv run python scripts/mock_water_monitor.py [--port 9000]
"""
from __future__ import annotations

import argparse
import copy
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

BASE_PAYLOAD = {
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
        {"rom_registered": True, "status": "ok", "name": "Internal Tank Water Temperature",
         "connected": True, "age_seconds": 2, "temperature_c": 22.0, "gpio_pin": 19, "rom_id": "287df3cb00000089",
         "raw_hex": "60 01 4b 46 7f ff 0c 10 8a"},
        {"rom_registered": True, "status": "ok", "name": "Internal Air Temperature",
         "connected": True, "age_seconds": 2, "temperature_c": 27.1, "gpio_pin": 19, "rom_id": "2823112200000037",
         "raw_hex": "b2 01 4b 46 7f ff 0c 10 33"},
    ],
    "errors": [],
}

STATE = {"external": 100, "internal": 100}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/set":
            qs = parse_qs(parsed.query)
            for key in ("external", "internal"):
                if key in qs:
                    STATE[key] = float(qs[key][0])
            self._send(200, {"ok": True, "state": STATE})
            return
        payload = copy.deepcopy(BASE_PAYLOAD)
        payload["tank_sensors"][0]["percent_full"] = STATE["external"]
        payload["tank_sensors"][1]["percent_full"] = STATE["internal"]
        self._send(200, payload)

    def log_message(self, *args) -> None:  # silence per-request logging
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Mock water-monitor on http://127.0.0.1:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
