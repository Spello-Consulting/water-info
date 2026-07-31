# Water Display — Implementation Plan

> Companion to [design.md](design.md). This is the pick-up-and-go plan: what to
> build, in what order, and the decisions already made. Read `design.md` first for
> the *what* and *why*; this file is the *how*.

## Current state of the repo

Template scaffolding only — no app logic yet.

- `pyproject.toml` — Python **3.13+**, `uv`-managed. Only real dep so far is
  `sc-foundation-services>=3.2.0`. Dev deps: `pytest`, `pytest-mock`,
  `pytest-dotenv`, `pre-commit`. `launch_path="src/main.py"` and
  `service_name="water-info"` are read by tooling — keep the entry point at
  `src/main.py`.
- `src/main.py` — stub (`print("Hello…")`). This is the entry point to flesh out.
- `scripts/launch.sh` — robust launcher (already done): finds home dir, sources
  `.env`, runs `uv sync`, then `uv run <launch_path>`. Handles SIGTERM cleanly for
  systemd. **No changes needed.**
- `deploy/water-info.service` — systemd unit (already corrected). Runs the
  launch script as user `nick`.
- `.gitignore` — already ignores `.env`, `logs/`, `*.json/*.csv/*.log` in `src/`,
  `.venv/`, etc.
- Config sync: `pyproject.toml [dev.env.sync]` mirrors `.env`, `.vscode/*`, `logs/*`
  to Dropbox — so `.env` lives outside git. **Secrets go in `.env`, never in
  `config.yaml`.**

## Stack & key decisions (already settled)

- **Web:** FastAPI + uvicorn, Jinja2 server-rendered pages, WebSocket push for live
  updates. Style after LightingControl / PowerController; card grid after
  DisplayBoard.
- **HTTP client:** `httpx` (async) to poll the water-monitor REST API.
- **Storage:** local **DuckDB** file — timestamped temp + tank readings, plus latest
  device row.
- **Foundation libs:** `SCLogging` (logging + `send_email`), `SCConfigManager` (yaml
  load/validate + `check_for_config_changes` hot-reload), `DateHelper` (all
  date/time handling).
- **SMS:** Twilio, isolated behind a `send_sms()` module so it can later move into
  SCLogging.
- **Deployment:** single process, systemd, LAN-only, **no auth**.

### DuckDB concurrency model (resolved — the one open question)

- Run **one uvicorn worker only**. DuckDB permits a single read-write process;
  multiple workers would conflict on the file. Document this as a hard constraint.
- **Single writer:** only the poller task writes to DuckDB (readings inserts +
  daily retention prune). One writer ⇒ no write-write contention; MVCC lets web
  reads run concurrently.
- Open **one connection at startup** (FastAPI `lifespan`), store on `app.state`.
  Use `conn.cursor()` per operation so poller and readers don't share a cursor.
- DuckDB calls are blocking — wrap **every** DB call (writes and reads) in
  `asyncio.to_thread(...)` so the event loop / WebSocket pushes never stall.
- External ad-hoc analytics while the app runs must open the DB **read-only**.

## Proposed module layout (`src/`)

```
src/
  main.py          # arg parse (--config, --homedir), build config, launch uvicorn (workers=1)
  config.py        # SCConfigManager setup + validation schema + hot-reload hook
  app.py           # FastAPI app factory + lifespan (open DuckDB, start poller, WS manager)
  api_client.py    # httpx async client for the water-monitor API
  models.py        # pydantic models: raw payload + card/system view models
  db.py            # DuckDB: schema init, insert readings, 24h min/max, chart series, prune
  poller.py        # async loop: poll -> persist -> evaluate alerts -> broadcast WS
  cards.py         # map API sensors -> ordered card view models per config
  alerts.py        # hysteresis state machine + dispatch (email + SMS)
  sms.py           # send_sms() Twilio wrapper (isolated for future SCLogging migration)
  websocket.py     # connection manager + broadcast(state)
  routes.py        # HTTP: GET / (home), GET /chart/{sensor}, GET /system, WS /ws
  templates/       # base.html, home.html, _card_temp.html, _card_water.html, chart.html, system.html
  static/          # css (grid + card theme), minimal js (WS client, chart)
```

Keep `main.py` at that path (tooling reads `launch_path`).

## Build order (phased)

### Phase 1 — Foundations
1. Add deps via `uv add`: `fastapi`, `uvicorn[standard]`, `jinja2`, `duckdb`,
   `httpx`, `twilio`. (`uvicorn[standard]` pulls in the websockets stack.)
2. `config.py`: define the validation schema and load `config.yaml` (override via
   `--config`) through `SCConfigManager`; wire `SCLogging` (`Files:` section) and
   `register_email_settings()` (`Email:` section). Add a sample `config.yaml` in
   the repo (non-sensitive only) and document required `.env` keys (Twilio
   SID/token/from-number, SMTP creds) in the README.
3. `db.py`: DuckDB schema —
   - `tank_readings(ts, sensor_name, percent_full, level_mm, volume_litres, status)`
   - `temp_readings(ts, sensor_name, temperature_c, status)`
   - `device_latest(ts, <device fields…>)` (upsert single latest row)
   Add insert fns, `min/max over last 24h` query, chart-series query (last N days),
   and `prune(older_than_days)`. All sync; callers wrap in `to_thread`.

### Phase 2 — Data acquisition
4. `api_client.py`: async GET of the water-monitor payload → validate into
   `models.py` pydantic models.
5. `poller.py`: `asyncio` task started in `lifespan`. Every `poll_interval`:
   fetch → on success persist readings + device row, update "last valid response"
   timestamp, evaluate alerts, broadcast latest state over WS; **on failure** keep
   last values and mark every card status = Error (per design). Run retention prune
   once/day from the same loop.

### Phase 3 — Web UI
6. `cards.py`: map API sensors → card view models using the config mapping
   (match by sensor **name**; allow display-name override; sensors not in config
   excluded; config entries with no matching sensor render a null-value card).
   Compute 24h min/max from `db.py`. Card status/colour rules per design
   (status from payload `status`; water % text orange < warning, red < critical).
7. `routes.py` + `templates/`: home (responsive CSS grid — 2 across iPhone
   portrait, 3 across on wider), chart page (last 30d default / configurable, with
   high/low reference lines, home + next-sensor buttons), system page (device
   section + last-valid-response time).
8. `websocket.py` + client JS: on connect push current state, then live updates on
   each poll.

### Phase 4 — Alerts
9. `sms.py`: `send_sms()` Twilio wrapper (credentials from env).
10. `alerts.py`: per-tank, per-channel hysteresis — fire once when % drops below the
    channel's alert threshold; re-arm only after it rises past the recovery
    threshold and drops again. Email via `SCLogging.send_email()`, SMS via
    `send_sms()`. Note: display warning/critical levels are **independent** of the
    email/SMS alert+recovery levels.

### Phase 5 — Config hot-reload, tests, deploy
11. Wire `SCConfigManager.check_for_config_changes` into the poller loop; apply
    live where safe (poll interval, thresholds, card mapping, retention/chart
    windows). Settings that can't apply live (DB path, listen host/port) → log and
    require restart.
12. Tests (`pytest` + `pytest-mock`, `pytest-dotenv`): payload parsing, card
    mapping edge cases (missing/extra sensors), 24h min/max queries, alert
    hysteresis state machine, prune. Mock httpx + Twilio.
13. Deploy: confirm `deploy/water-info.service` paths/user on the Ubuntu box,
    `.env` present, `systemctl enable --now water-info`.

## Open items to confirm during build
- Config key names/shape for the schema (nothing locked in yet — design lists the
  options, not the YAML structure). Draft the sample `config.yaml` early.
- Chart library choice (server-rendered SVG vs a small JS lib) — keep it
  self-contained/offline given LAN deployment.

## Verify end-to-end
- `uv sync` then `./scripts/launch.sh` (or `uv run src/main.py --config config.yaml`).
- Point at a live or mocked water-monitor URL; load `http://<host>:<port>/` on
  phone + desktop, confirm 2-up / 3-up grid, live WS updates, card colours,
  chart + system pages.
- Force an API outage → cards go Error, last values retained.
- Drop a tank below alert threshold in mock data → one email + one SMS, no repeats
  until recovery→re-drop.
- `systemctl` smoke test on the Ubuntu target.
