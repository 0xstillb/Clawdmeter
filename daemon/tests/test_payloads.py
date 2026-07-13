from __future__ import annotations

import time

from daemon.payloads import (
    build_codex_usage_payload,
    build_opencode_go_payload,
    build_deepseek_usage_payload,
    build_minimax_usage_payload,
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
    assert payload["s"] == 75
    assert payload["w"] == 50
    assert payload["top"]["label"] == "Weekly"
    assert payload["bottom"]["label"] == "Monthly"
    assert payload["top"]["pct"] == 75
    assert payload["bottom"]["pct"] == 50
    assert payload["st"] == "allowed"


def test_build_codex_usage_payload_maps_single_window_to_weekly() -> None:
    now = time.time()
    payload = build_codex_usage_payload(
        {
            "rate_limit": {
                "allowed": True,
                "primary_window": {
                    "used_percent": 37,
                    "reset_after_seconds": 3 * 24 * 60 * 60,
                },
            },
        },
        now=now,
    )

    assert payload["p"] == "codex"
    assert payload["mode"] == "weekly_only"
    assert payload["top"]["label"] == "Weekly"
    assert payload["top"]["kind"] == "window_long"
    assert payload["top"]["pct"] == 63
    assert payload["top"]["reset_mins"] == 4320
    # Legacy firmware should still see the one real value, not a fixed 100%.
    assert payload["s"] == 63
    assert payload["w"] == 63


def test_build_opencode_go_payload_preserves_missing_reset_subtext() -> None:
    payload = build_opencode_go_payload(
        {
            "weekly": {"used": 20.0, "limit": 100.0},
            "monthly": {"used": 30.0, "limit": 100.0},
        },
        now=0,
    )

    assert payload["top"]["pct"] == 80
    assert payload["bottom"]["pct"] == 70
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
        }, {
            "currency": "USD",
            "total_balance": "50.00",
            "granted_balance": "10.00",
            "topped_up_balance": "40.00",
        }],
    }
    p = build_deepseek_usage_payload(balance, now=now)
    assert p["p"] == "deepseek"
    assert p["plan_type"] == "prepaid"
    assert p["top"]["kind"] == "budget_daily"
    assert p["top"]["label"] == "Paid + Grant"
    assert p["top"]["subtext"] == "USD 40.00 + G 10.00"
    assert p["bottom"]["kind"] == "wallet_depletion"
    assert p["bottom"]["pct"] == 50
    assert p["bottom"]["label"] == "Balance"
    assert p["bottom"]["subtext"] == "USD 50.00"
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
        daily_spent=0, daily_reset_mins=720,
    )
    assert p["p"] == "zen"
    assert p["plan_type"] == "prepaid"
    assert p["top"]["kind"] == "budget_daily"
    assert p["top"]["pct"] == 0
    assert p["top"]["subtext"] == "no spend"
    assert p["bottom"]["kind"] == "wallet_depletion"
    assert p["bottom"]["pct"] == 42.5
    assert p["bottom"]["label"] == "Remaining"
    assert p["bottom"]["subtext"] == "$42.50"
    assert p["top"]["label"] == "Used"
    assert p["st"] == "allowed"


def test_prepaid_status_thresholds() -> None:
    """Test status derivation for low remaining balance."""
    import time
    now = time.time()
    balance = {
        "is_available": True,
        "balance_infos": [{"currency": "CNY", "total_balance": "5.00", "topped_up_balance": "5.00"}]
    }
    # A zero balance prompts the user to add credits.
    balance["balance_infos"][0]["total_balance"] = "0.00"
    balance["balance_infos"][0]["topped_up_balance"] = "0.00"
    p = build_deepseek_usage_payload(balance, now=now)
    assert p["st"] == "limited"
    assert p["bottom"]["subtext"] == "Add credits"

    # A positive balance marked unavailable stays visible with its status.
    balance["balance_infos"][0]["total_balance"] = "20.00"
    balance["balance_infos"][0]["topped_up_balance"] = "20.00"
    balance["is_available"] = False
    p = build_deepseek_usage_payload(balance, now=now)
    assert p["st"] == "limited"
    assert p["bottom"]["subtext"] == "CNY 20.00 (API unavailable)"


def test_build_opencode_go_payload_supports_dashboard_usage_percent_shape() -> None:
    payload = build_opencode_go_payload(
        {
            "rolling": {"status": "ok", "resetInSec": 16437, "usagePercent": 8},
            "weekly": {"status": "ok", "resetInSec": 380382, "usagePercent": 4},
            "monthly": {"status": "ok", "resetInSec": 2554239, "usagePercent": 2},
        },
        now=0,
    )

    assert payload["s"] == 96
    assert payload["w"] == 98
    assert payload["top"]["pct"] == 96
    assert payload["bottom"]["pct"] == 98
    assert payload["top"]["has_reset"] is True
    assert payload["bottom"]["has_reset"] is True
    assert payload["sr"] == 6340
    assert payload["wr"] == 42571
    assert payload["st"] == "allowed"


def test_build_minimax_coding_plan_payload_uses_remaining_quota() -> None:
    """Token Plan percentages/counts are remaining, not used values."""
    payload = build_minimax_usage_payload(
        {
            "data": {
                "model_remains": [
                    {
                        "model_name": "MiniMax-M3",
                        "current_interval_total_count": 100,
                        "current_interval_usage_count": 70,
                        "current_interval_remaining_percent": 70,
                        "remains_time": 7200,
                        "current_weekly_total_count": 1000,
                        "current_weekly_usage_count": 400,
                        "current_weekly_remaining_percent": 40,
                        "current_weekly_remains_time": 259200,
                    },
                    {
                        "model_name": "image-01",
                        "current_interval_remaining_percent": 5,
                    },
                ]
            }
        },
        now=0,
    )

    assert payload["p"] == "minimax"
    assert payload["top"]["pct"] == 70
    assert payload["bottom"]["pct"] == 40
    assert payload["sr"] == 120
    assert payload["wr"] == 4320
    assert payload["st"] == "allowed"


def test_minimax_count_fields_override_rounded_remaining_percent() -> None:
    """Counts are the source of truth when dashboard and API differ by rounding."""
    payload = build_minimax_usage_payload(
        {
            "data": {
                "model_remains": [{
                    "model_name": "MiniMax-M3",
                    "current_interval_total_count": 1000,
                    "current_interval_usage_count": 731,
                    "current_interval_remaining_percent": 70,
                    "current_weekly_total_count": 1000,
                    "current_weekly_usage_count": 541,
                    "current_weekly_remaining_percent": 50,
                    "weekly_remains_time": 604800000,
                }]
            }
        },
        now=0,
    )

    assert payload["top"]["pct"] == 73
    assert payload["bottom"]["pct"] == 54
    assert payload["bottom"]["reset_mins"] == 10080


def test_minimax_prefers_future_reset_epoch_over_stale_remains_time() -> None:
    """The live five-hour reset epoch wins when duration data lags behind."""
    now = 1_700_000_000
    payload = build_minimax_usage_payload(
        {
            "data": {
                "model_remains": [{
                    "model_name": "MiniMax-M3",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 70,
                    "remains_time": 1_800,
                    "end_time": now + 5 * 60 * 60,
                    "current_weekly_total_count": 1000,
                    "current_weekly_usage_count": 400,
                    "weekly_remains_time": 3 * 24 * 60 * 60,
                }]
            }
        },
        now=now,
    )

    assert payload["top"]["reset_mins"] == 300


def test_minimax_uses_general_text_lane_instead_of_video_reset() -> None:
    """A real video quota must not replace the general five-hour plan window."""
    now = 1_700_000_000
    payload = build_minimax_usage_payload(
        {
            "model_remains": [
                {
                    "model_name": "general",
                    "current_interval_remaining_percent": 98,
                    "end_time": (now + 5 * 60 * 60) * 1000,
                    "current_weekly_remaining_percent": 95,
                    "weekly_end_time": (now + 7 * 24 * 60 * 60) * 1000,
                },
                {
                    "model_name": "video",
                    "current_interval_total_count": 3,
                    "current_interval_usage_count": 0,
                    "end_time": (now + 12 * 60 * 60) * 1000,
                    "current_weekly_total_count": 21,
                    "current_weekly_usage_count": 0,
                },
            ]
        },
        now=now,
    )

    assert payload["top"]["pct"] == 98
    assert payload["top"]["reset_mins"] == 300
    assert payload["bottom"]["pct"] == 95
