"""Shared in-memory runtime state, updated by the poller and read by routes."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from models import WaterMonitorPayload


@dataclass
class AppState:
    """Latest known state of the water-monitor, kept between polls.

    On an API outage the last good ``payload`` is retained and ``api_ok`` is set
    False so cards render as Error while still showing the last values.
    """

    payload: WaterMonitorPayload | None = None
    api_ok: bool = False
    last_valid_response: dt.datetime | None = None
