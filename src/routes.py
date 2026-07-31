"""HTTP + WebSocket routes."""
from __future__ import annotations

import asyncio
import datetime as dt

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from starlette.status import HTTP_404_NOT_FOUND

from sc_foundation.sc_date_helper import DateHelper

from cards import build_cards
from chart import render_chart_svg
from poller import build_diagnostics

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _current_reading(card, payload, unit: str) -> str | None:
    """Formatted latest reading for the chart title, e.g. ``26.9°C`` (or None)."""
    if payload is None:
        return None
    sensor_obj = payload.tank_by_name(card.sensor) if card.is_water else payload.probe_by_name(card.sensor)
    if sensor_obj is None:
        return None
    value = sensor_obj.percent_full if card.is_water else sensor_obj.temperature_c
    if value is None:
        return None
    return f"{round(value):d}{unit}" if card.is_water else f"{value:.1f}{unit}"


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    app = request.app
    cfg = app.state.config
    now = DateHelper.now()
    cards = await asyncio.to_thread(build_cards, cfg.cards(), app.state.app_state.payload, app.state.db, app.state.app_state.api_ok, now)
    last_valid = DateHelper.format(app.state.app_state.last_valid_response) if app.state.app_state.last_valid_response else None
    return _templates(request).TemplateResponse(
        request,
        "home.html",
        {
            "cards": cards,
            "api_ok": app.state.app_state.api_ok,
            "last_valid_response": last_valid,
        },
    )


@router.get("/chart/{sensor}", response_class=HTMLResponse)
async def chart(request: Request, sensor: str):
    app = request.app
    cfg = app.state.config
    cards = cfg.cards()
    index = next((i for i, c in enumerate(cards) if c.sensor == sensor), None)
    if index is None:
        return HTMLResponse("Unknown sensor", status_code=HTTP_404_NOT_FOUND)

    card = cards[index]
    days = cfg.chart_days
    now = DateHelper.now()
    since = now - dt.timedelta(days=days)

    if card.is_water:
        points = await asyncio.to_thread(app.state.db.tank_series, card.sensor, since)
    else:
        points = await asyncio.to_thread(app.state.db.temp_series, card.sensor, since)
    lo, hi = await asyncio.to_thread(app.state.db.period_minmax, card.type, card.sensor, since)

    unit = "%" if card.is_water else "°C"
    svg = render_chart_svg(points, lo, hi, unit, card.type, days)

    # Current reading shown in the chart title (e.g. "External Air Temp — 26.9°C").
    current_reading = _current_reading(card, app.state.app_state.payload, unit)

    next_card = cards[(index + 1) % len(cards)]
    return _templates(request).TemplateResponse(
        request,
        "chart.html",
        {
            "card": card,
            "svg": svg,
            "days": days,
            "current_reading": current_reading,
            "next_sensor": next_card.sensor,
            "next_name": next_card.display_name,
            "has_data": bool(points),
        },
    )


@router.get("/system", response_class=HTMLResponse)
async def system(request: Request):
    app = request.app
    device = await asyncio.to_thread(app.state.db.latest_device)
    last_valid = DateHelper.format(app.state.app_state.last_valid_response) if app.state.app_state.last_valid_response else None
    return _templates(request).TemplateResponse(
        request,
        "system.html",
        {
            "device": device,
            "api_ok": app.state.app_state.api_ok,
            "last_valid_response": last_valid,
        },
    )


@router.get("/diagnostics/{sensor}", response_class=HTMLResponse)
async def diagnostics(request: Request, sensor: str):
    app = request.app
    cfg = app.state.config
    card = next((c for c in cfg.cards() if c.sensor == sensor), None)
    if card is None:
        return HTMLResponse("Unknown sensor", status_code=HTTP_404_NOT_FOUND)

    sensors = await asyncio.to_thread(build_diagnostics, cfg, app.state.app_state.payload, sensor)
    last_valid = DateHelper.format(app.state.app_state.last_valid_response) if app.state.app_state.last_valid_response else None
    return _templates(request).TemplateResponse(
        request,
        "diagnostics.html",
        {
            "sensors": sensors,
            "sensor": sensor,
            "display_name": card.display_name,
            "api_ok": app.state.app_state.api_ok,
            "last_valid_response": last_valid,
        },
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    app = websocket.app
    ws_manager = app.state.ws_manager
    await ws_manager.connect(websocket)
    try:
        while True:
            # The only client message expected is the "diagnostics" signal sent
            # by the diagnostics page; receiving also lets us detect disconnects.
            message = await websocket.receive_text()
            if message == "diagnostics":
                ws_manager.set_diagnostics(websocket, True)
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:  # noqa: BLE001
        await ws_manager.disconnect(websocket)
