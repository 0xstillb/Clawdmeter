from __future__ import annotations

import time

from daemon.payloads import build_opencode_go_payload


def test_build_opencode_go_payload_uses_remaining_percent() -> None:
    now = time.time()

    payload = build_opencode_go_payload(
        {
            "rolling": {"used": 0.0, "limit": 100.0, "periodEnd": now + 3600},
            "weekly": {"used": 25.0, "limit": 100.0, "periodEnd": now + 7200},
            "monthly": {"used": 50.0, "limit": 100.0, "periodEnd": now + 14400},
        },
        now=now,
    )

    assert payload["p"] == "go"
    assert payload["s"] == 100
    assert payload["w"] == 75
    assert payload["top"]["pct"] == 100
    assert payload["bottom"]["pct"] == 75
    assert payload["st"] == "m50"


def test_build_opencode_go_payload_preserves_missing_reset_subtext() -> None:
    payload = build_opencode_go_payload(
        {
            "rolling": {"used": 10.0, "limit": 100.0},
            "weekly": {"used": 20.0, "limit": 100.0},
            "monthly": {"used": 0.0, "limit": 100.0},
        },
        now=0,
    )

    assert payload["top"]["pct"] == 90
    assert payload["bottom"]["pct"] == 80
    assert payload["top"]["has_reset"] is False
    assert payload["bottom"]["has_reset"] is False
    assert payload["top"]["subtext"] == "reset unavailable"
    assert payload["bottom"]["subtext"] == "reset unavailable"
    assert payload["st"] == "allowed"


def test_build_opencode_go_payload_supports_dashboard_usage_percent_shape() -> None:
    payload = build_opencode_go_payload(
        {
            "rolling": {"status": "ok", "resetInSec": 16437, "usagePercent": 8},
            "weekly": {"status": "ok", "resetInSec": 380382, "usagePercent": 4},
            "monthly": {"status": "ok", "resetInSec": 2554239, "usagePercent": 2},
        },
        now=0,
    )

    assert payload["s"] == 92
    assert payload["w"] == 96
    assert payload["top"]["pct"] == 92
    assert payload["bottom"]["pct"] == 96
    assert payload["top"]["has_reset"] is True
    assert payload["bottom"]["has_reset"] is True
    assert payload["sr"] == 274
    assert payload["wr"] == 6340
    assert payload["st"] == "m2"
