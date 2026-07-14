"""Local, pending Wi-Fi fallback settings for the CYD tray flow.

The actual credentials live in CYD NVS after a successful BLE transfer.  This
small local copy only lets the tray retry a configuration that was saved while
the board was disconnected or running older firmware.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


_CONFIG_FILE = (
    Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    / "clawdmeter"
    / "wifi-fallback.json"
)
_STATUS_FILE = _CONFIG_FILE.with_name("wifi-fallback-status.json")
_PROVIDERS = frozenset(("deepseek", "openrouter", "minimax"))


def load_wifi_config(*, pending_only: bool = False) -> dict[str, str] | None:
    """Return valid saved credentials, optionally only when they need syncing."""
    try:
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or (pending_only and not raw.get("pending")):
        return None
    config = {
        "ssid": str(raw.get("ssid", "")),
        "password": str(raw.get("password", "")),
        "provider": str(raw.get("provider", "")),
        "api_key": str(raw.get("api_key", "")),
    }
    if (not config["ssid"] or len(config["ssid"]) > 32
            or not config["password"] or len(config["password"]) > 63
            or config["provider"] not in _PROVIDERS
            or not config["api_key"] or len(config["api_key"]) > 192):
        return None
    return config


def save_wifi_config(config: dict[str, str]) -> None:
    """Validate and persist a configuration that still needs a CYD sync."""
    normalized = {
        "ssid": str(config.get("ssid", "")).strip(),
        "password": str(config.get("password", "")),
        "provider": str(config.get("provider", "")).strip().lower(),
        "api_key": str(config.get("api_key", "")).strip(),
        "pending": True,
    }
    if (not normalized["ssid"] or len(normalized["ssid"]) > 32
            or not normalized["password"] or len(normalized["password"]) > 63
            or normalized["provider"] not in _PROVIDERS
            or not normalized["api_key"] or len(normalized["api_key"]) > 192):
        raise ValueError("Invalid Wi-Fi fallback configuration")
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    _write_wifi_status("pending", normalized)


def mark_wifi_config_synced(config: dict[str, str]) -> None:
    """Remove the local retry copy only if this is still the current config."""
    current = load_wifi_config()
    if current != config:
        return
    _write_wifi_status("synced", config)
    clear_wifi_config()


def clear_wifi_config() -> None:
    try:
        _CONFIG_FILE.unlink()
    except FileNotFoundError:
        pass


def _write_wifi_status(state: str, config: dict[str, str]) -> None:
    """Persist only non-secret status metadata for the tray."""
    _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_FILE.write_text(json.dumps({
        "state": state,
        "ssid": str(config.get("ssid", "")),
        "provider": str(config.get("provider", "")),
    }, indent=2), encoding="utf-8")


def wifi_settings_label(*, cyd_configured: bool = False) -> str:
    """Return a short, non-secret Wi-Fi configuration state for the tray."""
    try:
        raw = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "Wi-Fi settings: Saved on CYD" if cyd_configured else "Wi-Fi settings: Not configured"
    if not isinstance(raw, dict):
        return "Wi-Fi settings: Saved on CYD" if cyd_configured else "Wi-Fi settings: Not configured"
    ssid = str(raw.get("ssid", "")).strip()
    provider = str(raw.get("provider", "")).strip().lower()
    provider_label = {
        "deepseek": "DeepSeek",
        "minimax": "MiniMax",
        "openrouter": "OpenRouter",
    }.get(provider, "")
    details = " · ".join(part for part in (ssid, provider_label) if part)
    suffix = f" — {details}" if details else ""
    if raw.get("state") == "pending":
        return f"Wi-Fi settings: Waiting for CYD{suffix}"
    if raw.get("state") == "synced":
        return f"Wi-Fi settings: Saved on CYD{suffix}"
    return "Wi-Fi settings: Saved on CYD" if cyd_configured else "Wi-Fi settings: Not configured"
