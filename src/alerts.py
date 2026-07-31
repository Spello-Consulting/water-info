"""Per-tank, per-channel low-water alert dispatch with hysteresis.

Each (tank, channel) pair is a small state machine:

* **armed**  -> fires an *alert* notification once when ``percent_full`` drops
  *below* the channel's alert threshold, then becomes *alerted*.
* **alerted** -> when ``percent_full`` rises *at or above* the channel's recovery
  threshold, fires a *recovery* notification and re-arms; no repeat alerts in
  between.

So a single low-water episode produces exactly two notifications per channel: one
when it drops below the alert level, and one when it recovers. Email is sent via
``SCLogger.send_email``; SMS via :func:`sms.send_sms`. The display
warning/critical thresholds are independent of these alert/recovery thresholds
(see design.md).
"""
from __future__ import annotations

import sms
from config import AppConfig, CardConfig
from models import WaterMonitorPayload

EMAIL = "email"
SMS = "sms"

# Notification kinds.
ALERT = "alert"
RECOVERY = "recovery"


class AlertManager:
    """Holds alert hysteresis state and dispatches email/SMS notifications."""

    def __init__(self, app_config: AppConfig, logger) -> None:
        self._cfg = app_config
        self._logger = logger
        # (sensor_name, channel) -> True if currently alerted (fired, awaiting recovery)
        self._alerted: dict[tuple[str, str], bool] = {}

    def is_alerted(self, sensor: str, channel: str) -> bool:
        return self._alerted.get((sensor, channel), False)

    def evaluate(self, payload: WaterMonitorPayload | None, api_ok: bool) -> None:
        """Evaluate all water cards against the latest payload and dispatch alerts.

        No-op when the API is unreachable or a tank value is unavailable — we
        never fire (or clear) an alert on missing data.
        """
        if not api_ok or payload is None:
            return
        for card in self._cfg.cards():
            if not card.is_water:
                continue
            tank = payload.tank_by_name(card.sensor)
            if tank is None or tank.percent_full is None:
                continue
            value = float(tank.percent_full)
            self._eval_channel(card, EMAIL, value, card.email_alert_percent, card.email_recovery_percent)
            if self._cfg.sms_enabled:
                self._eval_channel(card, SMS, value, card.sms_alert_percent, card.sms_recovery_percent)

    def _eval_channel(self, card: CardConfig, channel: str, value: float, alert_threshold: float | None, recovery_threshold: float | None) -> None:
        if alert_threshold is None or recovery_threshold is None:
            return
        key = (card.sensor, channel)
        alerted = self._alerted.get(key, False)
        if not alerted and value < alert_threshold:
            self._dispatch(card, channel, ALERT, value, alert_threshold)
            self._alerted[key] = True
        elif alerted and value >= recovery_threshold:
            self._alerted[key] = False
            self._dispatch(card, channel, RECOVERY, value, recovery_threshold)

    def _dispatch(self, card: CardConfig, channel: str, event: str, value: float, threshold: float) -> None:
        if event == ALERT:
            subject = f"Low water alert: {card.display_name} at {value:.0f}%"
            body = (
                f"{card.display_name} has fallen to {value:.0f}%, "
                f"below the {channel} alert threshold of {threshold:.0f}%."
            )
        else:  # RECOVERY
            subject = f"Water recovered: {card.display_name} at {value:.0f}%"
            body = (
                f"{card.display_name} has recovered to {value:.0f}%, "
                f"at or above the {channel} recovery threshold of {threshold:.0f}%."
            )
        self._log(f"Dispatching {channel} {event} notification for {card.sensor} at {value:.0f}%.", "summary")
        if channel == EMAIL:
            try:
                self._logger.send_email(subject, body)
            except Exception as exc:  # noqa: BLE001 - never let a mail failure break the poller
                self._log(f"Failed to send email {event} for {card.sensor}: {exc}", "error")
        elif channel == SMS:
            sms.send_sms(self._cfg.sms_to_numbers, body, logger=self._logger)

    def _log(self, message: str, verbosity: str = "summary") -> None:
        if self._logger is not None:
            self._logger.log_message(message, verbosity)
