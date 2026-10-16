"""HTTP + WebSocket routes."""
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.status import HTTP_404_NOT_FOUND

from sc_foundation import SCCommon
from sc_foundation.sc_date_helper import DateHelper

from cards import build_cards
from chart import render_chart_svg
from poller import build_diagnostics

if TYPE_CHECKING:
    from sc_foundation import SCLogger

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _logfile_path(logger: SCLogger) -> str | None:
    """Return the log file path, or None when file logging is disabled.

    Returns:
        The log file path, or None.
    """
    if not logger.file_logging_enabled:
        return None
    path: str | None = logger.get_logfile_path()
    return path


def _deployment_rows(info: dict[str, Any]) -> dict[str, str]:
    """Build the version and git rows for the system page.

    The git remote is deliberately omitted: an HTTPS remote URL can embed a token.

    Args:
        info: The dictionary returned by ``SCCommon.get_deployment_info()``.

    Returns:
        Display rows keyed by label. Git rows are omitted when the app is not
        running from a git checkout.
    """
    rows = {"Application version": str(info.get("version") or "—")}
    if info.get("git_changes") is None:
        return rows
    rows["Git branch"] = str(info.get("git_branch") or "(detached HEAD)")
    rows["Git status"] = str(info.get("git_status") or "Unknown")
    rows["Uncommitted changes"] = str(info["git_changes"])
    return rows


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
    # Runs several git subprocesses; keep them off the event loop.
    deployment_info = await asyncio.to_thread(SCCommon.get_deployment_info)
    last_valid = DateHelper.format(app.state.app_state.last_valid_response) if app.state.app_state.last_valid_response else None
    return _templates(request).TemplateResponse(
        request,
        "system.html",
        {
            "deployment_rows": _deployment_rows(deployment_info),
            "device": device,
            "api_ok": app.state.app_state.api_ok,
            "last_valid_response": last_valid,
            "simulation_mode": app.state.config.simulation_mode,
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


@router.get("/config", response_class=HTMLResponse)
async def config(request: Request):
    """Show the contents of the active YAML config file.

    Secrets live in ``.env`` (never in the YAML), so dumping the config is safe.
    """
    app = request.app
    cfg = app.state.config
    path = cfg.config_path
    try:
        config_text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except OSError as exc:
        config_text = f"Could not read config file: {exc}"
    return _templates(request).TemplateResponse(
        request,
        "config.html",
        {
            "config_text": config_text,
            "config_path": str(path),
        },
    )


@router.get("/log", response_class=HTMLResponse)
async def show_log(request: Request) -> Response:
    """Render the log viewer page with the current log file contents.

    The page polls ``/log/content`` for new lines while its *Live updates*
    checkbox is ticked.

    Returns:
        The rendered log page.
    """
    logger = request.app.state.logger
    chunk = await asyncio.to_thread(logger.read_logfile_since)
    response: Response = _templates(request).TemplateResponse(
        request,
        "log.html",
        {"log_path": _logfile_path(logger) or "", "log_chunk": chunk},
    )
    return response


@router.get("/log/content")
async def log_content(request: Request, generation: int | None = None, offset: int = 0) -> Response:
    """Return log file content written since a previous read.

    Pass back the ``generation`` and ``offset`` from the previous response. When
    ``reset`` is true the client should replace its content with ``text``
    rather than append it (the log file was trimmed or replaced).

    Returns:
        A JSON ``LogChunk`` (text, generation, offset, reset).
    """
    chunk = await asyncio.to_thread(request.app.state.logger.read_logfile_since, generation, offset)
    return JSONResponse(asdict(chunk), headers={"Cache-Control": "no-store"})


@router.get("/log/download")
async def log_download(request: Request) -> Response:
    """Download a copy of the log file (404 when file logging is disabled).

    The content is a snapshot read under the logger's lock, so it is never
    caught mid-trim.

    Returns:
        The log file as an attachment, or a 404 response.
    """
    logger = request.app.state.logger
    log_path = _logfile_path(logger)
    if not log_path:
        return HTMLResponse("File logging is not enabled.", status_code=HTTP_404_NOT_FOUND)

    text = await asyncio.to_thread(logger.read_logfile)
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{Path(log_path).name}"'},
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
