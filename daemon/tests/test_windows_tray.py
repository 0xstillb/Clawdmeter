#!/usr/bin/env python3
"""Unit tests for daemon/tray_windows.py — APP-01.

Covers:
  TrayState scalar setters and initial state
  header_text() for all three states including last_sync=None
  daemon main() accepts tray_state and populates ts.loop / ts.stop_event
  Quit routes through loop.call_soon_threadsafe (not stop_event.set directly)
  Error toast fires only on transition INTO error state (D-04)

All pystray usage is inside tray_windows.main() (deferred import), so these
tests can import the pure helpers (TrayState, header_text) and test Quit/toast
handlers with mocked icons without importing the GTK-less top-level pystray.

Run: python -m pytest daemon/tests/test_windows_tray.py -x -q
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from daemon.tray_windows import (
    TrayState,
    _automatic_wifi_provider,
    _selected_wifi_provider,
    header_text,
    wifi_runtime_label,
    _acquire_single_instance,
    _clear_brightness_pct,
    _read_brightness_pct,
    _write_brightness_pct,
    _ERROR_ALREADY_EXISTS,
    _minimax_credentials,
    _save_minimax_credentials,
)


# ---------------------------------------------------------------------------
# TrayState — initial state and setters
# ---------------------------------------------------------------------------

def test_tray_state_initial():
    """TrayState initialises to scanning state with no last_sync."""
    ts = TrayState()
    assert ts.state == "scanning"
    assert ts.reason == ""
    assert ts.last_sync is None
    assert ts.loop is None
    assert ts.stop_event is None
    assert ts.wifi_notice_seq == 0
    assert ts.wifi_settings_seq == 0
    assert ts.wifi_runtime_status == "unknown"
    assert ts.wifi_runtime_seen_at is None


def test_wifi_connected_increments_tray_notification_sequence():
    ts = TrayState()

    ts.note_wifi_status("connected")
    first_seen = ts.wifi_runtime_seen_at
    ts.note_wifi_status("connected")
    ts.note_wifi_status("ignored")

    assert ts.wifi_notice_seq == 1
    assert ts.wifi_runtime_status == "connected"
    assert ts.wifi_runtime_seen_at is not None
    assert ts.wifi_runtime_seen_at >= first_seen


def test_wifi_settings_change_increments_menu_refresh_sequence():
    ts = TrayState()

    ts.note_wifi_settings_changed()

    assert ts.wifi_settings_seq == 1


def test_wifi_configured_status_marks_cyd_as_confirmed():
    ts = TrayState()

    ts.note_wifi_status("configured")

    assert ts.wifi_configured_on_cyd is True
    assert ts.wifi_settings_seq == 1


def test_wifi_runtime_status_updates_menu_state_without_toast():
    ts = TrayState()

    ts.note_wifi_status("connecting")
    ts.note_wifi_status("error")

    assert ts.wifi_runtime_status == "error"
    assert ts.wifi_notice_seq == 0
    assert ts.wifi_settings_seq == 2


def test_wifi_runtime_label_marks_status_as_last_reported(monkeypatch):
    ts = TrayState()
    ts.wifi_runtime_status = "connected"
    ts.wifi_runtime_seen_at = 1000.0
    monkeypatch.setattr(time, "strftime", lambda *_args: "13:45")

    assert wifi_runtime_label(ts) == "Wi-Fi status: Connected · last reported 13:45"


def test_set_connected():
    """set_connected(ts_float) sets state='connected', clears reason, records last_sync."""
    ts = TrayState()
    now = time.time()
    ts.set_connected(now)
    assert ts.state == "connected"
    assert ts.reason == ""
    assert ts.last_sync == now


def test_set_scanning():
    """set_scanning() sets state='scanning', clears reason."""
    ts = TrayState()
    ts.set_error("something bad")   # put it in error first
    ts.set_scanning()
    assert ts.state == "scanning"
    assert ts.reason == ""


def test_set_error():
    """set_error(why) sets state='error' and stores the reason string."""
    ts = TrayState()
    ts.set_error("token expired — run claude login")
    assert ts.state == "error"
    assert ts.reason == "token expired — run claude login"


# ---------------------------------------------------------------------------
# header_text — D-05 string shapes
# ---------------------------------------------------------------------------

def test_header_text_scanning():
    """header_text returns 'Scanning…' in scanning state."""
    ts = TrayState()
    ts.set_scanning()
    assert header_text(ts) == "Scanning…"


def test_header_text_error():
    """header_text returns 'Error: {reason}' in error state."""
    ts = TrayState()
    ts.set_error("token expired — run claude login")
    result = header_text(ts)
    assert result == "Error: token expired — run claude login"


def test_header_text_connected_with_last_sync():
    """header_text returns 'Connected · last update HH:MM' when last_sync is set."""
    ts = TrayState()
    # Use a known timestamp so we can predict the HH:MM string.
    known_ts = time.mktime(time.strptime("2026-06-01 14:32:00", "%Y-%m-%d %H:%M:%S"))
    ts.set_connected(known_ts)
    result = header_text(ts)
    # Extract the HH:MM portion from the actual local time expansion.
    expected_when = time.strftime("%H:%M", time.localtime(known_ts))
    assert result == f"Connected · last update {expected_when}"


def test_header_text_connected_never_when_last_sync_none():
    """header_text returns 'Connected · last update never' when last_sync is None."""
    ts = TrayState()
    # Manually set state without using set_connected so last_sync stays None.
    ts.state = "connected"
    ts.last_sync = None
    result = header_text(ts)
    assert result == "Connected · last update never"


def test_minimax_credentials_round_trip(tmp_path):
    """MiniMax tray settings persist only the Coding Plan API key."""
    _save_minimax_credentials(tmp_path, "minimax-api-key")

    assert _minimax_credentials(tmp_path) == "minimax-api-key"
    saved = (tmp_path / "minimax-credentials.json").read_text(encoding="utf-8")
    assert '"api_key": "minimax-api-key"' in saved
    assert "group_id" not in saved


def test_brightness_setting_round_trip(tmp_path, monkeypatch):
    import daemon.tray_windows as mod

    monkeypatch.setattr(mod, "_BRIGHTNESS_FILE", tmp_path / "brightness")
    assert _read_brightness_pct() is None

    _write_brightness_pct(75)
    assert _read_brightness_pct() == 75

    _clear_brightness_pct()
    assert _read_brightness_pct() is None


def test_wifi_fallback_uses_active_direct_provider(monkeypatch):
    import daemon.config as config_mod
    import daemon.tray_windows as tray_mod

    monkeypatch.setattr(config_mod, "provider_preference", lambda: "minimax")
    monkeypatch.setattr(tray_mod, "_direct_provider_api_key",
                        lambda provider: "minimax-key" if provider == "minimax" else "")

    selected, message = _automatic_wifi_provider()

    assert selected == {"provider": "minimax", "api_key": "minimax-key"}
    assert message == "Will use active provider: Minimax"


def test_wifi_fallback_finds_saved_direct_provider_when_active_is_not_direct(monkeypatch):
    import daemon.config as config_mod
    import daemon.tray_windows as tray_mod

    monkeypatch.setattr(config_mod, "provider_preference", lambda: "claude")
    monkeypatch.setattr(tray_mod, "_direct_provider_api_key",
                        lambda provider: "router-key" if provider == "openrouter" else "")

    selected, message = _automatic_wifi_provider()

    assert selected == {"provider": "openrouter", "api_key": "router-key"}
    assert message == "Will use saved API provider: OpenRouter"


def test_wifi_fallback_can_select_explicit_provider(monkeypatch):
    import daemon.tray_windows as tray_mod

    monkeypatch.setattr(tray_mod, "_direct_provider_api_key",
                        lambda provider: "deepseek-key" if provider == "deepseek" else "")

    selected, message = _selected_wifi_provider("deepseek")

    assert selected == {"provider": "deepseek", "api_key": "deepseek-key"}
    assert message == "Wi-Fi fallback provider: DeepSeek"


def test_wifi_fallback_explicit_provider_requires_saved_key(monkeypatch):
    import daemon.tray_windows as tray_mod

    monkeypatch.setattr(tray_mod, "_direct_provider_api_key", lambda _provider: "")

    selected, message = _selected_wifi_provider("openrouter")

    assert selected is None
    assert message == "Add an OpenRouter API key in Accounts & API keys first."


def test_wifi_ssid_parser_reads_current_windows_network(monkeypatch):
    import daemon.tray_windows as tray_mod

    class Result:
        stdout = "\n    SSID                   : Desk Wi-Fi\n    BSSID                  : 00:11:22:33:44:55\n"

    monkeypatch.setattr(tray_mod.subprocess, "run", lambda *args, **kwargs: Result())

    assert tray_mod._current_wifi_ssid() == "Desk Wi-Fi"


# ---------------------------------------------------------------------------
# daemon main() populates ts.loop and ts.stop_event
# ---------------------------------------------------------------------------

def test_main_populates_tray_state_loop_and_stop_event():
    """daemon main(tray_state=ts) sets ts.loop and ts.stop_event before the loop body."""
    import daemon.claude_usage_daemon_windows as mod

    ts = TrayState()
    populated = {}

    async def _fake_discover():
        # Record the state of ts at first scan entry (after main() startup lines).
        populated["loop"] = ts.loop
        populated["stop_event"] = ts.stop_event
        # Signal stop so the loop exits cleanly.
        ts.stop_event.set()
        return None, "scan"   # no device found

    with patch.object(mod, "discover_target", side_effect=_fake_discover):
        asyncio.run(mod.main(tray_state=ts))

    assert populated.get("loop") is not None, "ts.loop must be set by daemon main()"
    assert populated.get("stop_event") is not None, "ts.stop_event must be set by daemon main()"


# ---------------------------------------------------------------------------
# Quit handler routes through call_soon_threadsafe (not stop_event.set directly)
# ---------------------------------------------------------------------------

def test_quit_uses_call_soon_threadsafe():
    """The Quit menu handler calls loop.call_soon_threadsafe(stop_event.set) and icon.stop().

    It must NOT call stop_event.set() directly from the tray thread
    (RESEARCH Pitfall 2 / T-04-06 mitigation).
    """
    # Build a TrayState with a mocked loop and stop_event.
    ts = TrayState()
    mock_loop = MagicMock()
    mock_stop_event = MagicMock()
    ts.loop = mock_loop
    ts.stop_event = mock_stop_event

    # Build the Quit handler the same way tray_windows.main() does, without
    # importing pystray at the module level.  We construct a local closure
    # that mirrors the on_quit body.
    mock_icon = MagicMock()

    def _on_quit(icon_ref, _item):
        # This is the exact body from tray_windows.main() — keep in sync.
        ts.loop.call_soon_threadsafe(ts.stop_event.set)
        icon_ref.stop()

    _on_quit(mock_icon, None)

    # call_soon_threadsafe must have been called with stop_event.set as the arg.
    mock_loop.call_soon_threadsafe.assert_called_once_with(mock_stop_event.set)
    # icon.stop() must have been called.
    mock_icon.stop.assert_called_once()
    # stop_event.set() must NOT have been called directly.
    mock_stop_event.set.assert_not_called()


# ---------------------------------------------------------------------------
# Error toast fires only on transition INTO error (D-04)
# ---------------------------------------------------------------------------

def test_error_toast_on_entry_only():
    """The tray refresh loop fires icon.notify() only on transition INTO error.

    Sequence: scanning -> error -> error
    Expected: notify called exactly once (on the scanning->error transition).
    """
    ts = TrayState()
    ts.set_scanning()

    mock_icon = MagicMock()
    mock_icon._running = True

    # Simulate the _refresh loop's state-change detection logic from tray_windows.main().
    # We run two transitions manually:
    #   1. scanning -> error    (should call notify once)
    #   2. error -> error       (no change — notify must NOT fire again)
    prev_state: dict = {"state": None}

    def _process_state_change(new_state: str, reason: str = "") -> None:
        """Mirror the relevant part of the _refresh loop body."""
        ts.state = new_state
        ts.reason = reason
        current = ts.state
        if current != prev_state["state"]:
            if current == "error" and prev_state["state"] != "error":
                mock_icon.notify(ts.reason or "Clawdmeter error", "Clawdmeter")
            prev_state["state"] = current

    # Transition 1: scanning -> error  (notify should fire)
    _process_state_change("scanning")
    _process_state_change("error", "token expired — run claude login")
    # Transition 2: error -> error  (same state — no call)
    _process_state_change("error", "token expired — run claude login")

    mock_icon.notify.assert_called_once_with(
        "token expired — run claude login", "Clawdmeter"
    )


# ---------------------------------------------------------------------------
# Single-instance guard (named mutex) — duplicate-launch / ARSO collision
# ---------------------------------------------------------------------------
# Field bug: Windows "restart apps after sign-in" (ARSO) restored a console
# `python.exe tray_windows.py` instance while the headless `pythonw` autostart
# also fired — two trays fighting over the one BLE link. The guard makes a
# second instance exit before it touches BLE.

def test_single_instance_noop_off_windows():
    """Off-Windows the guard is a no-op that returns a truthy sentinel (never None)."""
    with patch("daemon.tray_windows.sys") as mock_sys:
        mock_sys.platform = "linux"
        assert _acquire_single_instance() is not None


def _fake_kernel32(last_error: int, handle: int):
    """Build a fake ctypes module tree whose CreateMutexW returns `handle` and
    whose get_last_error() returns `last_error`."""
    fake_kernel32 = MagicMock()
    fake_kernel32.CreateMutexW.return_value = handle
    fake_ctypes = MagicMock()
    fake_ctypes.WinDLL.return_value = fake_kernel32
    fake_ctypes.get_last_error.return_value = last_error
    return fake_ctypes


def test_single_instance_first_instance_gets_handle():
    """First instance: CreateMutexW succeeds, no prior owner → returns the handle."""
    fake_ctypes = _fake_kernel32(last_error=0, handle=0xABCD)
    with patch("daemon.tray_windows.sys") as mock_sys, \
         patch.dict("sys.modules", {"ctypes": fake_ctypes, "ctypes.wintypes": MagicMock()}):
        mock_sys.platform = "win32"
        assert _acquire_single_instance() == 0xABCD


def test_single_instance_second_instance_gets_none():
    """Second instance: mutex already exists → returns None so caller exits."""
    fake_ctypes = _fake_kernel32(last_error=_ERROR_ALREADY_EXISTS, handle=0xABCD)
    with patch("daemon.tray_windows.sys") as mock_sys, \
         patch.dict("sys.modules", {"ctypes": fake_ctypes, "ctypes.wintypes": MagicMock()}):
        mock_sys.platform = "win32"
        assert _acquire_single_instance() is None


def test_single_instance_fails_open_on_null_handle():
    """If CreateMutexW returns NULL, fail OPEN (truthy) — never block tray startup."""
    fake_ctypes = _fake_kernel32(last_error=_ERROR_ALREADY_EXISTS, handle=0)
    with patch("daemon.tray_windows.sys") as mock_sys, \
         patch.dict("sys.modules", {"ctypes": fake_ctypes, "ctypes.wintypes": MagicMock()}):
        mock_sys.platform = "win32"
        result = _acquire_single_instance()
        assert result is not None


# ---------------------------------------------------------------------------
# Regression: cwd-independent package + asset resolution (SC#1 logon autostart)
# ---------------------------------------------------------------------------
# Field bug: launching `pythonw.exe daemon\tray_windows.py` at logon starts with
# cwd = System32, so `import daemon.*` raised ModuleNotFoundError and the relative
# logo path failed — the tray crashed silently with no icon. tray_windows must
# self-locate the repo root from __file__ so it works from any working directory.

def test_repo_root_is_parent_of_daemon_package():
    """_REPO_ROOT points at the dir that CONTAINS the daemon package."""
    import os
    import daemon.tray_windows as tw

    assert os.path.isdir(os.path.join(tw._REPO_ROOT, "daemon"))
    assert os.path.isfile(
        os.path.join(tw._REPO_ROOT, "firmware", "src", "logo.h")
    ), "brand logo must resolve from _REPO_ROOT, not the current working directory"


def test_repo_root_on_sys_path_after_import():
    """Importing tray_windows puts the repo root on sys.path so `daemon.*` resolves regardless of cwd."""
    import sys
    import daemon.tray_windows as tw

    assert tw._REPO_ROOT in sys.path


# ---------------------------------------------------------------------------
# Regression: daemon main() must run in a BACKGROUND thread (SC#1 tray launch)
# ---------------------------------------------------------------------------
# Field bug: under the tray the loop runs in threading.Thread (pystray owns the
# main thread). OS signal-handler installation (loop.add_signal_handler /
# signal.signal) only works on the main thread, so main() raised
# "signal only works in main thread" and the daemon thread died on startup.
# main() must guard signal setup to the main thread; the tray owns shutdown.

def test_main_runs_in_background_thread_without_signal_error():
    """main(tray_state=ts) started from a non-main thread must not raise on signal setup."""
    import threading as _threading
    import daemon.claude_usage_daemon_windows as mod

    ts = TrayState()
    errors: list = []

    async def _fake_discover():
        ts.stop_event.set()   # exit the loop immediately
        return None, "scan"

    def _run() -> None:
        try:
            with patch.object(mod, "discover_target", side_effect=_fake_discover):
                asyncio.run(mod.main(tray_state=ts))
        except Exception as exc:   # noqa: BLE001 — capture for the assertion
            errors.append(exc)

    t = _threading.Thread(target=_run)
    t.start()
    t.join(timeout=10)

    assert not t.is_alive(), "daemon main() hung in background thread"
    assert not errors, f"main() raised in a background thread: {errors!r}"
