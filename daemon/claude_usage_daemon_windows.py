#!/usr/bin/env python3
"""Clawdmeter usage daemon for native Windows.

Supports Claude usage via the Anthropic OAuth flow, Codex usage via the
local Codex auth store plus OpenAI usage endpoints, and OpenCode Go
usage via dashboard scraping. All providers emit the same BLE payload
shape so the firmware can stay provider-agnostic.
"""

import asyncio
import base64
import datetime
import json
import logging
import logging.handlers
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path

# Allow `python daemon\claude_usage_daemon_windows.py` from the repo root.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

from daemon.config import PROVIDER_AUTO, auto_provider_ids, provider_preference
from daemon.payloads import build_claude_usage_payload, build_codex_usage_payload, build_opencode_go_payload
from daemon.plugin_runner import PluginRunner, PluginNotFoundError, PluginCrashedError
from daemon.petdex.constants import PET_ANIM_CHAR_UUID
from daemon.petdex.petdex_engine import PetdexEngine

DEVICE_NAME = "Clawdmeter"
SERVICE_UUID = "4c41555a-4465-7669-6365-000000000001"
RX_CHAR_UUID = "4c41555a-4465-7669-6365-000000000002"
TX_CHAR_UUID = "4c41555a-4465-7669-6365-000000000003"
REQ_CHAR_UUID = "4c41555a-4465-7669-6365-000000000004"

# Shared petdex engine for this process (keeps last pet selection for refresh)
_pet_engine = PetdexEngine()
_pet_engine.discover()
_pet_active_slug: str | None = None       # set by tray on pet select
_pet_active_state: str = "idle"
_pet_refresh_interval = 5                # resend pet every 5s to recover from splash transition

# Counter: how many pet refresh attempts since last successful write
_pet_refresh_misses: int = 0
_pet_refresh_miss_limit: int = 6          # after 30s of failures, stop spamming

POLL_INTERVAL = 60
TICK = 5
SCAN_TIMEOUT = 8.0
CONNECT_RETRIES = 3        # D-01: attempts before giving up on a device
CONNECT_RETRY_DELAY = 2.0  # D-01: seconds between failed connect attempts
ZOMBIE_BREAK_LIMIT = 3     # D-03: consecutive write failures before abandoning a half-open link
                           # N=1: breaks at T=60s, leaves ~60s headroom for reconnect+poll inside 120s SLA
                           # N=2 would bust the 120s budget before reconnect even begins
RECONNECT_BACKOFF_CAP = 8  # D-05: fast-reconnect cap (seconds); keeps stacked retries inside 120s SLA
                           # ~5–10s band per CONTEXT.md Claude's Discretion; 8 chosen as middle ground
CODEX_REFRESH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_REFRESH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_USAGE_URLS = (
    "https://chatgpt.com/backend-api/wham/usage",
    "https://chatgpt.com/backend-api/codex/usage",
)

API_URL = "https://api.anthropic.com/v1/messages"
API_HEADERS_TEMPLATE = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20",
    "Content-Type": "application/json",
    "User-Agent": "claude-code/2.1.5",
}
API_BODY = {
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1,
    "messages": [{"role": "user", "content": "hi"}],
}
BLE_ADDRESS_ENV = "CLAWDMETER_BLE_ADDRESS"


def _build_file_logger() -> logging.Logger | None:
    """Create a rotating file logger for field diagnostics, or None.

    Autostart launches the tray under pythonw.exe, which has no console — stdout
    is discarded (and is in fact None, making print() unsafe). A rotating file is
    then the ONLY trail when the daemon stalls in the field. Windows-only: on the
    Linux dev box / CI the console print() suffices, and gating to win32 keeps the
    pure-helper unit tests from writing stray log files.
    """
    if sys.platform != "win32":
        return None
    logger = logging.getLogger("clawdmeter.daemon")
    if logger.handlers:
        return logger  # idempotent across re-import (tray imports this module)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = base / "Clawdmeter" / "daemon.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
        )
    except OSError:
        return None  # best-effort — logging setup must never stop the daemon
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


_FILE_LOGGER = _build_file_logger()


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    # Under pythonw sys.stdout is None and print() would raise — guard it so a
    # missing console can never crash the daemon thread (the silent-freeze mode).
    try:
        print(line, flush=True)
    except (OSError, ValueError, AttributeError, RuntimeError):
        pass
    if _FILE_LOGGER is not None:
        _FILE_LOGGER.info(msg)


class AuthError(Exception):
    """Raised by poll_api on a genuine 401/403 — the token really is expired or
    invalid and the user must re-run `claude login`. Distinct from a None return,
    which means a TRANSIENT failure (network/DNS, timeout, rate-limit, 5xx) that
    must NOT be mislabeled as a token problem (SC#5: a boot-time `getaddrinfo
    failed` DNS blip wrongly fired the 'token expired' toast)."""


async def poll_api(token: str) -> dict | None:
    headers = dict(API_HEADERS_TEMPLATE)
    headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(API_URL, headers=headers, json=API_BODY)
    except httpx.HTTPError as e:
        # Network/DNS/timeout — transient. Return None (no toast), retry next tick.
        log(f"API call failed: {e}")
        return None
    if resp.status_code in (401, 403):
        # Genuine auth rejection — the ONLY case that warrants the actionable
        # "run claude login" toast.
        log(f"API HTTP {resp.status_code}: {resp.text[:200]}")
        raise AuthError(resp.status_code)
    if resp.status_code >= 400:
        # Other 4xx/5xx (rate-limit, server error) — transient, not a token issue.
        log(f"API HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    now = time.time()
    return build_claude_usage_payload(resp.headers, now=now)


def _provider_preference() -> str:
    return provider_preference()


def _saved_ble_address_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "Clawdmeter" / "ble-address.txt"


def _is_probable_ble_address(addr: str) -> bool:
    return bool(
        re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", addr)
        or re.fullmatch(r"[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}", addr)
    )


def _ble_address_override() -> str | None:
    raw = os.environ.get(BLE_ADDRESS_ENV, "").strip()
    if not raw:
        return None
    if _is_probable_ble_address(raw):
        return raw
    log(f"Ignoring invalid {BLE_ADDRESS_ENV} value: {raw!r}")
    return None


def load_cached_address() -> str | None:
    path = _saved_ble_address_path()
    try:
        addr = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if _is_probable_ble_address(addr):
        return addr
    log("Cached BLE address malformed, discarding")
    clear_cached_address()
    return None


def save_cached_address(addr: str) -> bool:
    if not _is_probable_ble_address(addr):
        return False
    path = _saved_ble_address_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(addr, encoding="utf-8")
    except OSError as e:
        log(f"Failed to save cached BLE address: {e}")
        return False
    return True


def clear_cached_address() -> None:
    _saved_ble_address_path().unlink(missing_ok=True)


def _codex_auth_candidates() -> list[Path]:
    if override := os.environ.get("CODEX_HOME"):
        return [Path(override) / "auth.json"]

    home = Path.home()
    return [
        home / ".Codex" / "auth.json",
        home / ".codex" / "auth.json",
    ]


def _account_id_from_id_token(id_token: object) -> str | None:
    if not isinstance(id_token, str):
        return None
    parts = id_token.split(".")
    if len(parts) < 2:
        return None

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload + padding)
        claims = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(claims, dict):
        return None
    auth = claims.get("https://api.openai.com/auth")
    if not isinstance(auth, dict):
        return None
    account_id = auth.get("chatgpt_account_id")
    return account_id if isinstance(account_id, str) else None


def _read_codex_credentials() -> dict | None:
    for path in _codex_auth_candidates():
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log(f"Codex auth.json parse failed at {path}")
            continue
        if not isinstance(data, dict):
            continue
        tokens = data.get("tokens")
        if not isinstance(tokens, dict):
            continue
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        account_id = tokens.get("account_id") or _account_id_from_id_token(tokens.get("id_token"))
        if isinstance(access_token, str) and access_token:
            return {
                "path": path,
                "data": data,
                "access_token": access_token,
                "refresh_token": refresh_token if isinstance(refresh_token, str) else None,
                "account_id": account_id if isinstance(account_id, str) else None,
            }
    return None


def _write_codex_credentials(creds: dict) -> bool:
    path = creds.get("path")
    data = creds.get("data")
    if not isinstance(path, Path) or not isinstance(data, dict):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"Codex auth.json write failed: {e}")
        return False
    return True


async def _refresh_codex_credentials(creds: dict) -> dict | None:
    refresh_token = creds.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        log("Codex refresh token unavailable")
        return None

    body = {
        "client_id": CODEX_REFRESH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(
                CODEX_REFRESH_TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as e:
        log(f"Codex OAuth refresh failed: {e}")
        return None
    if resp.status_code >= 400:
        log(f"Codex OAuth refresh HTTP {resp.status_code}")
        return None

    try:
        refresh_data = resp.json()
    except json.JSONDecodeError:
        log("Codex OAuth refresh response was not JSON")
        return None

    access_token = refresh_data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        log("Codex OAuth refresh response missing access token")
        return None

    new_refresh_token = refresh_data.get("refresh_token")
    if not isinstance(new_refresh_token, str) or not new_refresh_token:
        new_refresh_token = refresh_token

    data = creds.get("data")
    if not isinstance(data, dict):
        return None
    tokens = data.setdefault("tokens", {})
    if not isinstance(tokens, dict):
        return None

    tokens["access_token"] = access_token
    tokens["refresh_token"] = new_refresh_token
    id_token = refresh_data.get("id_token")
    if isinstance(id_token, str):
        tokens["id_token"] = id_token
    data["last_refresh"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    refreshed = {
        **creds,
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "account_id": creds.get("account_id") or _account_id_from_id_token(id_token),
        "data": data,
    }
    if not _write_codex_credentials(refreshed):
        log("Codex OAuth refresh succeeded but auth.json could not be updated")
    log("Codex OAuth refresh succeeded")
    return refreshed


def _usage_payload_from_codex_response(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    try:
        return build_codex_usage_payload(payload, now=time.time())
    except ValueError:
        return None


async def poll_codex_api(creds: dict, *, retry_on_401: bool = True) -> dict | None:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {creds['access_token']}",
        "User-Agent": "codex-cli",
    }
    account_id = creds.get("account_id")
    if isinstance(account_id, str) and account_id:
        headers["ChatGPT-Account-Id"] = account_id

    last_status = None
    for url in CODEX_USAGE_URLS:
        try:
            async with httpx.AsyncClient(timeout=20.0) as http:
                resp = await http.get(url, headers=headers)
        except httpx.HTTPError as e:
            log(f"Codex usage call failed: {e}")
            return None

        if resp.status_code == 404:
            last_status = 404
            continue
        if resp.status_code == 401 and retry_on_401:
            log("Codex usage HTTP 401; attempting OAuth refresh")
            refreshed = await _refresh_codex_credentials(creds)
            if refreshed is None:
                return None
            return await poll_codex_api(refreshed, retry_on_401=False)
        if resp.status_code >= 400:
            log(f"Codex usage HTTP {resp.status_code}: {resp.text[:200]}")
            return None

        try:
            payload = resp.json()
        except json.JSONDecodeError:
            log("Codex usage response was not JSON")
            return None
        return _usage_payload_from_codex_response(payload)

    if last_status == 404:
        log("Codex usage endpoint unavailable")
    return None


# ── OpenCode Go ────────────────────────────────────────────────────────────

GO_DASHBOARD_URL = "https://opencode.ai/workspace/{workspace_id}/go"


def _read_opencode_go_credentials() -> dict | None:
    """Return {workspace_id, auth_cookie} from env or config file, or None."""
    wid = os.environ.get("OPENCODE_GO_WORKSPACE_ID", "").strip()
    cookie = os.environ.get("OPENCODE_GO_AUTH_COOKIE", "").strip()
    if wid and cookie:
        return {"workspace_id": wid, "auth_cookie": cookie}

    config_paths = [
        Path.home() / ".config" / "clawdmeter" / "opencode-go-credentials.json",
        Path.home() / ".config" / "opencode" / "opencode-go-usage.json",
    ]
    for path in config_paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        wid = data.get("workspaceId") or data.get("workspace_id") or ""
        cookie = data.get("authCookie") or data.get("auth_cookie") or ""
        if isinstance(wid, str) and isinstance(cookie, str) and wid and cookie:
            return {"workspace_id": wid, "auth_cookie": cookie}
    return None


def _parse_opencode_go_html(html: str) -> dict | None:
    """Extract rolling/weekly/monthly usage data from dashboard HTML.

    The page embeds JS variables like::

        rollingUsage: $R[42]={"used":0.0,"limit":12.0,...}
        weeklyUsage:  $R[43]={"used":5.1,"limit":30.0,...}
        monthlyUsage: $R[44]={"used":5.0,"limit":60.0,...}

    Newer builds instead embed compact percentage objects like::

        rollingUsage:$R[35]={status:"ok",resetInSec:16437,usagePercent:8}
    """
    patterns = {
        "rolling": r'rollingUsage:\s*(?:\$R\[\d+\]\s*=\s*)?(\{[^}]+\})',
        "weekly": r'weeklyUsage:\s*(?:\$R\[\d+\]\s*=\s*)?(\{[^}]+\})',
        "monthly": r'monthlyUsage:\s*(?:\$R\[\d+\]\s*=\s*)?(\{[^}]+\})',
    }

    result = {}
    for key, pat in patterns.items():
        m = re.search(pat, html)
        if not m:
            log(f"OpenCode Go: {key} usage not found in dashboard HTML")
            continue
        raw = m.group(1)
        # Fix unquoted JS object keys → valid JSON
        quoted = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)', r'\1"\2"\3', raw)
        try:
            data = json.loads(quoted)
        except json.JSONDecodeError as e:
            log(f"OpenCode Go: failed to parse {key} data: {e}")
            continue
        if isinstance(data, dict):
            result[key] = data

    return result if result else None


async def poll_opencode_go_api(creds: dict) -> dict | None:
    """Fetch OpenCode Go dashboard and return a BLE-ready payload."""
    wid = creds.get("workspace_id", "")
    cookie = creds.get("auth_cookie", "")
    url = GO_DASHBOARD_URL.format(workspace_id=wid)
    headers = {
        "Cookie": f"auth={cookie}",
        "User-Agent": "clawdmeter/1.0",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.get(url, headers=headers)
    except httpx.HTTPError as e:
        log(f"OpenCode Go: HTTP request failed: {e}")
        return None

    if resp.status_code == 401 or resp.status_code == 403:
        log(f"OpenCode Go: auth failed (HTTP {resp.status_code}) — cookie may be expired")
        raise AuthError(resp.status_code)
    if resp.status_code >= 400:
        log(f"OpenCode Go: HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    parsed = _parse_opencode_go_html(resp.text)
    if parsed is None:
        log("OpenCode Go: no usage data found in dashboard")
        return None

    return build_opencode_go_payload(parsed, now=time.time())


def _select_named_usage_source(provider: str) -> tuple[str | None, str | None]:
    """Return (provider_id, error) for a named provider.

    Uses ``PluginRunner`` to check if the plugin exists on disk.
    No credential checking here — the plugin handles that internally.
    """
    try:
        from daemon.plugin_runner import PluginRunner
        runner = PluginRunner(Path(__file__).resolve().parent / "plugins")
        if runner.has_plugin(provider):
            return provider, None
    except Exception:
        pass

    return None, f"Provider unavailable: {provider}"


def _select_usage_source(*, now: float | None = None) -> tuple[str | None, str | None]:
    """Return (provider_id, error) based on user preference or auto-probe.

    Auto-probe: return the first available plugin.
    """
    pref = _provider_preference()

    if pref != PROVIDER_AUTO:
        return pref, None if pref != PROVIDER_AUTO else (None, "Provider unavailable")

    for provider in auto_provider_ids():
        source, _error = _select_named_usage_source(provider)
        if source is not None:
            return source, None
    return None, "No usage source found"


def _payload_for_wire(payload: dict) -> dict:
    """Shrink modern payloads to the BLE-friendly flat form when aliases exist.

    Windows WinRT writes to the ESP32's RX characteristic can reject larger JSON
    payloads even though the semantic data is valid. The firmware still accepts
    the compact flat shape, so prefer it on the wire when possible.
    """
    alias_keys = ("s", "sr", "w", "wr", "st", "ok")
    if not all(key in payload for key in alias_keys):
        return payload

    wire = {
        "s": payload["s"],
        "sr": payload["sr"],
        "w": payload["w"],
        "wr": payload["wr"],
        "st": payload["st"],
        "ok": payload["ok"],
    }
    provider = payload.get("p")
    if isinstance(provider, str) and provider:
        wire["p"] = provider
    return wire


async def scan_for_device():
    """Scan for DEVICE_NAME and return the BLEDevice, or None."""
    log(f"Scanning for '{DEVICE_NAME}' ({SCAN_TIMEOUT}s)...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=SCAN_TIMEOUT)
    if device:
        log(f"Found: {device.address}")
    return device  # BLEDevice or None — NOT an address string


async def discover_target() -> tuple[object | None, str]:
    """Pick the next connect target: env override, cached address, then active scan."""
    override = _ble_address_override()
    if override:
        log(f"Using {BLE_ADDRESS_ENV} override: {override}")
        return override, "override"

    cached = load_cached_address()
    if cached:
        log(f"Trying cached device address: {cached}")
        return cached, "cache"

    return await scan_for_device(), "scan"


class Session:
    def __init__(self, client: BleakClient) -> None:
        self.client = client
        self.refresh_requested = asyncio.Event()
        # Pet animation: background task cycles through frames at hold_ms intervals
        self._pet_anim_task: asyncio.Task | None = None
        self._pet_anim_running = False
        # Current slug/state/hold for screen-driven pet switching
        self._pet_slug: str | None = None
        self._pet_state: str = "idle"
        self._pet_hold_ms: int = 200

    # Map device screen names → pet state names
    _SCREEN_TO_PET_STATE = {
        "splash": "jumping",
        "usage": "review",
    }

    def _on_refresh(self, _char, _data: bytearray) -> None:
        log("Refresh requested by device")
        self.refresh_requested.set()

    def _on_screen_change(self, _char, data: bytearray) -> None:
        """Called when device sends a screen state notification via tx_char."""
        try:
            msg = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        screen = msg.get("sc")
        if not screen or not self._pet_slug:
            return
        pet_state = self._SCREEN_TO_PET_STATE.get(screen, "idle")
        if pet_state == self._pet_state:
            return  # already showing this state
        log(f"Screen -> {screen}, pet state -> {pet_state}")
        self._pet_state = pet_state
        hold = 150 if pet_state == "review" else 200 if pet_state == "idle" else 120
        asyncio.ensure_future(
            self.send_pet_animation(self._pet_slug, pet_state, hold)
        )

    async def setup_refresh_subscription(self) -> None:
        # The refresh subscription is optional — the 60s poll loop works without it.
        # WinRT's start_notify() CCCD write can raise a raw OSError/WinError (not
        # wrapped as BleakError) when the peer GATT server is transiently unavailable,
        # e.g. a just-power-cycled ESP32 whose server is not yet ready (G-03-01, SC#3).
        # Degrade gracefully instead of crashing the daemon so it stays single-process
        # across a power-cycle reconnect (SC#4, no restart).
        try:
            await self.client.start_notify(REQ_CHAR_UUID, self._on_refresh)
        except (BleakError, ValueError, OSError) as e:
            log(f"Refresh subscription unavailable: {e}")
        # Subscribe to screen-change notifications from the device
        try:
            await self.client.start_notify(TX_CHAR_UUID, self._on_screen_change)
        except (BleakError, ValueError, OSError) as e:
            log(f"Screen subscription unavailable: {e}")

    async def write_payload(self, payload: dict) -> bool:
        wire_payload = _payload_for_wire(payload)
        data = json.dumps(wire_payload, separators=(",", ":")).encode()
        log(f"Sending: {data.decode()}")
        try:
            await self.client.write_gatt_char(RX_CHAR_UUID, data, response=True)
            return True
        except (BleakError, OSError) as e:
            # WinRT can raise a raw OSError/WinError (NOT wrapped as BleakError)
            # when the peer GATT server goes transiently unavailable mid-write —
            # the same failure class setup_refresh_subscription() guards against.
            # Returning False trips the zombie-link break -> clean reconnect,
            # rather than an uncaught exception killing the daemon thread (the
            # silent-freeze failure mode, SC#2 field report).
            log(f"Write failed: {e}")
            return False

    async def send_pet_animation(self, slug: str, state: str = "idle",
                                  hold_ms: int = 200) -> bool:
        # Empty slug means "clear pet" (Stop Pet menu)
        if not slug:
            await self._stop_pet_anim()
            if self.client and self.client.is_connected:
                try:
                    await self.client.write_gatt_char(
                        PET_ANIM_CHAR_UUID, b"", response=True
                    )
                    log("Petdex: cleared")
                    return True
                except Exception as e:
                    log(f"Petdex: clear failed: {e}")
                    return False
            return False

        # Stop any running animation task (pet or state changed)
        await self._stop_pet_anim()

        # Get total frame count
        total = _pet_engine.get_frame_count(slug, state)
        if total == 0:
            log(f"Petdex: no frames for {slug}/{state}")
            return False

        log(f"Petdex: starting animation for {slug}/{state} ({total} frames, hold={hold_ms}ms)")

        # Save current pet info so screen-change callback can use it
        self._pet_slug = slug
        self._pet_state = state
        self._pet_hold_ms = hold_ms

        # Start background animation task
        self._pet_anim_running = True
        self._pet_anim_task = asyncio.create_task(
            self._pet_anim_runner(slug, state, hold_ms, total)
        )
        return True

    async def _pet_anim_runner(self, slug: str, state: str,
                                hold_ms: int, total_frames: int) -> None:
        """Background task: cycle through pet frames at hold_ms intervals."""
        try:
            frame = 0
            retries = 0
            max_retries = 3
            while self._pet_anim_running and self.client and self.client.is_connected:
                payload = _pet_engine.get_frame_payload(
                    slug, state, hold_ms, frame, total_frames
                )
                if payload:
                    try:
                        async with asyncio.timeout(5.0):
                            await self.client.write_gatt_char(
                                PET_ANIM_CHAR_UUID, payload, response=True
                            )
                        retries = 0  # success — reset retry counter
                    except (BleakError, OSError, asyncio.TimeoutError) as e:
                        retries += 1
                        if retries >= max_retries:
                            log(f"Petdex: anim write failed after {retries} retries ({type(e).__name__}): {e}")
                            break  # Stop — main loop watchdog restarts
                        await asyncio.sleep(0.2 * retries)  # 200ms, 400ms, 600ms backoff
                        continue  # retry same frame without advancing

                frame = (frame + 1) % total_frames
                await asyncio.sleep(hold_ms / 1000.0)
        except asyncio.CancelledError:
            pass
        finally:
            self._pet_anim_running = False
            log("Petdex: animation stopped")

    async def _stop_pet_anim(self) -> None:
        """Cancel the background animation task if running."""
        self._pet_anim_running = False
        if self._pet_anim_task:
            self._pet_anim_task.cancel()
            try:
                await self._pet_anim_task
            except (asyncio.CancelledError, Exception):
                pass
            self._pet_anim_task = None


def _extract_access_token(blob: str) -> str | None:
    """Pull the accessToken out of a credentials blob.

    Claude Code stores credentials as a JSON object; the blob may also be
    nested ({"claudeAiOauth": {"accessToken": "..."}}). Fall back to a
    regex match so unexpected shapes still work, and finally treat the
    blob as a raw token if nothing else matches.
    """
    blob = blob.strip()
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        # direct: {"accessToken": "..."}
        tok = data.get("accessToken")
        if isinstance(tok, str) and tok.strip():
            return tok
        # nested: {"claudeAiOauth": {"accessToken": "..."}}
        for v in data.values():
            if isinstance(v, dict):
                tok = v.get("accessToken")
                if isinstance(tok, str) and tok.strip():
                    return tok
    m = re.search(r'"accessToken"\s*:\s*"([^"]+)"', blob)
    if m:
        return m.group(1)
    # Raw token (no JSON wrapper) — must look plausible (sk-ant-... etc.)
    if re.fullmatch(r"[A-Za-z0-9_\-.~+/=]{20,}", blob):
        return blob
    return None


def _windows_credential_candidates() -> list[Path]:
    """Return the ordered list of credential file paths to probe (first hit wins).

    Priority:
    1. CLAUDE_CREDENTIALS_PATH env override (D-03, project-specific)
    2. CLAUDE_CONFIG_DIR env override (official Claude override)
    3. D-02 candidate list: home/.claude, LOCALAPPDATA/Claude, APPDATA/Claude
    """
    # Priority 1: project-specific env override (D-03)
    if override := os.environ.get("CLAUDE_CREDENTIALS_PATH"):
        return [Path(override)]
    # Priority 2: official CLAUDE_CONFIG_DIR env override
    if config_dir := os.environ.get("CLAUDE_CONFIG_DIR"):
        return [Path(config_dir) / ".credentials.json"]
    # Priority 3: D-02 candidate list — first hit wins
    home = Path.home()
    local_appdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    return [
        home / ".claude" / ".credentials.json",          # primary (confirmed by docs)
        local_appdata / "Claude" / ".credentials.json",  # fallback 2
        appdata / "Claude" / ".credentials.json",        # fallback 3
    ]


def read_token() -> str | None:
    """Read the Claude OAuth access token from the first available credential file."""
    for path in _windows_credential_candidates():
        try:
            return _extract_access_token(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return None


def _read_expiry() -> str:
    """Return human-readable expiry from the first-hit credentials file.

    Reads claudeAiOauth.expiresAt (epoch milliseconds — JS convention).
    Divides by 1000 before passing to fromtimestamp (Python expects seconds).
    Returns 'expiry unknown' on any parse failure.
    """
    for path in _windows_credential_candidates():
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            data = json.loads(raw)
            oauth = data.get("claudeAiOauth", {})
            expires_ms = oauth.get("expiresAt")
            if expires_ms is None:
                return "expiry unknown"
            # CRITICAL: expiresAt is JS-convention epoch milliseconds; divide by 1000
            # before fromtimestamp (Python expects seconds). Raw value -> year ~57000.
            dt = datetime.datetime.fromtimestamp(
                expires_ms / 1000, tz=datetime.timezone.utc
            )
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except (TypeError, ValueError, OSError, AttributeError, json.JSONDecodeError):
            return "expiry unknown"
    return "expiry unknown"


async def _wait_first(*events: asyncio.Event, timeout: float) -> None:
    """Return when any of `events` is set, or after `timeout` seconds.

    Lets the poll loop's TICK wait wake immediately on a stop signal (clean,
    responsive Quit) without losing the refresh-request wakeup — instead of
    waiting only on refresh_requested and re-checking stop_event up to TICK
    later. Cancels and drains the loser tasks so they don't warn.
    """
    tasks = [asyncio.ensure_future(e.wait()) for e in events]
    try:
        await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def connect_and_run(device, stop_event: asyncio.Event, tray_state=None) -> bool:
    """Connect to device and poll until disconnected or stopped.

    Returns True if at least one successful write occurred.
    """
    display = device if isinstance(device, str) else device.address
    log(f"Connecting to {display}...")
    # D-01: retry wrapper — defeats WinRT post-wake failure modes
    # (Could not get GATT services: Unreachable, stale is_connected).
    # Rebuild a fresh BleakClient each attempt (locked D-05 recipe).
    client = None
    for attempt in range(CONNECT_RETRIES):
        # D-05: pass BLEDevice (not address string), address_type="random" (NimBLE
        # static-random), use_cached_services=False (DIY firmware — WinRT GATT cache
        # may be stale after firmware reflash).
        client = BleakClient(
            device,
            address_type="random",
            use_cached_services=False,
        )
        try:
            await client.connect()
        except (BleakError, asyncio.TimeoutError) as e:
            log(f"Connection attempt {attempt + 1}/{CONNECT_RETRIES} failed: {e}")
            try:
                await client.disconnect()
            except BleakError:
                pass
            if attempt < CONNECT_RETRIES - 1:
                await asyncio.sleep(CONNECT_RETRY_DELAY)
            continue

        if not client.is_connected:
            log(f"Connection attempt {attempt + 1}/{CONNECT_RETRIES} failed (not connected)")
            try:
                await client.disconnect()
            except BleakError:
                pass
            if attempt < CONNECT_RETRIES - 1:
                await asyncio.sleep(CONNECT_RETRY_DELAY)
            continue

        # Connected successfully
        break
    else:
        log(f"Connection failed after {CONNECT_RETRIES} attempts")
        return False

    log("Connected")
    session = Session(client)
    await session.setup_refresh_subscription()

    # Health check: verify GATT services are actually accessible (WinRT can report
    # is_connected=True while the link is half-open). Read a characteristic to
    # confirm the GATT server is ready before entering the main loop.
    try:
        async with asyncio.timeout(3.0):
            # Try reading the TX char — if service discovery never completed or
            # the GATT server rejected us, this raises BleakError immediately.
            await client.read_gatt_char(TX_CHAR_UUID)
    except (BleakError, OSError, asyncio.TimeoutError) as e:
        log(f"GATT health check failed: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        return False
    log("GATT health check passed")

    refresh_callback = session.refresh_requested.set
    if tray_state is not None:
        tray_state.refresh_callback = refresh_callback
        tray_state.daemon_send_pet = session.send_pet_animation

    last_poll = 0.0  # D-03: poll immediately on first connect
    used_successfully = False
    consecutive_failures = 0  # D-03: zombie-link break counter
    last_pet_send: float | None = None  # pet animation refresh timer
    try:
        while client.is_connected and not stop_event.is_set():
            now = time.time()
            elapsed = now - last_poll
            if session.refresh_requested.is_set() or elapsed >= POLL_INTERVAL:
                session.refresh_requested.clear()
                source, source_error = _select_usage_source(now=now)
                if not source:
                    log(f"{source_error}; skipping poll")
                    if tray_state and source_error:
                        tray_state.set_error(source_error)
                else:
                    # Use PluginRunner to invoke the provider plugin
                    runner = PluginRunner(Path(__file__).resolve().parent / "plugins")
                    last_err = None
                    try:
                        resp = await runner.run(
                            source,
                            prev_payload=None,
                            last_error=last_err,
                        )
                        if resp.ok and resp.payload:
                            payload = resp.payload
                        else:
                            payload = None
                            last_err = resp.error
                            if not resp.retry:
                                # Permanent failure — show toast
                                log(f"{resp.error}; notifying user")
                                if tray_state and resp.error:
                                    tray_state.set_error(resp.error)
                            else:
                                log(f"{resp.error}; will retry")
                    except (PluginNotFoundError, PluginCrashedError) as e:
                        log(f"Plugin {source} error: {e}")
                        payload = None
                        if tray_state:
                            tray_state.set_error(str(e))

                    if payload is not None:
                        write_ok = False
                        for wretry in range(3):
                            if await session.write_payload(payload):
                                write_ok = True
                                break
                            log(f"Retrying payload write ({wretry+1}/3)...")
                            await asyncio.sleep(0.5 * (wretry + 1))
                        if write_ok:
                            last_poll = time.time()
                            used_successfully = True
                            consecutive_failures = 0  # D-03: reset on success
                            if tray_state:
                                tray_state.set_connected(time.time())
                        else:
                            consecutive_failures += 1
                            if consecutive_failures >= ZOMBIE_BREAK_LIMIT:
                                log(
                                    f"Zombie link detected ({consecutive_failures} consecutive"
                                    f" write failures); abandoning connection"
                                )
                                break
                    # else: payload is None from a TRANSIENT failure (network/DNS,
                    # timeout, rate-limit, 5xx). poll_api already logged it; do NOT
                    # toast "token expired" — that mislabeled a boot-time DNS blip
                    # as an auth problem (SC#5). Leave tray state unchanged; the next
                    # tick retries and set_connected() recovers it.

            # ── Pet animation watchdog ───────────────────────────────────────
            # The background animation task (started by send_pet_animation)
            # continuously cycles through frames. If it has died (e.g. BLE write
            # failure), restart it here. The 5-second tick is coarse, but the
            # animation task itself runs at hold_ms intervals.
            if _pet_active_slug is not None and session is not None:
                if not session._pet_anim_running:
                    slug = session._pet_slug or _pet_active_slug
                    state = session._pet_state or _pet_active_state
                    hold = session._pet_hold_ms or 200
                    log(f"Petdex: animation task dead, restarting {slug}/{state}")
                    asyncio.ensure_future(
                        session.send_pet_animation(slug, state, hold)
                    )

            # Wake on a refresh request OR a stop, whichever comes first.
            # promptly on stop_event is what lets the finally below run
            # client.disconnect() before the process exits, so the peer gets a
            # clean GATT disconnect (returns to its waiting screen) instead of
            # being left frozen on stale data after Quit (SC#3 graceful shutdown).
            await _wait_first(session.refresh_requested, stop_event, timeout=TICK)
    finally:
        if tray_state is not None and tray_state.refresh_callback is refresh_callback:
            tray_state.refresh_callback = None
            tray_state.daemon_send_pet = None
        # Clean GATT disconnect on the way out — this is what tells the peripheral
        # the link is gone. WinRT can surface a raw OSError (not BleakError) here,
        # so swallow both; the link tears down regardless once we exit.
        try:
            await client.disconnect()
        except (BleakError, OSError):
            pass

    log("Device disconnected" if not stop_event.is_set() else "Stopping")
    return used_successfully


def _next_backoff(current: int, cap: int) -> int:
    """D-05: double current backoff value, clamped to cap.

    Pure helper — unit-testable without driving the main loop.
    Used by both slow-search (cap=60) and fast-reconnect (cap=RECONNECT_BACKOFF_CAP) regimes.
    """
    return min(current * 2, cap)


async def main(tray_state=None) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    # Populate the shared state object so the tray can route Quit through
    # loop.call_soon_threadsafe (RESEARCH Pitfall 2).  Additive — the existing
    # stop_event = asyncio.Event() line above is unchanged.
    if tray_state is not None:
        tray_state.loop = loop
        tray_state.stop_event = stop_event

    def _stop(*_args: object) -> None:
        log("Daemon stopping")
        stop_event.set()

    # OS signal handlers can only be installed from the main thread, and
    # loop.add_signal_handler is unsupported on Windows. When running under the
    # tray (04-03) the loop lives in a background thread and the tray owns clean
    # shutdown via stop_event (loop.call_soon_threadsafe), so skip silently there.
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _stop)
            except NotImplementedError:
                # Windows: add_signal_handler not supported; fall back to signal.signal
                try:
                    signal.signal(sig, _stop)
                except ValueError:
                    # Not the main thread of the main interpreter — tray owns shutdown.
                    pass

    log("=== Clawdmeter Usage Daemon (BLE, Windows) ===")
    log(f"Poll interval: {POLL_INTERVAL}s")

    # D-05: two distinct backoff regimes — slow-search (device absent) vs fast-reconnect (link dropped)
    search_backoff = 1     # caps at 60s — gentle, for a device that is genuinely absent/off
    reconnect_backoff = 1  # caps at RECONNECT_BACKOFF_CAP — fast, to clear the 120s SLA after a drop
    while not stop_event.is_set():
        target, source = await discover_target()
        if not target:
            # Slow-search regime: device was not found by scan — back off gently
            if tray_state:
                tray_state.set_scanning()
            log(f"Device not found, retrying in {search_backoff}s...")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=search_backoff)
            except asyncio.TimeoutError:
                pass
            search_backoff = _next_backoff(search_backoff, 60)
            continue

        ok = await connect_and_run(target, stop_event, tray_state)
        connected_target = target

        if not ok and source == "cache":
            clear_cached_address()
            log("Cached device address failed; falling back to active scan")
            scanned = await scan_for_device()
            if scanned is not None:
                ok = await connect_and_run(scanned, stop_event, tray_state)
                connected_target = scanned

        if not ok:
            # Fast-reconnect regime: had/attempted a link that dropped — retry quickly
            if tray_state:
                tray_state.set_scanning()
            log(f"Connection lost, reconnecting in {reconnect_backoff}s...")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=reconnect_backoff)
            except asyncio.TimeoutError:
                pass
            reconnect_backoff = _next_backoff(reconnect_backoff, RECONNECT_BACKOFF_CAP)
        else:
            if source != "override":
                addr = connected_target if isinstance(connected_target, str) else connected_target.address
                save_cached_address(addr)
            # Successful session — reset reconnect counter to floor; search_backoff also reset
            reconnect_backoff = 1
            search_backoff = 1


if __name__ == "__main__":
    if sys.platform != "win32":
        print(
            "Warning: running under Linux/WSL — WinRT BLE will not be available.",
            file=sys.stderr,
        )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
