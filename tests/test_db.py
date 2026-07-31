"""SQLite storage tests."""
from __future__ import annotations

import datetime as dt

import pytest

from db import Database
from models import WaterMonitorPayload


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.sqlite"))
    yield database
    database.close()


def _payload(sample_payload, external_pct):
    sample_payload["tank_sensors"][0]["percent_full"] = external_pct
    return WaterMonitorPayload.model_validate(sample_payload)


def test_persist_and_minmax(db, sample_payload):
    now = dt.datetime(2026, 7, 28, 12, 0, tzinfo=dt.timezone.utc)
    for hours, pct in [(0, 60), (1, 90), (2, 30)]:
        db.persist_payload(_payload(sample_payload, pct), now - dt.timedelta(hours=hours))
    lo, hi = db.tank_minmax_24h("External Tank Water Level", now)
    assert (lo, hi) == (30, 90)
    # temperature min/max from the (constant) sample probe
    tlo, thi = db.temp_minmax_24h("External Air Temperature", now)
    assert tlo == thi == 30.6


def test_minmax_excludes_old_readings(db, sample_payload):
    now = dt.datetime(2026, 7, 28, 12, 0, tzinfo=dt.timezone.utc)
    db.persist_payload(_payload(sample_payload, 10), now - dt.timedelta(hours=48))  # too old
    db.persist_payload(_payload(sample_payload, 80), now - dt.timedelta(hours=1))
    lo, hi = db.tank_minmax_24h("External Tank Water Level", now)
    assert (lo, hi) == (80, 80)


def test_series_and_period_minmax(db, sample_payload):
    now = dt.datetime(2026, 7, 28, 12, 0, tzinfo=dt.timezone.utc)
    for days, pct in [(10, 50), (5, 70), (1, 20)]:
        db.persist_payload(_payload(sample_payload, pct), now - dt.timedelta(days=days))
    since = now - dt.timedelta(days=30)
    series = db.tank_series("External Tank Water Level", since)
    assert series and all(isinstance(v, float) for _, v in series)
    lo, hi = db.period_minmax("water", "External Tank Water Level", since)
    assert (lo, hi) == (20, 70)


def test_prune(db, sample_payload):
    now = dt.datetime(2026, 7, 28, 12, 0, tzinfo=dt.timezone.utc)
    db.persist_payload(_payload(sample_payload, 50), now - dt.timedelta(days=100))
    db.persist_payload(_payload(sample_payload, 60), now - dt.timedelta(days=10))
    removed = db.prune(90, now)
    # the 100-day-old payload contributed 2 tank + 2 temp readings, all pruned
    assert removed == 4
    # only the recent readings remain
    lo, hi = db.tank_minmax_24h("External Tank Water Level", now - dt.timedelta(days=10) + dt.timedelta(hours=1))
    assert hi == 60


def test_latest_device_upsert(db, sample_payload):
    now = dt.datetime(2026, 7, 28, 12, 0, tzinfo=dt.timezone.utc)
    db.persist_payload(_payload(sample_payload, 50), now)
    sample_payload["device"]["boot_count"] = 99
    db.persist_payload(_payload(sample_payload, 50), now + dt.timedelta(minutes=1))
    device = db.latest_device()
    assert device["boot_count"] == 99  # single latest row
