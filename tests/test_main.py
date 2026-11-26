"""Tests for the ``main`` entry point."""
from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import MagicMock

import main


def test_uvicorn_run_has_bounded_graceful_shutdown(monkeypatch: Any) -> None:
    """``main()`` must pass a bounded ``timeout_graceful_shutdown`` to uvicorn.

    Without it, an open ``/ws`` dashboard WebSocket keeps uvicorn waiting
    indefinitely on a single SIGTERM, so the process hangs on stop until it is
    SIGKILLed. This is a regression test for that deploy-time shutdown hang.
    """
    captured: dict[str, Any] = {}

    def _fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setattr(
        main,
        "parse_args",
        lambda: argparse.Namespace(config="config.yaml", homedir=None),
    )
    monkeypatch.setattr(main, "build_config_manager", lambda _cfg: MagicMock())
    monkeypatch.setattr(main, "build_logger", lambda _mgr: MagicMock())
    monkeypatch.setattr(main, "AppConfig", lambda _mgr: MagicMock(host="127.0.0.1", port=8000))
    monkeypatch.setattr(main, "create_app", lambda _cfg, _logger: MagicMock())
    monkeypatch.setattr(main.uvicorn, "run", _fake_run)

    main.main()

    kwargs = captured["kwargs"]
    assert "timeout_graceful_shutdown" in kwargs, (
        "uvicorn.run must be given a bounded graceful-shutdown timeout"
    )
    timeout = kwargs["timeout_graceful_shutdown"]
    assert timeout == main.WEB_SERVER_GRACEFUL_SHUTDOWN_TIMEOUT
    assert 0 < timeout <= 30
