# **Water Display Application Design**

Water Display is a web application that is a consumer to the water-monitor app that we recently implemented. The goal of the water-display app is to display water percentage full and temperature information via a web interface to a user, and also to send notifications when the water percentage in a tank gets too low.

## Application architecture 

The app will be uvicorn / FastAPI application that serves  Jinja2 rendered pages and pushes state updates to clients over WebSockets.

## Tooling 

### Local repo

The local working directory is `~/dev/water-display` 

### Package management 

Use `uv`  (not pip) for all package operations

### Package dependencies 

Use [sc-foundation-services](https://spello-consulting.github.io/sc-foundation/) for:

    - Logging - [SCLogging](https://spello-consulting.github.io/sc-foundation/reference/logging/)
    - Yaml configuration file management and  validation - [SCConfigManager](https://spello-consulting.github.io/sc-foundation/reference/configmanager/)
    - Date and time handling - [DateHelper](https://spello-consulting.github.io/sc-foundation/reference/datehelper/)

## Runtime environment

Development will be on an Apple Silicon MacMini and production deployment will be to a Ubuntu server. 

## Data Acquisition

The app will poll the water-monitor Rest API every X seconds (configurable). An example of the returned json payload is:

### Example payload response  

```
{
  "device": {
    "firmware_version": "1.28.0",
    "app_version": "0.1.0",
    "api_request_count": 1,
    "uptime_seconds": 29,
    "name": "water-monitor",
    "reset_cause": "HARD_RESET",
    "free_heap_bytes": 98256,
    "status": "ok",
    "wifi_rssi_dbm": -83,
    "boot_count": 13
  },
  "tank_sensors": [
    {
      "distance_mm": 134,
      "volume_litres": 1994,
      "connected": true,
      "gpio_tx_pin": 4,
      "level_mm": 1596,
      "percent_full": 100,
      "age_seconds": 5,
      "name": "External Tank Water Level",
      "status": "ok",
      "gpio_rx_pin": 16,
      "consecutive_failures": 0
    },
    {
      "distance_mm": 150,
      "volume_litres": 400,
      "connected": true,
      "gpio_tx_pin": 23,
      "level_mm": 800,
      "percent_full": 100,
      "age_seconds": 4,
      "name": "Internal Tank Water Level",
      "status": "ok",
      "gpio_rx_pin": 17,
      "consecutive_failures": 0
    }
  ],
  "temperature_probes": [
    {
      "rom_registered": true,
      "status": "ok",
      "name": "External Tank Water Temperature",
      "connected": true,
      "age_seconds": 3,
      "temperature_c": 23.5,
      "gpio_pin": 18,
      "rom_id": "28977122000000fd"
    },
    {
      "rom_registered": true,
      "status": "ok",
      "name": "External Air Temperature",
      "connected": true,
      "age_seconds": 3,
      "temperature_c": 30.6,
      "gpio_pin": 18,
      "rom_id": "280fd7ca00000017"
    },
    {
      "rom_registered": true,
      "status": "ok",
      "name": "Internal Tank Water Temperature",
      "connected": true,
      "age_seconds": 2,
      "temperature_c": 22.0,
      "gpio_pin": 19,
      "rom_id": "287df3cb00000089"
    },
    {
      "rom_registered": true,
      "status": "ok",
      "name": "Internal Air Temperature",
      "connected": true,
      "age_seconds": 2,
      "temperature_c": 27.1,
      "gpio_pin": 19,
      "rom_id": "2823112200000037"
    }
  ],
  "errors": []
}

```

Timestamped sensor data (temperature and water tank) will be logged to a local SQLite database, together with the latest values for the system wide device data. 

> **Storage engine note:** the original design used DuckDB, but DuckDB has no
> prebuilt wheel for 32-bit ARM userlands (as found on many Raspberry Pi OS
> installs) and its C++ source build exhausts memory on a Pi. The app therefore
> uses **SQLite**, which is bundled with Python and needs no compilation on any
> architecture. Timestamps are stored as UTC epoch seconds.

Concurrency: the app runs a single uvicorn worker and one shared SQLite
connection (WAL mode). The poller task is the only writer, every DB call is
serialised by a lock and executed off the event loop via `asyncio.to_thread`,
and ad-hoc external analytics should open the database read-only.


Historic sensor data will be preserved for a set period of time (configurable, 90 days by default), data older than this will be removed from the DB.

## Web design

The web application should follow style and design themes used in the [LightingControl](https://github.com/Spello-Consulting/LightingControl) and [PowerController](https://github.com/Spello-Consulting/PowerController) web interfaces.

The home page will use a css grid to render multiple “cards” (similar to topics used by [DisplayBoard](https://github.com/Spello-Consulting/DisplayBoard)) via a Jinja2 page template. The app supports two types of cards - Temperature and Water Percentage.

The web app is a responsive design. The nominal page is designed for the iPhone portrait layout and shows two across. Larger display (iPad landscape, desktop browser) will cause the app to automatically switch to 3 cards wide.

The configuration file controls which sensor data is used for each card and the order in which cards are displayed.

### Temperature cards

Each temperature card will show:

- Temperature in a large font in the centre of the card with a smaller font for the single decimal place.
- Sensor name top left corner
- Max temp (over the past 24 hours) top right corner
- Min temp (over the past 24 hours) bottom right corner
- Status text bottom left corner. This will be OK, Warning or Error, in black, orange or red text respectively. This reflects the value of the `temperature_probes[]: status` key in the water-monitor payload.

### Water Percentage cards

Each water percentage full card will show:

- Tank percentage full in a large font in the centre of the card 
- Sensor name top left corner
- Max percentage (over past 24 hours) top right corner
- Min percentage (over past 24 hours) bottom right corner
- Status text bottom left corner. This will be OK, Warning or Error, in black, orange or red text respectively.  This reflects the value of the `tank_sensors[]: status` key in the water-monitor payload.

The configuration file sets warning and critical water percentage full for each tank. 

The card’s tank percentage full text will be shown in orange text if the percentage full falls below the warning amount, and in red text if it falls below the critical amount.

### Charting pages

You can click / tap on a card to show the historic chart for that sensor. This page plots temperature or water percentage full for the last 30 days (or for all data available). Horizontal lines on chart shows high and low for the same period. The page includes buttons to return to home page and to go to next sensor.

## System page

The home page includes a button to navigate to the system summary page. This page shows:

- The data from the `device` section of the API payload response.
- The date / time that the last valid API response was obtained. 

## Configuration file

The app reads its non-sensitive configuration data from a configuration file. This will be config.yaml by default, but the file name / location can be overridden via a command line argument. The configuration file is validated at startup using a validation schema and the [SCConfigManager](https://spello-consulting.github.io/sc-foundation/reference/configmanager/) library. 

The file must be monitored for changes (see [check\_for\_config\_changes](https://spello-consulting.github.io/sc-foundation/reference/configmanager/#sc_foundation.sc_config_mgr.SCConfigManager.check_for_config_changes)) and new settings reloaded and applied to the running app when detected where possible. 

Configuration options include:

- water-monitor API URL and polling interval
- The standard `Files:`  section used by [SCLogging](https://spello-consulting.github.io/sc-foundation/reference/logging/)
- The standard `Email`  section used by [SCLogging](https://spello-consulting.github.io/sc-foundation/reference/logging/).register\_email\_settings() 
- Sensor data retention period (defaults to 90 days)
- Charting period (defaults to 30 days)
- Mapping of sensor names in the water-monitor API response to web app cards and layout. Mapping is via sensor names (eg. "External Tank Water Level") and the card config allows an alternate name to be displayed (eg. "External Water %"). Sensors present in the API payload but not in the mapping config are excluded. Config mapping entries that don't match to a sensor in the API data show a card with null values.
- Water tank warning and critical percentage full amounts for each tank (used for the display cards)
- Water tank email alert and recovery percentage full amounts for each tank
- Water tank SMS alert and recovery percentage full amounts for each tank

I'll leave the yaml config file structure to you Claude to determine, with the exception of the `Files` and `Email` sections. A starter file exists in the repo.

## Sensitive data 

Sensitive data (eg. SMTP username and password) will be stored in a .env and passed into the app as o/s environment parameters. The launch script `scripts/launch.sh` automates the load of the .env file into the environment. 

## Error handling 

If the water-monitor API is unreachable, the last values obtained should be displayed and the status of each card set to error. 

## Authentication

The web app URL will be exposed on the local LAN. There is no requirement for authentication to the web app. 

## Email and SMS Alerts

If the percentage full in a water tank falls below a set amount (say 20%), the app can send an email and/or SMS alert channel. The configuration file sets the threshold amount for each alert type. Once an alert has been sent to a particular channel, no further alerts will be sent until the water percentage full goes back up past the recovery amount and then falls back down below the alert amount.

When the water percentage full rises back to (or above) the recovery amount after an alert, the app sends a second **recovery notification** on the same channel, and re-arms that channel. So a single low-water episode produces exactly two notifications per channel: one when it drops below the alert level, and one when it recovers.


Email alerts will be sent using [SCLogging](https://spello-consulting.github.io/sc-foundation/reference/logging/).[send\_email](https://spello-consulting.github.io/sc-foundation/reference/logging/#sc_foundation.sc_logging.SCLogger.send_email)() 

SMS alerts will be sent via Twilio. For this, implement send\_sms() in a separate module so that this functionality can be migrated to [SCLogging](https://spello-consulting.github.io/sc-foundation/reference/logging/) at a later date.

## Deployment 

In production, the app will be launched by systemd. See `deploy/water-display.service` for a template service file.
