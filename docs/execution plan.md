# Water Information Display — Build Plan

## Context

`water-info` is a FastAPI/uvicorn web app that consumes the existing
water-monitor REST API, shows tank percentage-full and temperature as a
responsive card grid, serves historic charts and a system page, persists
readings to DuckDB, and sends email/SMS alerts when a tank runs low. The
repo is template scaffolding only (`src/main.py` is a stub). Design is in
[docs/design.md](docs/design.md); the detailed how is in
[docs/implementation-plan.md](docs/implementation-plan.md) — this file is
that plan plus the decisions just confirmed. Goal of this effort: implement
the full app per those two docs, verified end-to-end against a live
water-monitor endpoint.

## Decisions confirmed (this session)

- **Charts:** server-rendered SVG in Jinja — zero JS chart dependency, fully
  offline. Static high/low reference lines; home + next-sensor buttons.
- **SMS:** build `send_sms()` and wire it into alerts fully now, reading
  Twilio SID/token/from-number from env. If creds are absent at runtime, log
  a warning and skip SMS (email still fires). Twilio creds get added to
  `.env` later.
- **Test data:** live water-monitor endpoint is **`http://192.168.86.144/`**
  (confirmed reachable, HTTP 200, JSON served at root — no `/api` prefix;
  live payload matches the design schema exactly). Use it as the default
  `water-monitor URL` in `config.yaml` and for end-to-end checks; also build
  local mock/fixtures from the sample payload for tests and offline dev.
- **DuckDB concurrency** (already resolved in the plan): one uvicorn worker;
  single writer = the poller task; one connection opened in `lifespan` on
  `app.state`, `conn.cursor()` per op; every DB call wrapped in
  `asyncio.to_thread`; external analytics must open read-only.

## Repo facts to respect

- Python 3.13+, `uv`-managed. `pyproject.toml` already has `fastapi`,
  `jinja2`, `uvicorn[standard]`, `sc-foundation-services>=3.2.0`,
  `python-dotenv`. **Still to add:** `duckdb`, `httpx`, `twilio` (via `uv add`).
- Keep entry point at `src/main.py` (tooling reads `launch_path`).
- Secrets only in `.env` (currently `SMTP_USERNAME`, `SMTP_PASSWORD`; Twilio
  keys to be added). Never in `config.yaml`.
- `scripts/launch.sh` and `deploy/water-info.service` are done — no changes.
- House style: fetch and mirror LightingControl / PowerController (theme) and
  DisplayBoard (card grid) from github.com/Spello-Consulting (all reachable).
- SC-foundation APIs: confirm against
  https://spello-consulting.github.io/sc-foundation/reference/ as used
  (SCLogging `Files:`/`register_email_settings`/`send_email`, SCConfigManager
  load/validate/`check_for_config_changes`, DateHelper for all date/time).

## Module layout (`src/`)

Per implementation-plan.md: `main.py`, `config.py`, `app.py`, `api_client.py`,
`models.py`, `db.py`, `poller.py`, `cards.py`, `alerts.py`, `sms.py`,
`websocket.py`, `routes.py`, plus `templates/` and `static/`.

## Build order

**Phase 1 — Foundations**
1. `uv add duckdb httpx twilio`.
2. `config.py`: SCConfigManager schema + load (`--config` override); wire
   SCLogging (`Files:`) and `register_email_settings()` (`Email:`). Draft the
   full sample `config.yaml` early (extend the existing starter) covering:
   water-monitor URL + poll interval, retention days (default 90), chart days
   (default 30), sensor→card mapping (match by name, display-name override,
   card type), per-tank display warning/critical %, per-tank email alert+
   recovery %, per-tank SMS alert+recovery %. Document required `.env` keys
   (SMTP + Twilio) in README.
3. `db.py`: DuckDB schema — `tank_readings`, `temp_readings`, `device_latest`
   (upsert). Insert fns, 24h min/max, chart-series (last N days), `prune`.
   All sync; callers wrap in `to_thread`.

**Phase 2 — Data acquisition**
4. `api_client.py`: async httpx GET → validate into `models.py` pydantic
   models.
5. `poller.py`: `asyncio` task from `lifespan`. Each interval: fetch → persist
   readings + device row + update last-valid-response ts → evaluate alerts →
   broadcast state over WS. On failure: keep last values, set every card
   status = Error. Run retention prune once/day from the same loop.

**Phase 3 — Web UI**
6. `cards.py`: map sensors → ordered card view models per config (match by
   name; display-name override; unmapped sensors excluded; config entries with
   no sensor render null-value card). 24h min/max from `db.py`. Status/colour
   rules: status text OK/Warning/Error → black/orange/red from payload
   `status`; water % text orange < warning, red < critical.
7. `routes.py` + `templates/`: home (responsive CSS grid, 2-up iPhone
   portrait / 3-up wider), chart page (server-rendered SVG, last 30d default
   / configurable, high/low lines, home + next-sensor buttons), system page
   (device section + last-valid-response time).
8. `websocket.py` + client JS: push current state on connect, live updates each
   poll.

**Phase 4 — Alerts**
9. `sms.py`: `send_sms()` Twilio wrapper (env creds; graceful warn+skip if
   unset), isolated for future SCLogging migration.
10. `alerts.py`: per-tank, per-channel hysteresis — fire once when % drops
    below the channel's alert threshold; re-arm only after it rises past the
    recovery threshold and drops again. Email via `SCLogging.send_email()`,
    SMS via `send_sms()`. Display warning/critical levels are **independent**
    of email/SMS alert+recovery levels.

**Phase 5 — Hot-reload, tests, deploy**
11. Wire `check_for_config_changes` into the poller loop; apply live where safe
    (poll interval, thresholds, card mapping, retention/chart windows).
    Restart-only settings (DB path, listen host/port) → log a message.
12. Tests (`pytest`, `pytest-mock`, `pytest-dotenv`): payload parsing, card
    mapping edge cases (missing/extra sensors), 24h min/max, alert hysteresis
    state machine, prune. Mock httpx + Twilio.
13. Deploy notes: confirm service paths/user, `.env` present,
    `systemctl enable --now`.

## Verify end-to-end

- `uv sync` then `uv run src/main.py --config config.yaml` (or
  `./scripts/launch.sh`).
- Point at the **live** water-monitor URL (request it from the user). Load
  `http://<host>:<port>/` on phone + desktop: confirm 2-up/3-up grid, live WS
  updates, card colours, chart + system pages.
- Force an API outage → cards go Error, last values retained.
- Feed mock data dropping a tank below alert threshold → one email + one SMS
  (SMS skipped-with-warning if Twilio creds absent), no repeats until
  recovery→re-drop.
- Run `pytest`.
- `systemctl` smoke test on the Ubuntu target.