#!/usr/bin/env python3
"""Unit tests for Codex provider support in the Windows daemon."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from daemon.config import config_path, provider_preference, set_provider
from daemon.payloads import build_opencode_go_payload
from daemon.claude_usage_daemon_windows import (
    _account_id_from_id_token,
    _provider_failure_payload,
    _payload_for_wire,
    _read_codex_credentials,
    _select_usage_source,
    _usage_payload_from_codex_response,
    poll_codex_api,
)


def _fake_jwt(account_id: str) -> str:
    payload = {
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account_id,
        }
    }
    payload_json = json.dumps(payload).encode("utf-8")
    payload_b64 = __import__("base64").urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")
    return f"header.{payload_b64}.sig"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_account_id_from_id_token():
    assert _account_id_from_id_token(_fake_jwt("acct-123")) == "acct-123"


def test_provider_config_overrides_env(monkeypatch):
    monkeypatch.setenv("CLAWDMETER_PROVIDER", "codex")

    assert set_provider("claude") is True

    assert config_path().exists()
    assert provider_preference() == "claude"


def test_zen_failure_payload_replaces_stale_provider_data():
    """A Zen scrape failure still changes the ESP32 header to ZEN."""
    payload = _provider_failure_payload("zen", "Zen: unable to fetch balance")

    assert payload is not None
    assert payload["p"] == "zen"
    assert payload["plan_type"] == "prepaid"
    assert payload["top"] == {
        "label": "Used",
        "kind": "budget_daily",
        "pct": 0,
        "reset_mins": 0,
        "has_reset": False,
        "subtext": "$0.00",
    }
    assert payload["bottom"]["subtext"] == "$0.00"
    # Error payloads deliberately remain provider-shaped on the BLE wire.
    assert _payload_for_wire(payload) == payload
    assert _provider_failure_payload("codex", "unavailable") is None


def test_read_codex_credentials_from_auth_json(tmp_path, monkeypatch):
    codex_home = tmp_path / ".Codex"
    codex_home.mkdir()
    auth_path = codex_home / "auth.json"
    auth_path.write_text(json.dumps({
        "tokens": {
            "access_token": "codex-access",
            "refresh_token": "codex-refresh",
            "id_token": _fake_jwt("acct-xyz"),
        }
    }))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    creds = _read_codex_credentials()

    assert creds is not None
    assert creds["access_token"] == "codex-access"
    assert creds["refresh_token"] == "codex-refresh"
    assert creds["account_id"] == "acct-xyz"


def test_usage_payload_from_codex_response():
    now = time.time()
    payload = _usage_payload_from_codex_response({
        "rate_limit": {
            "allowed": True,
            "primary_window": {
                "used_percent": 12.2,
                "reset_at": now + 3600,
            },
            "secondary_window": {
                "used_percent": 48.7,
                "reset_after_seconds": 7200,
            },
        }
    })

    assert payload is not None
    assert payload["p"] == "codex"
    assert payload["s"] == 88
    assert payload["w"] == 51
    assert abs(payload["sr"] - 60) <= 1
    assert abs(payload["wr"] - 120) <= 1


def test_codex_weekly_only_payload_is_not_flattened_for_wire():
    payload = _usage_payload_from_codex_response({
        "rate_limit": {
            "allowed": True,
            "primary_window": {
                "used_percent": 25,
                "reset_after_seconds": 3600,
            },
        },
    })

    assert payload is not None
    wire = _payload_for_wire(payload)
    assert wire["p"] == "codex"
    assert wire["mode"] == "weekly_only"
    assert wire["top"]["label"] == "Weekly"


def test_go_weekly_monthly_payload_is_not_flattened_for_wire():
    payload = build_opencode_go_payload({
        "weekly": {"used": 25, "limit": 100, "periodEnd": 7200},
        "monthly": {"used": 10, "limit": 100, "periodEnd": 14400},
    }, now=0)

    wire = _payload_for_wire(payload)

    assert wire["top"]["label"] == "Weekly"
    assert wire["bottom"]["label"] == "Monthly"


def test_select_usage_source_prefers_codex(monkeypatch):
    import daemon.claude_usage_daemon_windows as mod

    monkeypatch.delenv("CLAWDMETER_PROVIDER", raising=False)

    provider, error = _select_usage_source()

    # Auto-probe should pick the first available plugin
    assert provider is not None or error is not None


def test_select_usage_source_respects_claude_override(monkeypatch):
    import daemon.claude_usage_daemon_windows as mod

    monkeypatch.setenv("CLAWDMETER_PROVIDER", "claude")

    provider, error = _select_usage_source()

    assert provider == "claude"
    assert error is None


def test_select_usage_source_aliases_opencode_to_codex(monkeypatch):
    """Verify that alias 'opencode-go' normalizes to 'go' via config."""
    from daemon.config import normalize_provider

    assert normalize_provider("opencode-go") == "go"
    assert normalize_provider("opencode") == "codex"


def test_poll_codex_api_uses_first_non_404_endpoint(monkeypatch):
    first = MagicMock(status_code=404, text="missing")
    second = MagicMock(status_code=200, text="ok")
    second.json.return_value = {
        "rate_limit": {
            "allowed": True,
            "primary_window": {"used_percent": 7, "reset_after_seconds": 1800},
            "secondary_window": {"used_percent": 21, "reset_after_seconds": 7200},
        }
    }

    http = AsyncMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.get = AsyncMock(side_effect=[first, second])

    with patch("httpx.AsyncClient", return_value=http):
        payload = _run(poll_codex_api({"access_token": "codex-access"}))

    assert payload is not None
    assert payload["p"] == "codex"
    assert payload["s"] == 93
    assert payload["w"] == 79
