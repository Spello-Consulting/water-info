"""Config validation, typed access and hot-reload tests."""
from __future__ import annotations

import time

import pytest
import yaml

from config import AppConfig, build_config_manager

VALID_CONFIG = {
    "Files": {"LogfileVerbosity": "debug", "ConsoleVerbosity": "debug"},
    "WaterMonitor": {"URL": "http://127.0.0.1:9000/", "PollIntervalSeconds": 15},
    "Database": {"Path": "data/x.sqlite", "RetentionDays": 60},
    "Charting": {"Days": 14},
    "Server": {"Host": "0.0.0.0", "Port": 8080},
    "Cards": [
        {"Sensor": "External Tank Water Level", "Type": "water", "DisplayName": "Ext",
         "WarningPercent": 40, "CriticalPercent": 20},
        {"Sensor": "External Air Temperature", "Type": "temperature"},
    ],
}


def _write(path, data):
    path.write_text(yaml.dump(data))
    return str(path)


def test_valid_config_loads(tmp_path):
    cfg = AppConfig(build_config_manager(_write(tmp_path / "c.yaml", VALID_CONFIG)))
    assert cfg.api_url == "http://127.0.0.1:9000/"
    assert cfg.poll_interval_seconds == 15
    assert cfg.retention_days == 60 and cfg.chart_days == 14
    assert cfg.port == 8080
    cards = cfg.cards()
    assert cards[0].display_name == "Ext" and cards[0].is_water
    assert cards[1].display_name == "External Air Temperature"  # falls back to sensor name


def test_defaults_applied(tmp_path):
    minimal = {
        "Files": {"LogfileVerbosity": "debug", "ConsoleVerbosity": "debug"},
        "WaterMonitor": {"URL": "http://x/"},
        "Cards": [{"Sensor": "T", "Type": "water"}],
    }
    cfg = AppConfig(build_config_manager(_write(tmp_path / "c.yaml", minimal)))
    assert cfg.poll_interval_seconds == 30
    assert cfg.retention_days == 90 and cfg.chart_days == 30
    assert cfg.port == 8000


def test_invalid_card_type_rejected(tmp_path):
    bad = {**VALID_CONFIG, "Cards": [{"Sensor": "T", "Type": "banana"}]}
    with pytest.raises(RuntimeError):
        build_config_manager(_write(tmp_path / "c.yaml", bad))


def test_missing_required_section_rejected(tmp_path):
    bad = {k: v for k, v in VALID_CONFIG.items() if k != "WaterMonitor"}
    with pytest.raises(RuntimeError):
        build_config_manager(_write(tmp_path / "c.yaml", bad))


def test_sms_to_numbers_from_config(tmp_path, monkeypatch):
    monkeypatch.delenv("TWILIO_SEND_SMS_TO", raising=False)
    data = {**VALID_CONFIG, "SMS": {"SendSMSTo": ["+15005550006"]}}
    cfg = AppConfig(build_config_manager(_write(tmp_path / "c.yaml", data)))
    assert cfg.sms_to_numbers == ["+15005550006"]


def test_sms_to_numbers_env_overrides_config(tmp_path, monkeypatch):
    data = {**VALID_CONFIG, "SMS": {"SendSMSTo": ["+15005550006"]}}
    cfg = AppConfig(build_config_manager(_write(tmp_path / "c.yaml", data)))
    monkeypatch.setenv("TWILIO_SEND_SMS_TO", " +393311194199 , +14155550100 ")
    assert cfg.sms_to_numbers == ["+393311194199", "+14155550100"]


def test_sms_to_numbers_empty_env_falls_back_to_config(tmp_path, monkeypatch):
    data = {**VALID_CONFIG, "SMS": {"SendSMSTo": ["+15005550006"]}}
    cfg = AppConfig(build_config_manager(_write(tmp_path / "c.yaml", data)))
    monkeypatch.setenv("TWILIO_SEND_SMS_TO", "  ,  ")
    assert cfg.sms_to_numbers == ["+15005550006"]


def test_hot_reload_picks_up_changes(tmp_path):
    path = tmp_path / "c.yaml"
    mgr = build_config_manager(_write(path, VALID_CONFIG))
    cfg = AppConfig(mgr)
    assert cfg.poll_interval_seconds == 15

    from sc_foundation.sc_date_helper import DateHelper
    last_check = DateHelper.now()
    time.sleep(1.1)  # ensure mtime advances past last_check

    changed = {**VALID_CONFIG, "WaterMonitor": {"URL": "http://127.0.0.1:9000/", "PollIntervalSeconds": 99}}
    _write(path, changed)
    result = mgr.check_for_config_changes(last_check)
    assert result is not None                 # detected a change
    assert cfg.poll_interval_seconds == 99     # live value updated after reload
