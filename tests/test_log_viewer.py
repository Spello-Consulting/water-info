"""Tests for the log viewer and extended system information (issue #9)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from sc_foundation import SCCommon, SCLogger

import app as app_module
from routes import router
from state import AppState

_SRC_DIR = Path(app_module.__file__).resolve().parent

_DEPLOYMENT_INFO = {
    "name": "water-info",
    "version": "9.8.7",
    "description": "Test",
    "git_branch": "feature/test-branch",
    "git_tag": None,
    "git_remote": "https://secret-token@github.com/example/repo.git",
    "git_status": "Ahead",
    "git_changes": 3,
}


class _FakeDb:
    @staticmethod
    def latest_device():
        return None


def _make_logger(logfile: Path | None, max_lines: int = 1000) -> SCLogger:
    return SCLogger({
        "logfile_name": str(logfile) if logfile else None,
        "file_verbosity": "debug",
        "console_verbosity": "none",
        "max_lines": max_lines,
    })


def _make_client(logger: SCLogger) -> TestClient:
    """Build the routes on a bare app (no lifespan, so no poller or DB).

    Returns:
        A test client for the app.
    """
    app = FastAPI()
    app.mount("/static", app_module.NoCacheStaticFiles(directory=_SRC_DIR / "static"), name="static")
    app.state.templates = Jinja2Templates(directory=_SRC_DIR / "templates")
    app.state.logger = logger
    app.state.db = _FakeDb()
    app.state.app_state = AppState()
    app.state.config = SimpleNamespace(simulation_mode=False)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def logger(tmp_path):
    log = _make_logger(tmp_path / "logs" / "app.log", max_lines=5)
    log.log_message("first log line", "summary")
    log.log_message("a <b>tagged</b> warning", "warning")
    return log


@pytest.fixture
def client(logger):
    return _make_client(logger)


# ---- System page ----


def test_system_page_shows_version_and_git(client, monkeypatch):
    """The system page shows the app version and git branch/status/changes."""
    monkeypatch.setattr(SCCommon, "get_deployment_info", lambda: dict(_DEPLOYMENT_INFO))
    body = client.get("/system").text

    assert "Application version" in body
    assert "9.8.7" in body
    assert "feature/test-branch" in body
    assert "Ahead" in body
    assert "Uncommitted changes" in body
    # The remote URL can embed credentials, so it must never be shown.
    assert "secret-token" not in body
    assert 'href="/log"' in body


def test_system_page_without_git(client, monkeypatch):
    """Git rows are omitted when the app isn't running from a git checkout."""
    info = dict(_DEPLOYMENT_INFO, git_branch=None, git_status="Unknown", git_changes=None)
    monkeypatch.setattr(SCCommon, "get_deployment_info", lambda: info)
    body = client.get("/system").text

    assert "9.8.7" in body
    assert "Git branch" not in body
    assert "Uncommitted changes" not in body


# ---- Log viewer ----


def test_log_page_shows_contents(client, logger):
    """The log page renders the log file contents, HTML-escaped."""
    response = client.get("/log")

    assert response.status_code == 200
    body = response.text
    assert "first log line" in body
    assert "&lt;b&gt;tagged&lt;/b&gt;" in body
    assert logger.get_logfile_path() in body
    assert 'id="log-live"' in body
    assert 'href="/log/download"' in body
    assert "/static/log.js" in body


def test_log_content_incremental(client, logger):
    """/log/content returns only new lines when given the previous position."""
    first = client.get("/log/content").json()
    assert first["reset"] is True
    assert "first log line" in first["text"]

    logger.log_message("a newer line", "summary")
    second = client.get(
        "/log/content",
        params={"generation": first["generation"], "offset": first["offset"]},
    ).json()

    assert second["reset"] is False
    assert "a newer line" in second["text"]
    assert "first log line" not in second["text"]


def test_log_content_resets_after_trim(client, logger):
    """After the log is trimmed the client is told to replace its content."""
    first = client.get("/log/content").json()

    for i in range(10):
        logger.log_message(f"filler {i}", "summary")
    logger.trim_logfile()

    second = client.get(
        "/log/content",
        params={"generation": first["generation"], "offset": first["offset"]},
    ).json()

    assert second["reset"] is True
    assert second["text"] == logger.read_logfile()


def test_log_download(client, logger):
    """/log/download returns the log file as an attachment."""
    response = client.get("/log/download")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="app.log"'
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == logger.read_logfile()


def test_log_pages_when_file_logging_disabled():
    """With file logging off the page explains why and download is a 404."""
    test_client = _make_client(_make_logger(None))

    page = test_client.get("/log")
    assert page.status_code == 200
    assert "File logging is not enabled" in page.text
    assert "/static/log.js" not in page.text
    assert test_client.get("/log/download").status_code == 404
    assert not test_client.get("/log/content").json()["text"]
