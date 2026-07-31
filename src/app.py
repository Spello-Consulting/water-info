"""FastAPI application factory and lifespan wiring.

The lifespan opens the single SQLite connection, creates the shared runtime
objects (HTTP client, WebSocket manager, alert manager, app state), and starts
the background poller task. Everything is stored on ``app.state`` for routes.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from alerts import AlertManager
from api_client import WaterMonitorClient
from config import AppConfig
from db import Database
from poller import poller_loop
from state import AppState
from websocket import WebSocketManager

_SRC_DIR = Path(__file__).resolve().parent


class NoCacheStaticFiles(StaticFiles):
    """Serve static files with ``Cache-Control: no-cache``.

    Forces browsers to revalidate ``app.js`` / ``style.css`` on each load so an
    already-open page or kiosk picks up a new deploy without a manual hard
    refresh. The server still answers unchanged files with a 304 (via the
    ETag/Last-Modified StaticFiles already sends), so this is cheap.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(app_config: AppConfig, logger) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(app_config.db_path)
        client = WaterMonitorClient(app_config)
        ws_manager = WebSocketManager()
        alert_manager = AlertManager(app_config, logger)
        app_state = AppState()

        app.state.config = app_config
        app.state.logger = logger
        app.state.db = db
        app.state.client = client
        app.state.ws_manager = ws_manager
        app.state.app_state = app_state

        source = f"simulation file {app_config.simulation_file}" if app_config.simulation_mode else app_config.api_url
        logger.log_message(f"Starting poller against {source} every {app_config.poll_interval_seconds}s.", "summary")
        poller_task = asyncio.create_task(
            poller_loop(app_config, app_state, client, db, ws_manager, alert_manager, logger)
        )
        try:
            yield
        finally:
            poller_task.cancel()
            try:
                await poller_task
            except asyncio.CancelledError:
                pass
            await client.aclose()
            db.close()
            logger.log_message("Water-display shut down cleanly.", "summary")

    app = FastAPI(title="Water Information Display", lifespan=lifespan)
    app.mount("/static", NoCacheStaticFiles(directory=_SRC_DIR / "static"), name="static")
    app.state.templates = Jinja2Templates(directory=_SRC_DIR / "templates")

    from routes import router  # imported here to avoid circular import at module load

    app.include_router(router)
    return app
