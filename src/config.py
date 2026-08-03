"""Configuration loading, validation and typed access for water-info.

Wraps :class:`SCConfigManager` (YAML load + validation + hot-reload) and
:class:`SCLogger` (logging + email). The Cerberus validation schema defined
here is *merged* with the foundation library's built-in schema, so it only
needs to describe the sections this app adds on top of ``Files:`` / ``Email:``.

Config values are read live via :class:`AppConfig` (never cached) so that
``check_for_config_changes`` hot-reloads take effect at the next point of use.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from sc_foundation.sc_config_mgr import SCConfigManager
from sc_foundation.sc_logging import SCLogger

# Cerberus rejects unknown top-level keys, so every section the app uses must
# appear here. Merged with sc_foundation's built-in Files/Email/... schema.
VALIDATION_SCHEMA: dict = {
    "WaterMonitor": {
        "type": "dict",
        "required": True,
        "schema": {
            "URL": {"type": "string", "required": True},
            "PollIntervalSeconds": {"type": "number", "required": False, "min": 1, "max": 3600},
            "RequestTimeoutSeconds": {"type": "number", "required": False, "min": 1, "max": 120},
            # Simulation mode: read payloads from a local JSON file instead of the API.
            "SimulationMode": {"type": "boolean", "required": False, "nullable": True},
            "SimulationFile": {"type": "string", "required": False, "nullable": True},
        },
    },
    "Database": {
        "type": "dict",
        "required": False,
        "schema": {
            "Path": {"type": "string", "required": False, "nullable": True},
            "RetentionDays": {"type": "number", "required": False, "min": 1, "max": 3650},
        },
    },
    "Charting": {
        "type": "dict",
        "required": False,
        "schema": {
            "Days": {"type": "number", "required": False, "min": 1, "max": 3650},
        },
    },
    "Server": {
        "type": "dict",
        "required": False,
        "schema": {
            "Host": {"type": "string", "required": False, "nullable": True},
            "Port": {"type": "number", "required": False, "min": 1, "max": 65535},
        },
    },
    "SMS": {
        "type": "dict",
        "required": False,
        "schema": {
            "EnableSMS": {"type": "boolean", "required": False, "nullable": True},
            "SendSMSTo": {
                "type": "list",
                "required": False,
                "nullable": True,
                "schema": {"type": "string"},
            },
        },
    },
    "Cards": {
        "type": "list",
        "required": True,
        "schema": {
            "type": "dict",
            "schema": {
                "Sensor": {"type": "string", "required": True},
                "Type": {"type": "string", "required": True, "allowed": ["water", "temperature"]},
                "DisplayName": {"type": "string", "required": False, "nullable": True},
                # Display colour thresholds (water cards only)
                "WarningPercent": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 100},
                "CriticalPercent": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 100},
                # Email alert hysteresis (water cards only)
                "EmailAlertPercent": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 100},
                "EmailRecoveryPercent": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 100},
                # SMS alert hysteresis (water cards only)
                "SMSAlertPercent": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 100},
                "SMSRecoveryPercent": {"type": "number", "required": False, "nullable": True, "min": 0, "max": 100},
            },
        },
    },
}


@dataclass(frozen=True)
class CardConfig:
    """One configured card, parsed from a ``Cards:`` list entry."""

    sensor: str
    type: str  # "water" | "temperature"
    display_name: str
    warning_percent: float | None = None
    critical_percent: float | None = None
    email_alert_percent: float | None = None
    email_recovery_percent: float | None = None
    sms_alert_percent: float | None = None
    sms_recovery_percent: float | None = None

    @property
    def is_water(self) -> bool:
        return self.type == "water"


class AppConfig:
    """Typed, reload-safe accessor over an :class:`SCConfigManager`.

    Every getter reads through to the underlying config manager so that a
    hot-reload (which replaces the manager's internal dict) is reflected
    immediately without restarting the app.
    """

    def __init__(self, config_mgr: SCConfigManager) -> None:
        self._cfg = config_mgr

    @property
    def config_mgr(self) -> SCConfigManager:
        return self._cfg

    # --- Water-monitor API -------------------------------------------------
    @property
    def api_url(self) -> str:
        return self._cfg.get("WaterMonitor", "URL")

    @property
    def poll_interval_seconds(self) -> float:
        return self._cfg.get("WaterMonitor", "PollIntervalSeconds", default=30)

    @property
    def request_timeout_seconds(self) -> float:
        return self._cfg.get("WaterMonitor", "RequestTimeoutSeconds", default=10)

    @property
    def simulation_mode(self) -> bool:
        """When True, payloads are read from ``simulation_file`` instead of the API."""
        return bool(self._cfg.get("WaterMonitor", "SimulationMode", default=False))

    @property
    def simulation_file(self) -> str:
        return self._cfg.get("WaterMonitor", "SimulationFile", default="data/payload_sample.json")

    # --- Storage -----------------------------------------------------------
    @property
    def db_path(self) -> str:
        return self._cfg.get("Database", "Path", default="data/water_display.sqlite")

    @property
    def retention_days(self) -> int:
        return int(self._cfg.get("Database", "RetentionDays", default=90))

    # --- Charting ----------------------------------------------------------
    @property
    def chart_days(self) -> int:
        return int(self._cfg.get("Charting", "Days", default=30))

    # --- Server ------------------------------------------------------------
    @property
    def host(self) -> str:
        return self._cfg.get("Server", "Host", default="0.0.0.0")

    @property
    def port(self) -> int:
        return int(self._cfg.get("Server", "Port", default=8000))

    # --- SMS ---------------------------------------------------------------
    @property
    def sms_enabled(self) -> bool:
        return bool(self._cfg.get("SMS", "EnableSMS", default=False))

    @property
    def sms_to_numbers(self) -> list[str]:
        """Recipient numbers for SMS alerts.

        The ``TWILIO_SEND_SMS_TO`` environment variable takes precedence over the
        ``SMS.SendSMSTo`` config key. Multiple numbers may be given in the env var
        as a comma-separated list. When the env var is unset (or empty after
        parsing), the config value is used.
        """
        env_value = os.environ.get("TWILIO_SEND_SMS_TO")
        if env_value is not None:
            numbers = [n.strip() for n in env_value.split(",") if n.strip()]
            if numbers:
                return numbers
        return list(self._cfg.get("SMS", "SendSMSTo", default=[]) or [])

    # --- Cards -------------------------------------------------------------
    def cards(self) -> list[CardConfig]:
        """Return the ordered list of configured cards."""
        raw = self._cfg.get("Cards", default=[]) or []
        cards: list[CardConfig] = []
        for entry in raw:
            sensor = entry.get("Sensor")
            cards.append(
                CardConfig(
                    sensor=sensor,
                    type=entry.get("Type"),
                    display_name=entry.get("DisplayName") or sensor,
                    warning_percent=entry.get("WarningPercent"),
                    critical_percent=entry.get("CriticalPercent"),
                    email_alert_percent=entry.get("EmailAlertPercent"),
                    email_recovery_percent=entry.get("EmailRecoveryPercent"),
                    sms_alert_percent=entry.get("SMSAlertPercent"),
                    sms_recovery_percent=entry.get("SMSRecoveryPercent"),
                )
            )
        return cards


def build_config_manager(config_file: str) -> SCConfigManager:
    """Load and validate the YAML config file, raising on any problem."""
    return SCConfigManager(config_file=config_file, validation_schema=VALIDATION_SCHEMA)


def build_logger(config_mgr: SCConfigManager) -> SCLogger:
    """Construct an :class:`SCLogger` from the ``Files:``/``Email:`` sections."""
    logger = SCLogger(config_mgr.get_logger_settings())
    logger.register_email_settings(config_mgr.get_email_settings())
    config_mgr.register_logger(logger.log_message)
    return logger
