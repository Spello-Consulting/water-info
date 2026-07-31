"""SQLite persistence for water-display.

Single-file SQLite database holding timestamped tank + temperature readings and
a single latest-device row. SQLite ships with Python (no native wheels to
compile), so this runs on any architecture — including 32-bit ARM userlands on
the Raspberry Pi, where DuckDB has no wheel and won't build.

Timestamps are stored as UTC epoch seconds (REAL). All methods are synchronous
and blocking; callers wrap them in ``asyncio.to_thread`` so the event loop is
never stalled. A single connection is shared across threads
(``check_same_thread=False``) and every operation is serialised by a lock; the
poller is the only writer (see design.md).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from pathlib import Path

from models import WaterMonitorPayload

# Device columns persisted in the single-row device_latest table (order matters).
_DEVICE_FIELDS = [
    "firmware_version",
    "app_version",
    "api_request_count",
    "uptime_seconds",
    "name",
    "reset_cause",
    "free_heap_bytes",
    "status",
    "wifi_rssi_dbm",
    "boot_count",
]
_DEVICE_TEXT = {"firmware_version", "app_version", "name", "reset_cause", "status"}


class Database:
    """Thin synchronous wrapper around a single SQLite connection."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        path = Path(db_path)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Shared across worker threads; every access is serialised by _lock.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        device_cols = ",\n".join(
            f"{name} {'TEXT' if name in _DEVICE_TEXT else 'INTEGER'}" for name in _DEVICE_FIELDS
        )
        with self._lock:
            self._conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS tank_readings (
                    ts REAL NOT NULL,
                    sensor_name TEXT NOT NULL,
                    percent_full REAL,
                    level_mm REAL,
                    volume_litres REAL,
                    status TEXT
                );
                CREATE TABLE IF NOT EXISTS temp_readings (
                    ts REAL NOT NULL,
                    sensor_name TEXT NOT NULL,
                    temperature_c REAL,
                    status TEXT
                );
                CREATE TABLE IF NOT EXISTS device_latest (
                    ts REAL NOT NULL,
                    {device_cols}
                );
                CREATE INDEX IF NOT EXISTS idx_tank ON tank_readings (sensor_name, ts);
                CREATE INDEX IF NOT EXISTS idx_temp ON temp_readings (sensor_name, ts);
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- Writes ------------------------------------------------------------
    def persist_payload(self, payload: WaterMonitorPayload, ts: dt.datetime) -> None:
        """Insert all tank + temperature readings and upsert the device row."""
        epoch = ts.timestamp()
        with self._lock:
            for tank in payload.tank_sensors:
                self._conn.execute(
                    "INSERT INTO tank_readings VALUES (?, ?, ?, ?, ?, ?)",
                    (epoch, tank.name, tank.percent_full, tank.level_mm, tank.volume_litres, tank.status),
                )
            for probe in payload.temperature_probes:
                self._conn.execute(
                    "INSERT INTO temp_readings VALUES (?, ?, ?, ?)",
                    (epoch, probe.name, probe.temperature_c, probe.status),
                )
            values = [epoch, *(getattr(payload.device, name) for name in _DEVICE_FIELDS)]
            placeholders = ", ".join(["?"] * len(values))
            self._conn.execute("DELETE FROM device_latest")
            self._conn.execute(f"INSERT INTO device_latest VALUES ({placeholders})", values)
            self._conn.commit()

    def prune(self, older_than_days: int, now: dt.datetime) -> int:
        """Delete readings older than ``older_than_days``. Returns rows removed."""
        cutoff = (now - dt.timedelta(days=older_than_days)).timestamp()
        with self._lock:
            removed = 0
            for table in ("tank_readings", "temp_readings"):
                cur = self._conn.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
                removed += cur.rowcount
            self._conn.commit()
            return removed

    # --- Reads -------------------------------------------------------------
    def tank_minmax_24h(self, sensor_name: str, now: dt.datetime) -> tuple[float | None, float | None]:
        return self._minmax("tank_readings", "percent_full", sensor_name, now - dt.timedelta(hours=24))

    def temp_minmax_24h(self, sensor_name: str, now: dt.datetime) -> tuple[float | None, float | None]:
        return self._minmax("temp_readings", "temperature_c", sensor_name, now - dt.timedelta(hours=24))

    def _minmax(self, table: str, value_col: str, sensor_name: str, since: dt.datetime) -> tuple[float | None, float | None]:
        with self._lock:
            row = self._conn.execute(
                f"SELECT MIN({value_col}), MAX({value_col}) FROM {table} WHERE sensor_name = ? AND ts >= ?",
                (sensor_name, since.timestamp()),
            ).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def tank_series(self, sensor_name: str, since: dt.datetime, buckets: int = 500) -> list[tuple[dt.datetime, float]]:
        return self._series("tank_readings", "percent_full", sensor_name, since, buckets)

    def temp_series(self, sensor_name: str, since: dt.datetime, buckets: int = 500) -> list[tuple[dt.datetime, float]]:
        return self._series("temp_readings", "temperature_c", sensor_name, since, buckets)

    def _series(self, table: str, value_col: str, sensor_name: str, since: dt.datetime, buckets: int) -> list[tuple[dt.datetime, float]]:
        """Downsample readings since ``since`` into at most ``buckets`` averaged points."""
        cutoff = since.timestamp()
        with self._lock:
            row = self._conn.execute(
                f"SELECT MIN(ts), MAX(ts) FROM {table} WHERE sensor_name = ? AND ts >= ?",
                (sensor_name, cutoff),
            ).fetchone()
            if not row or row[0] is None:
                return []
            span_seconds = max(row[1] - row[0], 1.0)
            bucket_seconds = max(span_seconds / max(buckets, 1), 1.0)
            result = self._conn.execute(
                f"""
                SELECT CAST(ts / ? AS INTEGER) AS bucket, AVG({value_col})
                FROM {table}
                WHERE sensor_name = ? AND ts >= ? AND {value_col} IS NOT NULL
                GROUP BY bucket
                ORDER BY bucket
                """,
                (bucket_seconds, sensor_name, cutoff),
            ).fetchall()
        return [(dt.datetime.fromtimestamp(bucket * bucket_seconds), value) for bucket, value in result]

    def period_minmax(self, card_type: str, sensor_name: str, since: dt.datetime) -> tuple[float | None, float | None]:
        """Min/max of the raw readings over the charting period (for reference lines)."""
        table, col = ("tank_readings", "percent_full") if card_type == "water" else ("temp_readings", "temperature_c")
        return self._minmax(table, col, sensor_name, since)

    def latest_device(self) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT ts, {', '.join(_DEVICE_FIELDS)} FROM device_latest LIMIT 1"
            ).fetchone()
        if not row:
            return None
        device = dict(zip(["ts", *_DEVICE_FIELDS], row))
        device["ts"] = dt.datetime.fromtimestamp(device["ts"])
        return device
