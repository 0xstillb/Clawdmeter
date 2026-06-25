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
      - **Top card** (``window_short``) → rolling 5-hour usage
      - **Bottom card** (``window_long``) → weekly usage

    Monthly usage is carried in the status string so a future firmware rev
    can surface it without a protocol break.
    """
    current_time = time.time() if now is None else now

    def _remaining_window_pct(u: dict) -> int:
        if "usagePercent" in u:
            return _remaining_pct(u.get("usagePercent"))
        lim = u.get("limit", 0) or 1
        used = u.get("used", 0) or 0
        used_pct = max(0, min(100, int(round(used / lim * 100))))
        return 100 - used_pct

    def _used_window_pct(u: dict) -> int:
        if "usagePercent" in u:
            return _int_pct(u.get("usagePercent"))
        lim = u.get("limit", 0) or 1
        used = u.get("used", 0) or 0
        return max(0, min(100, int(round(used / lim * 100))))

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

    rolling_pct = _remaining_window_pct(parsed.get("rolling", {}))
    rolling_reset = _reset_mins(parsed.get("rolling", {}))
    rolling_window = parsed.get("rolling", {})
    weekly_window = parsed.get("weekly", {})
    monthly_window = parsed.get("monthly", {})

    rolling_has_reset = (
        rolling_window.get("periodEnd") is not None or
        rolling_window.get("resetInSec") is not None
    )
    weekly_pct = _remaining_window_pct(parsed.get("weekly", {}))
    weekly_reset = _reset_mins(parsed.get("weekly", {}))
    weekly_has_reset = (
        weekly_window.get("periodEnd") is not None or
        weekly_window.get("resetInSec") is not None
    )
    monthly_pct = _used_window_pct(monthly_window)

    status = f"m{monthly_pct}" if monthly_pct else "allowed"

    return build_windowed_payload(
        provider="go",
        top_pct=rolling_pct,
        top_reset_mins=rolling_reset,
        bottom_pct=weekly_pct,
        bottom_reset_mins=weekly_reset,
        status=status,
        top_has_reset=rolling_has_reset,
        bottom_has_reset=weekly_has_reset,
        top_subtext=None if rolling_has_reset else "reset unavailable",
        bottom_subtext=None if weekly_has_reset else "reset unavailable",
    )


def build_deepseek_usage_payload(headers: Mapping[str, str], *, now: float) -> dict:
    """Build a BLE payload from DeepSeek API rate-limit headers.

    DeepSeek returns per-minute rate-limit headers on every API response:
      - X-RateLimit-Limit-Requests  (max requests per minute)
      - X-RateLimit-Remaining-Requests  (remaining in this minute window)
      - X-RateLimit-Reset-Requests  (seconds until reset)

    Also uses X-RateLimit-Limit-Tokens / X-RateLimit-Remaining-Tokens when
    available for a token-based view.  Falls back to requests-based when
    token headers are absent.

    Mapping: top card = requests/utilization (short window, per-minute),
             bottom card = token utilization (longer view).
    """
    current_time = time.time() if now is None else now

    def hdr(name: str, default: str = "0") -> str:
        return headers.get(name, default)

    # ── request-based (short window) ─────────────────────────────────
    req_limit = _int_pct(hdr("x-ratelimit-limit-requests", "60"))
    req_remaining = _int_pct(hdr("x-ratelimit-remaining-requests", "0"))
    req_reset_sec = _int_pct(hdr("x-ratelimit-reset-requests", "60"))
    req_pct = 100 - int(round(req_remaining / max(req_limit, 1) * 100)) if req_limit > 0 else 0
    req_reset_mins = int(round(req_reset_sec / 60)) if req_reset_sec > 0 else 0

    # ── token-based (long window) ───────────────────────────────────
    tok_limit = _int_pct(hdr("x-ratelimit-limit-tokens", "0"))
    tok_remaining = _int_pct(hdr("x-ratelimit-remaining-tokens", "0"))
    tok_reset_sec = _int_pct(hdr("x-ratelimit-reset-tokens", "0"))
    has_token_headers = tok_limit > 0

    if has_token_headers:
        tok_pct = 100 - int(round(tok_remaining / max(tok_limit, 1) * 100)) if tok_limit > 0 else 0
        tok_reset_mins = int(round(tok_reset_sec / 60)) if tok_reset_sec > 0 else 0
    else:
        tok_pct = req_pct
        tok_reset_mins = req_reset_mins

    status = "allowed"
    if tok_pct >= 90 or req_pct >= 90:
        status = "limited"
    elif tok_pct >= 75 or req_pct >= 75:
        status = "warning"

    return build_windowed_payload(
        provider="deepseek",
        top_pct=req_pct,
        top_reset_mins=req_reset_mins,
        bottom_pct=tok_pct,
        bottom_reset_mins=tok_reset_mins,
        status=status,
        top_has_reset=req_reset_mins > 0,
        bottom_has_reset=tok_reset_mins > 0,
        top_subtext="requests/min" if req_reset_mins <= 0 else None,
        bottom_subtext="tokens/min" if not has_token_headers else None,
    )


def build_minimax_usage_payload(data: dict, *, now: float | None = None) -> dict:
    """Build a BLE payload from MiniMax API usage data.

    MiniMax returns usage info in the response body under ``usage``:
      {
        "usage": {
          "total_tokens": N,
          "prompt_tokens": N,
          "completion_tokens": N,
          "daily_usage_pct": 45,       # optional — percentage of daily limit used
          "daily_limit": 1000000,
          "rate_limit_pct": 12          # optional — current rate-limit utilization
        }
      }

    Mapping:
      - Top card (window_short) → rate-limit utilization (per-minute)
      - Bottom card (window_long) → daily token usage
    """
    current_time = time.time() if now is None else now
    usage = data.get("usage") or data if isinstance(data, dict) else {}
    if not isinstance(usage, dict):
        usage = {}

    # ── rate-limit utilization (short window) ───────────────────────
    rate_pct = _int_pct(usage.get("rate_limit_pct", 0))
    reset_after = int(usage.get("rate_limit_reset_seconds", 60))
    rate_reset_mins = int(round(reset_after / 60)) if reset_after > 0 else 1

    # ── daily token usage (long window) ─────────────────────────────
    daily_pct = _int_pct(usage.get("daily_usage_pct", 0))
    daily_limit = _int_pct(usage.get("daily_limit", 0))
    daily_reset_mins = 1440  # ~24 hours

    # If we only have raw token counts, compute a rough percentage
    if daily_pct == 0 and daily_limit > 0:
        total_tokens = _int_pct(usage.get("total_tokens", 0))
        daily_pct = int(round(total_tokens / max(daily_limit, 1) * 100))

    status = "allowed"
    if daily_pct >= 90 or rate_pct >= 90:
        status = "limited"
    elif daily_pct >= 75 or rate_pct >= 75:
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
