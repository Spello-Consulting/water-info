"""WebSocket connection manager and state broadcast.

Keeps the last broadcast state so a newly-connected client is pushed the current
snapshot immediately, then receives live updates on every poll.
"""
from __future__ import annotations

import asyncio

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._diag_viewers: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._latest: dict | None = None
        # Set when a diagnostics viewer connects so the poller can wake from its
        # sleep and switch to the fast (2s) poll cadence immediately.
        self.wake_event = asyncio.Event()

    @property
    def diagnostics_active(self) -> bool:
        """True while at least one client is viewing the diagnostics page."""
        return bool(self._diag_viewers)

    def set_diagnostics(self, websocket: WebSocket, on: bool) -> None:
        """Mark/unmark ``websocket`` as a diagnostics viewer.

        On the 0->1 transition the poller is woken so fast-polling starts without
        waiting out the current (possibly long) sleep.
        """
        if on:
            was_empty = not self._diag_viewers
            self._diag_viewers.add(websocket)
            if was_empty:
                self.wake_event.set()
        else:
            self._diag_viewers.discard(websocket)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        if self._latest is not None:
            await websocket.send_json(self._latest)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        # A closed socket must not keep the poller pinned to the fast cadence.
        self._diag_viewers.discard(websocket)

    async def broadcast(self, state: dict) -> None:
        """Store and push ``state`` to all connected clients, dropping dead ones."""
        self._latest = state
        async with self._lock:
            connections = list(self._connections)
        dead: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(state)
            except Exception:  # noqa: BLE001 - a broken socket must not stop the broadcast
                dead.append(websocket)
        if dead:
            async with self._lock:
                for websocket in dead:
                    self._connections.discard(websocket)
