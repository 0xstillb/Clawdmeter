import asyncio
import json

import pytest

import daemon.wifi_fallback_config as config


@pytest.fixture(autouse=True)
def _isolated_wifi_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_CONFIG_FILE", tmp_path / "wifi-fallback.json")
    monkeypatch.setattr(config, "_STATUS_FILE", tmp_path / "wifi-fallback-status.json")


def _valid_config():
    return {
        "ssid": "desk-wifi",
        "password": "correct horse battery staple",
        "provider": "deepseek",
        "api_key": "sk-test-key",
    }


def test_save_keeps_config_only_until_cyd_acknowledges():
    saved = _valid_config()
    config.save_wifi_config(saved)

    assert config.load_wifi_config() == saved
    assert config.load_wifi_config(pending_only=True) == saved

    config.mark_wifi_config_synced(saved)

    assert config.load_wifi_config() is None
    assert config.load_wifi_config(pending_only=True) is None
    assert config.wifi_settings_label() == "Wi-Fi settings: Saved on CYD — desk-wifi · DeepSeek"


def test_tray_label_marks_unsent_settings_pending():
    config.save_wifi_config(_valid_config())

    assert config.wifi_settings_label() == "Wi-Fi settings: Waiting for CYD — desk-wifi · DeepSeek"


def test_tray_label_uses_cyd_confirmation_when_no_local_status_exists():
    assert config.wifi_settings_label(cyd_configured=True) == "Wi-Fi settings: Saved on CYD"


def test_invalid_configuration_is_not_persisted():
    invalid = _valid_config()
    invalid["provider"] = "codex"

    with pytest.raises(ValueError):
        config.save_wifi_config(invalid)

    assert config.load_wifi_config() is None


def test_malformed_saved_configuration_is_ignored():
    config._CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config._CONFIG_FILE.write_text(json.dumps({"ssid": "x", "provider": "deepseek"}), encoding="utf-8")

    assert config.load_wifi_config() is None


def test_wifi_config_waits_for_cyd_confirmation():
    from daemon.claude_usage_daemon_windows import Session

    class Client:
        async def write_gatt_char(self, _uuid, data, response=True):
            assert response is True
            assert b'"api_key":"sk-test-key"' in data
            session._on_tx(None, bytearray(b'{"wifi":"updated"}'))

    session = Session(Client())

    assert asyncio.run(session.write_wifi_config(_valid_config())) is True


def test_wifi_connected_status_is_forwarded_to_tray():
    from daemon.claude_usage_daemon_windows import Session

    statuses = []
    session = Session(object())
    session.wifi_status_callback = statuses.append

    session._on_tx(None, bytearray(b'{"wifi":"connected"}'))

    assert statuses == ["connected"]
