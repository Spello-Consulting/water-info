"""The polling loop: fetch -> persist -> evaluate alerts -> broadcast.

Runs as a single asyncio task started in the FastAPI lifespan. On a fetch
failure the last good values are retained and every card is marked Error. A
retention prune runs once per day, and config changes are picked up each cycle.
"""
from __future__ import annotations

import asyncio
import datetime as dt

from sc_foundation.sc_date_helper import DateHelper

from alerts import AlertManager
from api_client import WaterMonitorClient, WaterMonitorError
from cards import build_cards
from config import AppConfig
from db import Database
from state import AppState
from websocket import WebSocketManager

# Poll cadence used while the diagnostics page is open, overriding the configured
# WaterMonitor.PollIntervalSeconds so the page is near-real-time.
DIAGNOSTICS_POLL_SECONDS = 2


def build_diagnostics(app_config: AppConfig, payload, sensor: str | None = None) -> list[dict]:
    """Build the per-sensor raw-field rows shown on the diagnostics page.

    One entry per sensor in the latest payload, carrying its configured friendly
    name/type and the modeled fields (``name`` excluded — it is the key). When
    ``sensor`` is given, only that sensor's row is returned.
    """
    if payload is None:
        return []
    by_name = {card.sensor: card for card in app_config.cards()}
    rows: list[dict] = []
    for s in [*payload.tank_sensors, *payload.temperature_probes]:
        if sensor is not None and s.name != sensor:
            continue
        card = by_name.get(s.name)
        rows.append(
            {
                "sensor": s.name,
                "display_name": card.display_name if card else s.name,
                "type": card.type if card else "unknown",
                # Non-finite readings are already coerced to None by the model.
                "fields": s.model_dump(exclude={"name"}),
            }
        )
    return rows


def build_state(app_config: AppConfig, app_state: AppState, db: Database, now: dt.datetime, ws_manager: WebSocketManager) -> dict:
    """Build the JSON-serialisable snapshot broadcast to WebSocket clients."""
    cards = build_cards(app_config.cards(), app_state.payload, db, app_state.api_ok, now)
    last_valid = None
    if app_state.last_valid_response is not None:
        last_valid = DateHelper.format(app_state.last_valid_response)
    state = {
        "cards": [card.to_dict() for card in cards],
        "api_ok": app_state.api_ok,
        "last_valid_response": last_valid,
    }
    # Only carry the (larger) diagnostics payload when someone is viewing it.
    if ws_manager.diagnostics_active:
        state["diagnostics"] = build_diagnostics(app_config, app_state.payload)
    return state


async def poller_loop(
    app_config: AppConfig,
    app_state: AppState,
    client: WaterMonitorClient,
    db: Database,
    ws_manager: WebSocketManager,
    alert_manager: AlertManager,
    logger,
) -> None:
    last_prune_date: dt.date | None = None
    last_config_check = DateHelper.now()

    while True:
        # --- Fetch + persist ------------------------------------------------
        try:
            payload = await client.fetch()
            now = DateHelper.now()
            app_state.payload = payload
            app_state.api_ok = True
            app_state.last_valid_response = now
            await asyncio.to_thread(db.persist_payload, payload, now)
            await asyncio.to_thread(alert_manager.evaluate, payload, True)
        except WaterMonitorError as exc:
            app_state.api_ok = False  # keep last payload; cards will show Error
            logger.log_message(f"Water-monitor poll failed: {exc}", "error")

        # --- Broadcast current state ---------------------------------------
        now = DateHelper.now()
        try:
            state = await asyncio.to_thread(build_state, app_config, app_state, db, now, ws_manager)
            await ws_manager.broadcast({"type": "state_update", "state": state})
        except Exception as exc:  # noqa: BLE001 - broadcast must never kill the loop
            logger.log_message(f"Failed to build/broadcast state: {exc}", "error")

        # --- Daily retention prune -----------------------------------------
        today = now.date()
        if last_prune_date != today:
            try:
                removed = await asyncio.to_thread(db.prune, app_config.retention_days, now)
                logger.log_message(f"Retention prune removed {removed} old readings.", "summary")
            except Exception as exc:  # noqa: BLE001
                logger.log_message(f"Retention prune failed: {exc}", "error")
            last_prune_date = today

        # --- Config hot-reload ---------------------------------------------
        new_check = app_config.config_mgr.check_for_config_changes(last_config_check)
        if new_check is not None:
            last_config_check = new_check
            logger.log_message(
                "Config file changed and reloaded. Live settings applied; "
                "changes to database path or server host/port require a restart.",
                "summary",
            )

        # --- Pace the loop -------------------------------------------------
        # Fast cadence while diagnostics is open; the wake_event lets a viewer
        # that connects mid-sleep trigger an immediate poll.
        interval = DIAGNOSTICS_POLL_SECONDS if ws_manager.diagnostics_active else app_config.poll_interval_seconds
        try:
            await asyncio.wait_for(ws_manager.wake_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        ws_manager.wake_event.clear()
