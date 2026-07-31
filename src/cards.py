"""Map water-monitor sensors to ordered card view models per config.

Matching is by sensor **name**. Sensors present in the payload but not in the
config are excluded; config entries with no matching sensor render a card with
null values. Status/colour rules follow design.md:

* Status text OK / Warning / Error -> black / orange / red, from the sensor's
  ``status`` field (or Error when the API is unreachable / sensor missing).
* Water percentage value text is orange below the warning threshold and red
  below the critical threshold.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

from config import CardConfig
from db import Database
from models import WaterMonitorPayload

# Status levels -> display label + CSS class (colour).
_STATUS_LABEL = {"ok": "OK", "warning": "Warning", "error": "Error"}


@dataclass
class CardView:
    """Everything a template (or WebSocket client) needs to render one card."""

    sensor: str
    type: str  # "water" | "temperature"
    display_name: str
    present: bool
    value: float | None
    value_int: str  # large-font portion ("96", "24", or "--")
    value_dec: str  # small-font portion (".1" for temperature, "" otherwise)
    unit: str  # "%" or "°C"
    value_class: str  # value-ok | value-warning | value-critical
    status: str  # ok | warning | error
    status_label: str  # OK | Warning | Error
    min_str: str
    max_str: str

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(value: float | None, card_type: str) -> tuple[str, str]:
    """Split a value into (large, small) display strings."""
    if value is None:
        return "--", ""
    if card_type == "water":
        return f"{round(value):d}", ""
    # temperature: one decimal place, decimal shown in a smaller font
    whole = int(value) if value >= 0 else -int(-value)
    dec = abs(value - whole)
    return f"{whole:d}", f".{round(dec * 10):d}"


def _minmax_str(lo: float | None, hi: float | None, unit: str, card_type: str) -> tuple[str, str]:
    def one(v: float | None) -> str:
        if v is None:
            return "--"
        return f"{round(v):d}{unit}" if card_type == "water" else f"{v:.1f}{unit}"

    return one(lo), one(hi)


def build_card(card: CardConfig, payload: WaterMonitorPayload | None, db: Database, api_ok: bool, now: dt.datetime) -> CardView:
    unit = "%" if card.is_water else "°C"

    sensor = None
    if payload is not None:
        sensor = payload.tank_by_name(card.sensor) if card.is_water else payload.probe_by_name(card.sensor)

    present = sensor is not None
    value = None
    raw_status = None
    if sensor is not None:
        value = sensor.percent_full if card.is_water else sensor.temperature_c
        raw_status = (sensor.status or "").lower()

    # Status: Error when API is down or the sensor is missing, else from payload.
    if not api_ok or not present:
        status = "error"
    elif raw_status in ("ok", "warning", "error"):
        status = raw_status
    else:
        status = "error"

    # Value colour (water cards only): orange below warning, red below critical.
    value_class = "value-ok"
    if card.is_water and value is not None:
        if card.critical_percent is not None and value < card.critical_percent:
            value_class = "value-critical"
        elif card.warning_percent is not None and value < card.warning_percent:
            value_class = "value-warning"

    if card.is_water:
        lo, hi = db.tank_minmax_24h(card.sensor, now)
    else:
        lo, hi = db.temp_minmax_24h(card.sensor, now)
    min_str, max_str = _minmax_str(lo, hi, unit, card.type)

    value_int, value_dec = _fmt(value, card.type)
    return CardView(
        sensor=card.sensor,
        type=card.type,
        display_name=card.display_name,
        present=present,
        value=value,
        value_int=value_int,
        value_dec=value_dec,
        unit=unit,
        value_class=value_class,
        status=status,
        status_label=_STATUS_LABEL[status],
        min_str=min_str,
        max_str=max_str,
    )


def build_cards(cards: list[CardConfig], payload: WaterMonitorPayload | None, db: Database, api_ok: bool, now: dt.datetime) -> list[CardView]:
    """Build the ordered list of card view models. Blocking (DB reads); call via to_thread."""
    return [build_card(card, payload, db, api_ok, now) for card in cards]
