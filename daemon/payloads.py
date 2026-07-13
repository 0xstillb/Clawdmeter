from __future__ import annotations

from collections.abc import Mapping
import time


def _pct(util: str) -> int:
    try:
        return int(round(float(util) * 100))
    except (TypeError, ValueError):
        return 0


def _reset_minutes(reset_ts: str, now: float) -> int:
    try:
        r = float(reset_ts)
    except (TypeError, ValueError):
        return 0
    mins = (r - now) / 60.0
    return int(round(mins)) if mins > 0 else 0


def _int_pct(util: object) -> int:
    try:
        return max(0, min(100, int(round(float(util)))))
    except (TypeError, ValueError):
        return 0


def _remaining_pct(util: object) -> int:
    return 100 - _int_pct(util)


def _reset_minutes_from_value(value: object, now: float) -> int:
    try:
        reset_ts = float(value)
    except (TypeError, ValueError):
        return 0
    mins = (reset_ts - now) / 60.0
    return int(round(mins)) if mins > 0 else 0


def _reset_minutes_from_window(window: Mapping[str, object], now: float) -> int:
    if "reset_at" in window:
        return _reset_minutes_from_value(window.get("reset_at"), now)
    if "resets_at" in window:
        return _reset_minutes_from_value(window.get("resets_at"), now)
    try:
        seconds = float(window.get("reset_after_seconds", 0))
    except (TypeError, ValueError):
        return 0
    mins = seconds / 60.0
    return int(round(mins)) if mins > 0 else 0


def build_provider_payload(*, provider: str, mode: str, top: dict, bottom: dict,
                           status: str = "unknown", ok: bool = True,
                           plan_type: str = "subscription",
                           legacy_aliases: dict | None = None) -> dict:
    payload = {
        "p": provider,
        "plan_type": plan_type,
        "mode": mode,
        "top": top,
        "bottom": bottom,
        "st": status,
        "ok": ok,
    }
    if legacy_aliases:
        payload.update(legacy_aliases)
    return payload


def build_windowed_payload(*, provider: str, top_pct: int, top_reset_mins: int,
                           bottom_pct: int, bottom_reset_mins: int,
                           status: str = "unknown", mode: str = "window",
                           top_has_reset: bool = True, bottom_has_reset: bool = True,
                           top_subtext: str | None = None, bottom_subtext: str | None = None) -> dict:
    return build_provider_payload(
        provider=provider,
        mode=mode,
        top={
            "label": "Current",
            "kind": "window_short",
            "pct": top_pct,
            "reset_mins": top_reset_mins,
            "has_reset": top_has_reset,
            **({"subtext": top_subtext} if top_subtext else {}),
        },
        bottom={
            "label": "Weekly",
            "kind": "window_long",
            "pct": bottom_pct,
            "reset_mins": bottom_reset_mins,
            "has_reset": bottom_has_reset,
            **({"subtext": bottom_subtext} if bottom_subtext else {}),
        },
        status=status,
        ok=True,
        legacy_aliases={
            "s": top_pct,
            "sr": top_reset_mins,
            "w": bottom_pct,
            "wr": bottom_reset_mins,
        },
    )


def build_claude_usage_payload(headers: Mapping[str, str], *, now: float) -> dict:
    def hdr(name: str, default: str = "0") -> str:
        return headers.get(name, default)

    session_pct = _pct(hdr("anthropic-ratelimit-unified-5h-utilization"))
    session_reset = _reset_minutes(hdr("anthropic-ratelimit-unified-5h-reset"), now)
    weekly_pct = _pct(hdr("anthropic-ratelimit-unified-7d-utilization"))
    weekly_reset = _reset_minutes(hdr("anthropic-ratelimit-unified-7d-reset"), now)
    # ── convert to remaining % ──────────────────────────────────────
    session_pct = 100 - session_pct
    weekly_pct = 100 - weekly_pct
    status = hdr("anthropic-ratelimit-unified-5h-status", "unknown")

    return build_windowed_payload(
        provider="claude",
        top_pct=session_pct,
        top_reset_mins=session_reset,
        bottom_pct=weekly_pct,
        bottom_reset_mins=weekly_reset,
        status=status,
    )


def build_opencode_go_payload(parsed: dict, *, now: float | None = None) -> dict:
    """Build a BLE payload from OpenCode Go subscription usage data.

    ``parsed`` must have keys ``rolling``, ``weekly``, ``monthly``. Each window
    may be either the older ``{used, limit, periodEnd}`` shape or the newer
    ``{usagePercent, resetInSec, status}`` shape emitted by the web dashboard.

    The firmware's two-card display maps:
      - **Top card** → weekly remaining quota
      - **Bottom card** → monthly remaining quota
    """
    current_time = time.time() if now is None else now

    def _remaining_window_pct(u: dict) -> int:
        if "usagePercent" in u:
            return _remaining_pct(u.get("usagePercent"))
        lim = u.get("limit", 0) or 1
        used = u.get("used", 0) or 0
        used_pct = max(0, min(100, int(round(used / lim * 100))))
        return 100 - used_pct

    def _reset_mins(u: dict) -> int:
        if "resetInSec" in u:
            try:
                secs = float(u.get("resetInSec", 0))
            except (TypeError, ValueError):
                return 0
            return int(round(secs / 60)) if secs > 0 else 0
        end = u.get("periodEnd")
        if end is None:
            return 0
        try:
            secs = float(end) - current_time
        except (TypeError, ValueError):
            return 0
        return int(round(secs / 60)) if secs > 0 else 0

    weekly_window = parsed.get("weekly", {})
    monthly_window = parsed.get("monthly", {})
    weekly_pct = _remaining_window_pct(parsed.get("weekly", {}))
    weekly_reset = _reset_mins(parsed.get("weekly", {}))
    weekly_has_reset = (
        weekly_window.get("periodEnd") is not None or
        weekly_window.get("resetInSec") is not None
    )
    monthly_pct = _remaining_window_pct(monthly_window)
    monthly_reset = _reset_mins(monthly_window)
    monthly_has_reset = (
        monthly_window.get("periodEnd") is not None or
        monthly_window.get("resetInSec") is not None
    )

    status = "allowed"
    if weekly_pct <= 10 or monthly_pct <= 10:
        status = "limited"
    elif weekly_pct <= 25 or monthly_pct <= 25:
        status = "warning"

    # Labels intentionally differ from build_windowed_payload's standard
    # Current/Weekly wording: Go's useful long-lived limits are Weekly and
    # Monthly, not the rolling request window.
    return build_provider_payload(
        provider="go",
        mode="weekly_monthly",
        top={
            "label": "Weekly",
            "kind": "window_long",
            "pct": weekly_pct,
            "reset_mins": weekly_reset,
            "has_reset": weekly_has_reset,
            **({"subtext": "reset unavailable"} if not weekly_has_reset else {}),
        },
        bottom={
            "label": "Monthly",
            "kind": "window_long",
            "pct": monthly_pct,
            "reset_mins": monthly_reset,
            "has_reset": monthly_has_reset,
            **({"subtext": "reset unavailable"} if not monthly_has_reset else {}),
        },
        status=status,
        legacy_aliases={
            "s": weekly_pct,
            "sr": weekly_reset,
            "w": monthly_pct,
            "wr": monthly_reset,
        },
    )


def build_deepseek_usage_payload(balance_data: dict, *, now: float | None = None) -> dict:
    """Build a BLE payload from DeepSeek's API-only balance response.

    DeepSeek exposes no daily, session, or weekly quota windows. Its balance
    endpoint reports total, paid (topped-up), and granted credit, so the two
    cards show that exact breakdown instead of derived daily spend.

    ``balance_data`` shape from ``GET /user/balance``::

        {
            "is_available": true,
            "balance_infos": [{
                "currency": "CNY",
                "total_balance": "110.00",
                "granted_balance": "10.00",
                "topped_up_balance": "100.00"
            }]
        }

    """
    infos = balance_data.get("balance_infos", [])
    entries = [item for item in infos if isinstance(item, dict)] if isinstance(infos, list) else []
    if not entries:
        return _build_deepseek_fallback_payload(now)

    # A DeepSeek account may contain multiple ledgers. Prefer USD when present.
    info = next((item for item in entries if str(item.get("currency", "")).upper() == "USD"), entries[0])
    is_available = bool(balance_data.get("is_available", True))
    currency = str(info.get("currency", "CNY")).upper()

    def amount(key: str) -> float:
        try:
            return max(0.0, float(info.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0.0

    total_balance = amount("total_balance")
    paid_balance = amount("topped_up_balance")
    granted_balance = amount("granted_balance")
    if granted_balance == 0 and total_balance > paid_balance:
        granted_balance = total_balance - paid_balance

    paid_detail = f"{currency} {paid_balance:.2f} + G {granted_balance:.2f}"
    if total_balance <= 0:
        balance_detail = "Add credits"
    elif not is_available:
        balance_detail = f"{currency} {total_balance:.2f} (API unavailable)"
    else:
        balance_detail = f"{currency} {total_balance:.2f}"

    return build_provider_payload(
        provider="deepseek",
        mode="prepaid",
        plan_type="prepaid",
        top={
            "label": "Paid + Grant",
            "kind": "budget_daily",
            "pct": paid_balance + granted_balance,
            "reset_mins": 0,
            "has_reset": False,
            "subtext": paid_detail,
        },
        bottom={
            "label": "Balance",
            "kind": "wallet_depletion",
            "pct": total_balance,
            "reset_mins": 0,
            "has_reset": False,
            "subtext": balance_detail,
        },
        status="allowed" if is_available and total_balance > 0 else "limited",
        ok=is_available,
        legacy_aliases={"s": total_balance, "sr": 0, "w": paid_balance + granted_balance, "wr": 0},
    )


def _build_deepseek_fallback_payload(now: float | None = None) -> dict:
    """Return a minimal payload when balance API response is unexpected."""
    return build_provider_payload(
        provider="deepseek",
        mode="prepaid",
        plan_type="prepaid",
        top={
            "label": "Paid + Grant",
            "kind": "budget_daily",
            "pct": 0,
            "reset_mins": 0,
            "has_reset": False,
            "subtext": "unavailable",
        },
        bottom={
            "label": "Balance",
            "kind": "wallet_depletion",
            "pct": 0,
            "reset_mins": 0,
            "has_reset": False,
            "subtext": "unavailable",
        },
        status="unknown",
        ok=False,
        legacy_aliases={"s": 0, "sr": 0, "w": 0, "wr": 0},
    )


# ── Generic prepaid helper ──────────────────────────────────────────────


def _prepaid_remaining_pct(total: float, used: float) -> int:
    """Compute remaining percentage from total and used amounts."""
    if total > 0 and used >= 0:
        remaining = max(0, total - used)
        return max(0, min(100, int(round(remaining / total * 100))))
    return 100


def _prepaid_status(remaining_pct: int, is_available: bool = True) -> str:
    """Derive status string from remaining percentage."""
    if not is_available:
        return "limited"
    if remaining_pct <= 10:
        return "limited"
    if remaining_pct <= 25:
        return "warning"
    return "allowed"


# ── OpenRouter payload builder ──────────────────────────────────────────


def build_openrouter_usage_payload(key_data: dict, *, now: float | None = None,
                                    daily_spent: float = 0,
                                    daily_spent_pct: int = 0,
                                    daily_reset_mins: int = 1440) -> dict:
    """Build a BLE payload from OpenRouter auth/key API data (prepaid).

    OpenRouter is a credits-based prepaid system.  Key info from
    ``GET /api/v1/auth/key``::

        {
            "data": {
                "usage": 42.50,
                "limit": 100.00,
                "is_free": false,
                ...
            }
        }

    ``usage`` = credits consumed, ``limit`` = total credits purchased.
    """
    data = key_data.get("data") if isinstance(key_data, dict) else {}
    if not isinstance(data, dict):
        data = {}

    usage = float(data.get("usage", 0) or 0)
    limit = float(data.get("limit", 0) or 0)
    remaining_pct = _prepaid_remaining_pct(limit, usage)
    remaining_credits = max(0, limit - usage)

    status = _prepaid_status(remaining_pct)

    return build_provider_payload(
        provider="openrouter",
        mode="prepaid",
        plan_type="prepaid",
        top={
            "label": "Today",
            "kind": "budget_daily",
            "pct": daily_spent_pct,
            "reset_mins": daily_reset_mins,
            "has_reset": daily_reset_mins > 0,
            "subtext": f"{daily_spent:.2f} credits spent" if daily_spent > 0 else "no spend",
        },
        bottom={
            "label": "CR",
            "kind": "wallet_depletion",
            "pct": remaining_pct,
            "reset_mins": 0,
            "has_reset": False,
            "subtext": f"{remaining_credits:.2f}",
        },
        status=status,
        ok=True,
        legacy_aliases={
            "s": remaining_pct,
            "sr": 0,
            "w": daily_spent_pct,
            "wr": daily_reset_mins,
        },
    )


# ── Zen payload builder ────────────────────────────────────────────────


def build_zen_usage_payload(balance_data: dict, *, now: float | None = None,
                             daily_spent: float = 0,
                             daily_reset_mins: int = 1440,
                             total_budget: float | None = None,
                             total_spent: float | None = None) -> dict:
    """Build a BLE payload from OpenCode Zen balance data (prepaid).

    Scrapes the billing page using Go's auth cookie — there is no
    standalone Zen balance API.

    total_budget: user-configured total top-up ($). When None, firmware
                  defaults to $20 for bar scaling.
                  Set via Zen credentials dialog or zen-credentials.json.
    total_spent:  total_budget - balance (used). When None, falls back to
                  daily_spent for the top card.

    Card layout (raw $ amounts, no % conversion):
      - Top:  total used — pct = total_spent (budget - remaining)
      - Bottom: remaining — pct = dollar balance remaining
    """
    if not isinstance(balance_data, dict):
        balance_data = {}

    balance = float(balance_data.get("balance", 0) or 0)
    currency = str(balance_data.get("currency", "USD") or "USD")

    # Top card: total used (budget - remaining), fallback to daily spend
    top_amount = total_spent if total_spent is not None else daily_spent
    top_subtext = f"${top_amount:.2f}" if top_amount > 0 else "no spend"

    # Status based on raw dollar thresholds
    if balance < 1.0:
        status = "limited"
    elif balance < 5.0:
        status = "warning"
    else:
        status = "allowed"

    payload = build_provider_payload(
        provider="zen",
        mode="prepaid",
        plan_type="prepaid",
        top={
            "label": "Used",
            "kind": "budget_daily",
            "pct": round(top_amount, 2),
            "reset_mins": daily_reset_mins,
            "has_reset": daily_reset_mins > 0,
            "subtext": top_subtext,
        },
        bottom={
            "label": "Remaining",
            "kind": "wallet_depletion",
            "pct": round(balance, 2),
            "reset_mins": 0,
            "has_reset": False,
            "subtext": f"${balance:.2f}",
        },
        status=status,
        ok=True,
        legacy_aliases={
            "s": round(balance, 2),
            "sr": 0,
            "w": round(daily_spent, 2),
            "wr": daily_reset_mins,
        },
    )
    if total_budget is not None and total_budget > 0:
        payload["budget"] = round(total_budget, 2)
    return payload


def build_minimax_usage_payload(data: dict, *, now: float | None = None) -> dict:
    """Build a BLE payload from MiniMax Coding Plan quota data.

    ``/v1/token_plan/remains`` reports *remaining* quota in ``model_remains``.
    It is not a chat-completion response and its percentages must not be
    inverted.  MiniMax's current Coding Plan has a rolling window and a
    weekly window, which map to the two display cards.
    """
    current_time = time.time() if now is None else now
    root = data.get("data") if isinstance(data, dict) else None
    root = root if isinstance(root, dict) else data
    models = root.get("model_remains") if isinstance(root, dict) else None

    def as_number(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def value(item: dict, *names: str) -> object | None:
        for name in names:
            if name in item and item[name] is not None:
                return item[name]
        return None

    def remaining_pct(item: dict, window: str) -> int | None:
        total = as_number(value(item, f"{window}_total_count", f"{window}TotalCount"))
        # Despite its historical name, this field is MiniMax's remaining
        # count. Prefer the count-derived result; it is more exact than the
        # rounded percentage shown in newer API responses and matches the
        # Token Plan web dashboard.
        remaining = as_number(value(item, f"{window}_usage_count", f"{window}UsageCount"))
        if total is not None and total > 0 and remaining is not None:
            return _int_pct(remaining / total * 100)

        # MiniMax's percentage fields already mean remaining quota.
        explicit = value(
            item,
            f"{window}_remaining_percent",
            f"{window}RemainingPercent",
            "usage_percent",
            "usagePercent",
        )
        if explicit is not None:
            return _int_pct(explicit)
        return None

    def reset_mins(item: dict, window: str) -> int:
        if window == "current_weekly":
            # Do not fall back to the interval reset here: it is commonly a
            # five-hour timestamp and would be displayed incorrectly on the
            # weekly card when the API omits its weekly reset.
            seconds = as_number(value(
                item,
                "current_weekly_remains_time",
                "currentWeeklyRemainsTime",
                "weekly_remains_time",
                "weeklyRemainsTime",
            ))
            end = as_number(value(
                item,
                "current_weekly_end_time",
                "currentWeeklyEndTime",
                "weekly_end_time",
                "weeklyEndTime",
            ))
        else:
            seconds = as_number(value(
                item,
                f"{window}_remains_time",
                f"{window}RemainsTime",
                "remains_time",
                "remainsTime",
            ))
            end = as_number(value(item, f"{window}_end_time", f"{window}EndTime", "end_time", "endTime"))
        # The API's explicit reset epoch is authoritative. ``remains_time``
        # is only a fallback; it can lag behind the live rolling five-hour
        # window after a quota refresh.
        if end is not None:
            if end > 10_000_000_000:
                end /= 1000
            if end > current_time:
                return int(round((end - current_time) / 60))

        if seconds is not None and seconds > 0:
            # Some older responses encode duration in milliseconds.
            if seconds > 864_000:
                seconds /= 1000
            return int(round(seconds / 60))
        return 0

    if isinstance(models, list):
        candidates = [item for item in models if isinstance(item, dict)]
        if candidates:
            # Prefer text/chat entries over separate image, video, speech, or
            # music quotas so the monitor follows the Coding Plan people use.
            def is_non_text_service(item: dict) -> bool:
                name = str(value(item, "model_name", "modelName", "service_type", "serviceType") or "").lower()
                return any(token in name for token in ("image", "video", "speech", "music", "audio"))

            text_candidates = [item for item in candidates if not is_non_text_service(item)]
            # A MiniMax response can list a separate video quota with a real
            # count while the text/general plan exposes percentage-only quota.
            # Choose the text/general lane first; otherwise the video reset
            # (often 12 or 24 hours) is incorrectly shown as the 5-hour card.
            if text_candidates:
                candidates = text_candidates

            def chat_score(item: dict) -> int:
                name = str(value(item, "model_name", "modelName", "service_type", "serviceType") or "").lower()
                score = 0
                if name.startswith("minimax-m"):
                    score += 1_000
                elif name in ("general", "text", "text-generation"):
                    score += 500
                elif "minimax" in name:
                    score += 10
                if any(token in name for token in ("m3", "m2", "text", "chat", "coding")):
                    score += 100
                interval_total = as_number(value(item, "current_interval_total_count", "currentIntervalTotalCount"))
                weekly_total = as_number(value(item, "current_weekly_total_count", "currentWeeklyTotalCount"))
                if interval_total is not None and interval_total > 0:
                    score += 10_000
                if weekly_total is not None and weekly_total > 0:
                    score += 1_000
                return score

            item = max(candidates, key=chat_score)
            rolling_pct = remaining_pct(item, "current_interval")
            weekly_pct = remaining_pct(item, "current_weekly")
            if rolling_pct is not None:
                # A plan can temporarily omit its weekly quota. Do not turn
                # that absence into a false 0%; preserve the old fallback only
                # when no Coding Plan fields are present at all.
                if weekly_pct is None:
                    weekly_pct = rolling_pct
                status = "allowed"
                if rolling_pct <= 10 or weekly_pct <= 10:
                    status = "limited"
                elif rolling_pct <= 25 or weekly_pct <= 25:
                    status = "warning"
                return build_windowed_payload(
                    provider="minimax",
                    top_pct=rolling_pct,
                    top_reset_mins=reset_mins(item, "current_interval"),
                    bottom_pct=weekly_pct,
                    bottom_reset_mins=reset_mins(item, "current_weekly"),
                    status=status,
                    top_has_reset=True,
                    bottom_has_reset=True,
                )

    # Compatibility with the original plugin response shape. This path is
    # retained for old self-hosted gateways, not the official Coding Plan API.
    usage = data.get("usage") or data if isinstance(data, dict) else {}
    if not isinstance(usage, dict):
        usage = {}
    rate_used = _int_pct(usage.get("rate_limit_pct", 0))
    rate_pct = 100 - rate_used
    reset_after = int(usage.get("rate_limit_reset_seconds", 60))
    rate_reset_mins = int(round(reset_after / 60)) if reset_after > 0 else 1
    daily_used = _int_pct(usage.get("daily_usage_pct", 0))
    daily_pct = 100 - daily_used
    daily_limit = _int_pct(usage.get("daily_limit", 0))
    daily_reset_mins = 1440
    if not usage.get("daily_usage_pct") and daily_limit > 0:
        total_tokens = _int_pct(usage.get("total_tokens", 0))
        daily_pct = 100 - int(round(total_tokens / max(daily_limit, 1) * 100))

    status = "allowed"
    if daily_used >= 90 or rate_used >= 90:
        status = "limited"
    elif daily_used >= 75 or rate_used >= 75:
        status = "warning"

    return build_windowed_payload(
        provider="minimax",
        top_pct=rate_pct,
        top_reset_mins=rate_reset_mins,
        bottom_pct=daily_pct,
        bottom_reset_mins=daily_reset_mins,
        status=status,
        top_has_reset=True,
        bottom_has_reset=True,
        top_subtext="rate limit" if rate_pct == 0 else None,
        bottom_subtext="daily limit" if daily_pct == 0 else None,
    )


def build_codex_usage_payload(payload: Mapping[str, object], *, now: float | None = None) -> dict:
    rate_limit = payload.get("rate_limit") or {}
    if not isinstance(rate_limit, Mapping):
        raise ValueError("payload must include a rate_limit mapping")

    primary = rate_limit.get("primary_window") or payload.get("primary") or {}
    secondary = rate_limit.get("secondary_window") or payload.get("secondary") or {}
    if not isinstance(primary, Mapping) or not isinstance(secondary, Mapping):
        raise ValueError("payload must include primary and secondary usage windows")

    current_time = time.time() if now is None else now
    session_pct = _remaining_pct(primary.get("used_percent"))
    session_reset = _reset_minutes_from_window(primary, current_time)
    has_secondary_window = "used_percent" in secondary
    weekly_pct = _remaining_pct(secondary.get("used_percent"))
    weekly_reset = _reset_minutes_from_window(secondary, current_time)

    allowed = rate_limit.get("allowed")
    limit_reached = rate_limit.get("limit_reached")
    reached_type = payload.get("rate_limit_reached_type")
    if allowed is True:
        status = "allowed"
    elif isinstance(reached_type, str):
        status = reached_type
    elif limit_reached is True:
        status = "limited"
    else:
        status = "unknown"

    # Codex now returns a single weekly window for some accounts.  The old
    # response had a five-hour primary window plus a weekly secondary window.
    # Do not manufacture a second 100% window when that secondary payload is
    # absent: make the real weekly value the sole visible card instead.
    if not has_secondary_window:
        weekly_pct = session_pct
        weekly_reset = session_reset
        return build_provider_payload(
            provider="codex",
            mode="weekly_only",
            top={
                "label": "Weekly",
                "kind": "window_long",
                "pct": weekly_pct,
                "reset_mins": weekly_reset,
                "has_reset": weekly_reset > 0,
                "subtext": "reset unavailable" if weekly_reset <= 0 else "",
            },
            # Provider payloads require two panels. Firmware that understands
            # weekly_only hides this placeholder; a transport that must flatten
            # the payload can use the aliases below for both cards instead of a
            # stale 100% value.
            bottom={
                "label": "Unavailable",
                "kind": "hidden",
                "pct": 0,
                "reset_mins": 0,
                "has_reset": False,
                "subtext": "not applicable",
            },
            status=str(status),
            legacy_aliases={
                "s": weekly_pct,
                "sr": weekly_reset,
                "w": weekly_pct,
                "wr": weekly_reset,
            },
        )

    return build_windowed_payload(
        provider="codex",
        top_pct=session_pct,
        top_reset_mins=session_reset,
        bottom_pct=weekly_pct,
        bottom_reset_mins=weekly_reset,
        status=str(status),
    )
