from __future__ import annotations

import time

from daemon.payloads import (
    build_opencode_go_payload,
    build_deepseek_usage_payload,
    build_openrouter_usage_payload,
    build_zen_usage_payload,
)


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


def test_build_deepseek_prepaid_payload() -> None:
    import time
    now = time.time()
    balance = {
        "is_available": True,
        "balance_infos": [{
            "currency": "CNY",
            "total_balance": "75.00",
            "topped_up_balance": "70.00",
        }]
    }
    p = build_deepseek_usage_payload(
        balance, now=now, total_top_up=100.0,
        daily_spent=5.00, daily_spent_pct=5, daily_reset_mins=360,
    )
    assert p["p"] == "deepseek"
    assert p["plan_type"] == "prepaid"
    assert p["top"]["kind"] == "budget_daily"
    assert p["top"]["pct"] == 5
    assert p["bottom"]["kind"] == "wallet_depletion"
    assert p["bottom"]["pct"] == 70  # (100-30)/100*100 = 70% remaining
    assert p["bottom"]["label"] == "CNY"
    assert p["bottom"]["subtext"] == "75.00"
    assert p["st"] == "allowed"


def test_build_openrouter_prepaid_payload() -> None:
    import time
    now = time.time()
    key_data = {"data": {"usage": 42.50, "limit": 100.00, "is_free": False}}
    p = build_openrouter_usage_payload(
        key_data, now=now,
        daily_spent=5.00, daily_spent_pct=5, daily_reset_mins=360,
    )
    assert p["p"] == "openrouter"
    assert p["plan_type"] == "prepaid"
    assert p["top"]["kind"] == "budget_daily"
    assert p["top"]["pct"] == 5
    assert p["bottom"]["kind"] == "wallet_depletion"
    assert p["bottom"]["pct"] == 57  # (100-42.5)/100*100 = 57%
    assert p["bottom"]["label"] == "CR"
    assert p["bottom"]["subtext"] == "57.50"
    assert p["st"] == "allowed"


def test_build_zen_prepaid_payload() -> None:
    import time
    now = time.time()
    p = build_zen_usage_payload(
        {"balance": 42.50, "currency": "USD"}, now=now,
        daily_spent=0, daily_spent_pct=0, daily_reset_mins=720,
    )
    assert p["p"] == "zen"
    assert p["plan_type"] == "prepaid"
    assert p["top"]["kind"] == "budget_daily"
    assert p["top"]["pct"] == 0
    assert p["bottom"]["kind"] == "wallet_depletion"
    assert p["bottom"]["pct"] == 42
    assert p["bottom"]["label"] == "USD"
    assert p["bottom"]["subtext"] == "42.50"
    assert p["st"] == "allowed"


def test_prepaid_status_thresholds() -> None:
    """Test status derivation for low remaining balance."""
    import time
    now = time.time()
    balance = {
        "is_available": True,
        "balance_infos": [{"currency": "CNY", "total_balance": "5.00", "topped_up_balance": "5.00"}]
    }
    # 5% remaining → limited
    p = build_deepseek_usage_payload(balance, now=now, total_top_up=100.0,
                                      daily_spent=0, daily_spent_pct=0, daily_reset_mins=1440)
    assert p["st"] == "limited"

    # 20% remaining → warning
    balance["balance_infos"][0]["total_balance"] = "20.00"
    balance["balance_infos"][0]["topped_up_balance"] = "20.00"
    p = build_deepseek_usage_payload(balance, now=now, total_top_up=100.0,
                                      daily_spent=0, daily_spent_pct=0, daily_reset_mins=1440)
    assert p["st"] == "warning"


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
