# Water Display

A web application that consumes the water-monitor REST API and displays tank
percentage-full and temperature as a live, responsive card grid, with historic
charts, a system page, and low-water email/SMS alerts.

- **Stack:** FastAPI + uvicorn, Jinja2 server-rendered pages, WebSocket push for
  live updates, SQLite for history, `httpx` for polling, Twilio for SMS.
- **Foundation libs:** [`sc-foundation-services`](https://spello-consulting.github.io/sc-foundation/)
  for logging (`SCLogging`), config (`SCConfigManager`) and date/time (`DateHelper`).
- **Deployment:** single process, systemd, LAN-only, no auth.

See [docs/design.md](docs/design.md) and [docs/implementation-plan.md](docs/implementation-plan.md)
for the full design.

## Requirements

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/) for all package operations (not pip)

## Configuration

Non-sensitive settings live in [`config.yaml`](config.yaml) (override the path
with `--config`). The file is validated at startup and **hot-reloaded** while
running — changes to poll interval, thresholds, card mapping and retention/chart
windows apply live; changes to the database path or server host/port require a
restart.

Key sections:

| Section        | Purpose                                                        |
|----------------|----------------------------------------------------------------|
| `Files`        | `SCLogging` log file settings                                  |
| `Email`        | `SCLogging` email settings (SMTP creds come from `.env`)       |
| `WaterMonitor` | API `URL`, `PollIntervalSeconds`, `RequestTimeoutSeconds`, `SimulationMode`, `SimulationFile` |
| `Database`     | SQLite `Path`, `RetentionDays` (default 90)                    |
| `Charting`     | `Days` charted (default 30)                                    |
| `Server`       | `Host` / `Port` to bind                                        |
| `SMS`          | `EnableSMS`, `SendSMSTo` list (Twilio creds come from `.env`)  |
| `Cards`        | Ordered card list: sensor→card mapping, display names, and per-tank display/alert thresholds |

Cards map to API sensors **by name**. Sensors not listed are excluded; a card
whose sensor is absent from the API renders with null values. Per water card:
`WarningPercent`/`CriticalPercent` set the value text colour (orange/red);
`EmailAlertPercent`/`EmailRecoveryPercent` and `SMSAlertPercent`/`SMSRecoveryPercent`
drive independent alert hysteresis.

**Alert hysteresis:** when a tank drops below a channel's `…AlertPercent`, that
channel sends an **alert** notification once. When it rises back to or above the
channel's `…RecoveryPercent`, the channel sends a **recovery** notification and
re-arms. So each low-water episode produces two messages per channel (down, then
recovered) — no repeats while it stays low or stays recovered. Email and SMS are
evaluated independently against their own thresholds.

## Secrets (`.env`)

Secrets are **never** stored in `config.yaml`. Copy [`.env.example`](.env.example)
to `.env` and fill in:

- `SMTP_USERNAME`, `SMTP_PASSWORD` — for email alerts
- Twilio keys — for SMS alerts (see [SMS alerts (Twilio) setup](#sms-alerts-twilio-setup)).
  If unset, SMS is skipped with a warning and email still works.

`scripts/launch.sh` loads `.env` into the environment automatically. Environment
variables are read at **startup only** — after editing `.env`, restart the app
(unlike `config.yaml`, which hot-reloads).

## SMS alerts (Twilio) setup

SMS alerts go through [Twilio](https://www.twilio.com/). Follow these steps once.

### 1. Get your Account SID

On the [Twilio Console](https://console.twilio.com) dashboard, copy your
**Account SID** — it starts with `AC…`. This is **not** an API key; it identifies
your account and always goes in `TWILIO_ACCOUNT_SID`.

### 2. Create an API key

Console → **Account → API keys & tokens → Create API key**.

- **Key type: Standard** (recommended). Standard keys can send messages out of the
  box. A **Restricted** key must have the *Messaging → Messages: Create* permission
  explicitly granted, or sending fails with
  `70051 required permission twilio/messaging/messages/create is missing`.
- Copy the **SID** (`SK…`) and the **Secret** (shown once) immediately.

> Alternatively you can skip the API key and use your account **Auth Token**
> (dashboard, next to the Account SID): set `TWILIO_AUTH_TOKEN` and leave the
> `TWILIO_API_KEY_*` vars unset. API keys are preferred because they're revocable
> without changing the account token.

### 3. Set up a sender

`TWILIO_FROM_NUMBER` is either:

- a Twilio **phone number** in E.164 format (e.g. `+15005550006`), or
- an **alphanumeric sender ID** — max **11 characters** (letters/digits/spaces,
  e.g. `SpelloWater`). These are one-way (recipients can't reply) and, in many
  countries (Italy included), must be **pre-registered** in the Twilio Console
  before messages will deliver. See Twilio's per-country
  [SMS guidelines](https://www.twilio.com/en-us/guidelines/sms).

### 4. Fill in `.env`

```dotenv
TWILIO_ACCOUNT_SID=AC...          # your account SID (NOT the API key)
TWILIO_API_KEY_SID=SK...          # the Standard API key SID
TWILIO_API_KEY_SECRET=...         # the API key secret
TWILIO_FROM_NUMBER=SpelloWater    # phone number or <=11-char sender ID
```

### 5. Enable and test

Enable SMS and list recipients in `config.yaml`:

```yaml
SMS:
  EnableSMS: True
  SendSMSTo:
    - "+393311194199"
```

Send a test message straight from `.env` (no app needed):

```bash
./scripts/send_test_sms.sh                       # first SendSMSTo recipient
./scripts/send_test_sms.sh +393311194199 "Hi"    # explicit recipient + message
```

An HTTP `201` means Twilio accepted the message. Common failures:

| Twilio error | Cause | Fix |
|---|---|---|
| `70051 … permission … missing` | Restricted API key without messaging-create | Use a Standard key, or grant the permission |
| `70051` with `SK…` in the request path | API key SID used as the account SID | Put the `AC…` account SID in `TWILIO_ACCOUNT_SID` |
| `21212` / invalid `From` | Bad or unregistered sender | Check number/sender-ID length and registration |

Once the test passes, restart the app — low-water readings below a tank's
`SMSAlertPercent` will now send SMS (use **Simulation mode** below to trigger one
on demand).

## Running

```bash
./scripts/launch.sh                 # syncs deps, loads .env, starts the app
# or directly:
uv run src/main.py --config config.yaml
```

Then open `http://<host>:8000/` on a phone or desktop browser. The home grid
shows 2 cards across on iPhone portrait and 3 across on wider screens; tap a card
for its 30-day chart, and use the **System** button for device details.

> **Storage:** the app runs a **single uvicorn worker** by design — the poller
> task is the sole writer to the SQLite database (WAL mode, one shared
> connection). SQLite ships with Python, so there are no native wheels to build
> — which is why the app installs on 32-bit ARM (Raspberry Pi) as well as 64-bit.
> To run ad-hoc analytics while the app is running, open the database
> **read-only**.

## Simulation mode

To test card colours and low-water alerts without the hardware, enable
simulation mode in `config.yaml`:

```yaml
WaterMonitor:
  SimulationMode: True
  SimulationFile: "data/payload_sample.json"
```

The app then reads its payload from `SimulationFile` (a JSON file in the
water-monitor payload format) instead of the live endpoint. Edit the file — e.g.
drop a tank's `percent_full` below its alert threshold — and the change is picked
up on the next poll, driving colours and firing email/SMS alerts exactly as a
live reading would. A ready-to-edit sample lives at
[`data/payload_sample.json`](data/payload_sample.json). Toggling `SimulationMode`
is itself hot-reloaded, so you can switch to/from live data without a restart.

## Development

A local mock of the water-monitor API is also provided (an HTTP server, as
opposed to the file-based simulation mode above):

```bash
uv run python scripts/mock_water_monitor.py --port 9000
# then set WaterMonitor.URL to http://127.0.0.1:9000/ in config.yaml
# drive levels: curl "http://127.0.0.1:9000/set?external=15&internal=45"
```

## Tests

```bash
uv run pytest
```

## Deployment

Production runs under systemd. Ensure `.env` is present in the working directory, then:

### 1. Deploy the water-info.service file

```bash
sudo cp deploy/water-info.service /etc/systemd/system/
```

Edit the deployed file and validate paths, user name, etc.

```bash
sudo nano /etc/systemd/system/water-info.service
```

## 2. Enable and start the service

```bash
sudo systemctl daemon-reexec       # re-executes systemd in case of changes
sudo systemctl daemon-reload       # reload service files
sudo systemctl enable water-info   # enable on boot
sudo systemctl start water-info    # start now
```

## 3. View logs

```bash
journalctl -u water-info -f
```
