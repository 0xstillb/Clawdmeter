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
                           legacy_aliases: dict | None = None) -> dict:
    payload = {
        "p": provider,
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
                           status: str = "unknown", mode: str = "window") -> dict:
    return build_provider_payload(
        provider=provider,
        mode=mode,
        top={
            "label": "Current",
            "kind": "window_short",
            "pct": top_pct,
            "reset_mins": top_reset_mins,
            "has_reset": True,
        },
        bottom={
            "label": "Weekly",
            "kind": "window_long",
            "pct": bottom_pct,
            "reset_mins": bottom_reset_mins,
            "has_reset": True,
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
    status = hdr("anthropic-ratelimit-unified-5h-status", "unknown")

    return build_windowed_payload(
        provider="claude",
        top_pct=session_pct,
        top_reset_mins=session_reset,
        bottom_pct=weekly_pct,
        bottom_reset_mins=weekly_reset,
        status=status,
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

    return build_windowed_payload(
        provider="codex",
        top_pct=session_pct,
        top_reset_mins=session_reset,
        bottom_pct=weekly_pct,
        bottom_reset_mins=weekly_reset,
        status=str(status),
    )
