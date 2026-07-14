#!/usr/bin/env python3
"""Windows system-tray entry and state bridge for Clawdmeter — APP-01.

Provides:
  TrayState   — thread-safe scalar bridge (daemon loop writes, tray reads)
  header_text — pure helper producing the D-05 status-header string
  main()      — tray entry: builds per-state icons, runs the daemon loop in a
                bg thread, and runs pystray.Icon on the main thread

The daemon loop (claude_usage_daemon_windows.main) is UNCHANGED in logic;
this module injects only additive state-setter calls at existing branch points.

Usage::

    python tray_windows.py

Run: python -m pytest daemon/tests/test_windows_tray.py -x -q
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path

# Repo root = the directory that CONTAINS the `daemon` package (this file is
# <repo>/daemon/tray_windows.py). Resolve it from __file__ so the package
# imports below and the brand-logo asset load work no matter what the current
# working directory is — critical for logon autostart, where the HKCU\Run entry
# starts with cwd = System32, not the repo (APP-01 / SC#1).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from daemon.wifi_fallback_config import (
    load_wifi_config,
    mark_wifi_config_synced,
    save_wifi_config,
    wifi_settings_label,
)

# Autostart launches us with the BASE interpreter's pythonw.exe, not the venv's
# (see autostart_windows._command — the venv pythonw redirector pops a console
# window). The base interpreter does NOT see the venv's site-packages, so add
# them here to resolve pystray/bleak/PIL. os.path.isdir guards the no-venv and
# already-inside-venv cases; site.addsitedir is a no-op on a missing dir anyway.
_VENV_SITE = os.path.join(_REPO_ROOT, ".venv", "Lib", "site-packages")
if os.path.isdir(_VENV_SITE):
    import site
    site.addsitedir(_VENV_SITE)

# ---------------------------------------------------------------------------
# TrayState — thread-safe scalar bridge (loop -> tray)
# ---------------------------------------------------------------------------

class TrayState:
    """Shared state object bridging the daemon asyncio loop to the tray.

    The daemon loop writes state via the set_* methods; the tray reads the
    scalar attributes.  No lock is needed — writes are atomic attribute
    assignments of simple Python scalars, and the tray only ever reads them.

    The loop populates `loop` and `stop_event` at startup (inside
    daemon_main()) so the tray's Quit handler can route through
    loop.call_soon_threadsafe (RESEARCH Pitfall 2 / Anti-Pattern).
    """

    def __init__(self) -> None:
        self.state: str = "scanning"       # "connected" | "scanning" | "error"
        self.reason: str = ""              # error reason string (D-04)
        self.last_sync: float | None = None  # time.time() of last successful write

        # Populated by daemon main() at startup:
        self.loop = None        # asyncio running loop (for call_soon_threadsafe)
        self.stop_event = None  # asyncio.Event (the existing clean-shutdown hook)
        self.refresh_callback = None  # callable that pokes the active session poll loop
        self.daemon_send_pet = None   # async callable (slug, state, hold_ms) -> bool
        self.daemon_send_wifi = None  # async callable (Wi-Fi config) -> bool
        self.wifi_notice_seq = 0
        self.wifi_settings_seq = 0
        self.wifi_configured_on_cyd = False
        self.wifi_runtime_status = "unknown"
        self.wifi_runtime_seen_at: float | None = None

    def set_connected(self, ts: float) -> None:
        """Called after write_payload returns True.  ts = time.time()."""
        self.state = "connected"
        self.reason = ""
        self.last_sync = ts

    def set_scanning(self) -> None:
        """Called in scan/reconnect branches.  BLE churn stays Scanning (D-01)."""
        self.state = "scanning"
        self.reason = ""

    def set_error(self, why: str) -> None:
        """Called on token-expired / API auth failure (D-01 Error = actionable only)."""
        self.state = "error"
        self.reason = why

    def request_refresh(self) -> bool:
        """Ask the active daemon session to poll immediately, if connected."""
        if self.loop is None or self.refresh_callback is None:
            return False
        try:
            self.loop.call_soon_threadsafe(self.refresh_callback)
        except RuntimeError:
            return False
        return True

    def sync_wifi_config(self, config: dict[str, str]) -> bool:
        """Queue a saved Wi-Fi fallback configuration on the active BLE session."""
        if self.loop is None or self.daemon_send_wifi is None:
            return False

        async def _send() -> bool:
            if not await self.daemon_send_wifi(config):
                return False
            mark_wifi_config_synced(config)
            return True

        try:
            future = asyncio.run_coroutine_threadsafe(_send(), self.loop)
        except RuntimeError:
            return False

        def _finished(result) -> None:
            try:
                if not result.result():
                    self.set_error("Wi-Fi settings are waiting for CYD")
            except Exception:
                self.set_error("Wi-Fi settings are waiting for CYD")
            finally:
                self.wifi_settings_seq += 1

        future.add_done_callback(_finished)
        return True

    def note_wifi_status(self, status: str) -> None:
        if status == "configured":
            self.wifi_configured_on_cyd = True
            self.wifi_settings_seq += 1
            return

        runtime_states = {"not_configured", "standby", "connecting", "connected", "error"}
        if status not in runtime_states:
            return
        previous = self.wifi_runtime_status
        self.wifi_runtime_status = status
        self.wifi_runtime_seen_at = time.time()
        self.wifi_settings_seq += 1
        if status == "connected" and previous != "connected":
            self.wifi_notice_seq += 1

    def note_wifi_settings_changed(self) -> None:
        """Refresh the device submenu after a pending/synced state change."""
        self.wifi_settings_seq += 1


# ---------------------------------------------------------------------------
# header_text — pure D-05 status header string
# ---------------------------------------------------------------------------

def header_text(ts: TrayState) -> str:
    """Return the D-05 menu status-header string for the current TrayState.

    Shapes:
      "Connected · last update HH:MM"  (ts.last_sync is a float)
      "Connected · last update never"  (ts.last_sync is None)
      "Scanning…"
      "Error: {reason}"
    """
    if ts.state == "connected":
        if ts.last_sync is not None:
            when = time.strftime("%H:%M", time.localtime(ts.last_sync))
        else:
            when = "never"
        return f"Connected · last update {when}"
    if ts.state == "scanning":
        return "Scanning…"   # "Scanning…"
    return f"Error: {ts.reason}"


def wifi_runtime_label(ts: TrayState) -> str:
    """Human-readable last Wi-Fi state reported by CYD over BLE."""
    labels = {
        "not_configured": "Not configured",
        "standby": "Standby (BLE preferred)",
        "connecting": "Connecting…",
        "connected": "Connected",
        "error": "Connection error",
        "unknown": "Unknown",
    }
    label = labels.get(ts.wifi_runtime_status, "Unknown")
    if ts.wifi_runtime_seen_at is None:
        return f"Wi-Fi status: {label}"
    when = time.strftime("%H:%M", time.localtime(ts.wifi_runtime_seen_at))
    return f"Wi-Fi status: {label} · last reported {when}"


def tray_title_text(ts: TrayState, max_len: int = 128) -> str:
    """Return a Windows-safe tray tooltip/title string.

    pystray's Win32 backend rejects titles longer than 128 chars.
    """
    text = header_text(ts)
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1] + "…"


# ── Display brightness ───────────────────────────────────────────────────

_BRIGHTNESS_PRESETS = (15, 30, 50, 75, 100)
_BRIGHTNESS_FILE = (
    Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    / "clawdmeter"
    / "brightness"
)


def _read_brightness_pct() -> int | None:
    try:
        raw = _BRIGHTNESS_FILE.read_text(encoding="utf-8").strip()
        if raw:
            return max(0, min(100, int(raw)))
    except (OSError, ValueError):
        pass
    return None


def _write_brightness_pct(pct: int) -> None:
    pct = max(0, min(100, int(pct)))
    _BRIGHTNESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _BRIGHTNESS_FILE.write_text(f"{pct}\n", encoding="utf-8")


def _clear_brightness_pct() -> None:
    try:
        _BRIGHTNESS_FILE.unlink()
    except FileNotFoundError:
        pass


def _show_brightness_dialog(after_save) -> None:
    import tkinter as tk
    from tkinter import messagebox

    current = _read_brightness_pct()
    current = 50 if current is None else current
    win = tk.Tk()
    win.title("Clawdmeter — Custom Brightness")
    win.resizable(False, False)
    win.configure(bg="#1e1e1e")
    win.geometry("360x170")

    tk.Label(win, text="Display brightness (%)", bg="#1e1e1e", fg="#cccccc",
             font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(18, 0))
    value = tk.StringVar(value=str(current))
    spin = tk.Spinbox(win, from_=5, to=100, increment=5, textvariable=value,
                      font=("Consolas", 12), bg="#2d2d2d", fg="#ffffff",
                      insertbackground="#ffffff", relief=tk.FLAT, bd=6, width=8)
    spin.pack(anchor="w", padx=20, pady=(8, 0))

    def save() -> None:
        try:
            pct = int(value.get())
        except ValueError:
            messagebox.showerror("Invalid", "Enter a number 5–100.", parent=win)
            return
        if not 5 <= pct <= 100:
            messagebox.showerror("Out of range", "Brightness must be 5–100.", parent=win)
            return
        _write_brightness_pct(pct)
        after_save()
        win.destroy()

    buttons = tk.Frame(win, bg="#1e1e1e")
    buttons.pack(fill="x", padx=20, pady=(16, 14))
    tk.Button(buttons, text="Save", command=save, bg="#3a5fd7", fg="white",
              relief=tk.FLAT, padx=16, pady=4).pack(side=tk.RIGHT, padx=(8, 0))
    tk.Button(buttons, text="Cancel", command=win.destroy, bg="#3a3a3a", fg="#cccccc",
              relief=tk.FLAT, padx=16, pady=4).pack(side=tk.RIGHT)
    spin.focus_set()
    win.mainloop()


# ── CYD Wi-Fi fallback ───────────────────────────────────────────────────

_WIFI_FALLBACK_PROVIDERS = ("deepseek", "minimax", "openrouter")
_WIFI_PROVIDER_LABELS = {
    "auto": "Auto (active/saved API key)",
    "deepseek": "DeepSeek",
    "minimax": "MiniMax",
    "openrouter": "OpenRouter",
}
_WIFI_FALLBACK_CREDENTIAL_FILES = {
    "deepseek": "deepseek-credentials.json",
    "minimax": "minimax-credentials.json",
    "openrouter": "openrouter-credentials.json",
}
_WIFI_FALLBACK_ENV_KEYS = {
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_KEY"),
    "minimax": ("MINIMAX_CODING_API_KEY", "MINIMAX_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
}


def _direct_provider_api_key(provider: str) -> str:
    """Read an already-configured direct API key without logging it."""
    for name in _WIFI_FALLBACK_ENV_KEYS.get(provider, ()):
        if key := os.environ.get(name, "").strip():
            return key
    filename = _WIFI_FALLBACK_CREDENTIAL_FILES.get(provider)
    if not filename:
        return ""
    try:
        saved = json.loads((Path.home() / ".config" / "clawdmeter" / filename).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(saved.get("api_key", "")).strip() if isinstance(saved, dict) else ""


def _automatic_wifi_provider() -> tuple[dict[str, str] | None, str]:
    """Prefer the active API provider, then another saved direct API key."""
    from daemon.config import provider_preference

    preferred = provider_preference()
    candidates = (preferred,) + tuple(p for p in _WIFI_FALLBACK_PROVIDERS if p != preferred)
    for provider in candidates:
        if provider not in _WIFI_FALLBACK_PROVIDERS:
            continue
        if api_key := _direct_provider_api_key(provider):
            label = provider.title() if provider != "openrouter" else "OpenRouter"
            if provider == preferred:
                return {"provider": provider, "api_key": api_key}, f"Will use active provider: {label}"
            return {"provider": provider, "api_key": api_key}, f"Will use saved API provider: {label}"
    return None, "Add a DeepSeek, MiniMax, or OpenRouter API key in Accounts & API keys first."


def _selected_wifi_provider(provider: str) -> tuple[dict[str, str] | None, str]:
    """Resolve an explicit provider, or retain the convenient Auto mode."""
    if provider == "auto":
        return _automatic_wifi_provider()
    if provider not in _WIFI_FALLBACK_PROVIDERS:
        return None, "Choose Auto, DeepSeek, MiniMax, or OpenRouter."
    label = _WIFI_PROVIDER_LABELS[provider]
    if api_key := _direct_provider_api_key(provider):
        return {"provider": provider, "api_key": api_key}, f"Wi-Fi fallback provider: {label}"
    article = "an" if provider == "openrouter" else "a"
    return None, f"Add {article} {label} API key in Accounts & API keys first."


def _current_wifi_ssid() -> str:
    """Return Windows' currently connected SSID, without reading its password."""
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=4, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*SSID\s*:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if match:
            ssid = match.group(1)
            if ssid and ssid.lower() != "n/a":
                return ssid
    return ""

def _show_wifi_fallback_dialog(ts: TrayState) -> None:
    """Configure CYD's direct API fallback and queue it over BLE."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    existing = load_wifi_config() or {}
    win = tk.Tk()
    win.title("CYD — Wi-Fi Fallback")
    win.resizable(False, False)
    win.configure(bg="#1e1e1e")
    win.geometry("540x335")

    tk.Label(
        win,
        text=("Used only when CYD has not received BLE data for 90 seconds.\n"
              "Choose a provider; its saved API key is applied automatically."),
        justify=tk.LEFT, bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 9),
    ).pack(anchor="w", padx=20, pady=(18, 6))

    form = tk.Frame(win, bg="#1e1e1e")
    form.pack(fill="x", padx=20, pady=(6, 0))

    def field(row: int, label: str, value: str = "", *, secret: bool = False):
        tk.Label(form, text=label, bg="#1e1e1e", fg="#e0e0e0",
                 font=("Segoe UI", 9), width=15, anchor="w").grid(
                     row=row, column=0, sticky="w", pady=5)
        entry = tk.Entry(form, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff",
                         relief=tk.FLAT, bd=6, font=("Consolas", 10), show="*" if secret else "")
        entry.insert(0, value)
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        return entry

    form.columnconfigure(1, weight=1)
    ssid = field(0, "Wi-Fi name", existing.get("ssid", "") or _current_wifi_ssid())
    password = field(1, "Wi-Fi password", existing.get("password", ""), secret=True)

    tk.Label(form, text="Provider", bg="#1e1e1e", fg="#e0e0e0",
             font=("Segoe UI", 9), width=15, anchor="w").grid(
                 row=2, column=0, sticky="w", pady=5)
    provider_ids = ("auto",) + _WIFI_FALLBACK_PROVIDERS
    provider_by_label = {_WIFI_PROVIDER_LABELS[p]: p for p in provider_ids}
    initial_provider = existing.get("provider", "auto")
    if initial_provider not in provider_ids:
        initial_provider = "auto"
    provider_choice = tk.StringVar(value=_WIFI_PROVIDER_LABELS[initial_provider])
    provider_box = ttk.Combobox(
        form,
        textvariable=provider_choice,
        values=tuple(_WIFI_PROVIDER_LABELS[p] for p in provider_ids),
        state="readonly",
        font=("Segoe UI", 9),
    )
    provider_box.grid(row=2, column=1, sticky="ew", pady=5)

    selected_provider = lambda: provider_by_label.get(provider_choice.get(), "auto")
    provider_config, provider_message = _selected_wifi_provider(selected_provider())
    status = tk.Label(win, text=provider_message, bg="#1e1e1e",
                      fg="#5a7aff" if provider_config else "#d47a7a", font=("Segoe UI", 8))
    status.pack(anchor="w", padx=20, pady=(8, 0))

    def provider_changed(_event=None) -> None:
        config, message = _selected_wifi_provider(selected_provider())
        status.config(text=message, fg="#5a7aff" if config else "#d47a7a")

    provider_box.bind("<<ComboboxSelected>>", provider_changed)

    def use_current_wifi() -> None:
        if detected := _current_wifi_ssid():
            ssid.delete(0, tk.END)
            ssid.insert(0, detected)
        else:
            messagebox.showinfo("Wi-Fi not detected", "Windows is not connected to a Wi-Fi network.", parent=win)

    def save() -> None:
        api_config, api_message = _selected_wifi_provider(selected_provider())
        if not api_config:
            messagebox.showerror("Direct API required", api_message, parent=win)
            return
        config = {
            "ssid": ssid.get(),
            "password": password.get(),
            **api_config,
        }
        try:
            save_wifi_config(config)
        except ValueError:
            messagebox.showerror(
                "Check settings",
                "Enter Wi-Fi name and password.\n"
                "Wi-Fi name is limited to 32 characters; password to 63.",
                parent=win,
            )
            return
        ts.note_wifi_settings_changed()
        pending_config = load_wifi_config(pending_only=True)
        sent_now = bool(pending_config) and ts.sync_wifi_config(pending_config)
        status.config(
            text=("Saved — applying to the connected CYD…" if sent_now
                  else "Saved — CYD will receive this on its next BLE connection."),
            fg="#5a7aff",
        )
        win.after(1600, win.destroy)

    buttons = tk.Frame(win, bg="#1e1e1e")
    buttons.pack(fill="x", padx=20, pady=(14, 16))
    tk.Button(buttons, text="Save to CYD", command=save, bg="#3a5fd7", fg="white",
              relief=tk.FLAT, padx=18, pady=5).pack(side=tk.RIGHT)
    tk.Button(buttons, text="Cancel", command=win.destroy, bg="#3a3a3a", fg="#cccccc",
              relief=tk.FLAT, padx=18, pady=5).pack(side=tk.RIGHT, padx=(0, 8))
    tk.Button(buttons, text="Use current Wi-Fi", command=use_current_wifi, bg="#3a3a3a", fg="#cccccc",
              relief=tk.FLAT, padx=14, pady=5).pack(side=tk.LEFT)
    tk.Label(
        win,
        text="Enter the Wi-Fi password once; Windows' saved password is never read.",
        justify=tk.LEFT, bg="#1e1e1e", fg="#777777", font=("Segoe UI", 8),
    ).pack(anchor="w", padx=20)
    ssid.focus_set()
    win.mainloop()


# ── Generic API key dialog ───────────────────────────────────────────────

def _apikey_dialog(*, title: str, provider_id: str, cred_filename: str,
                    label: str, help_text: str, ts: object = None,
                    secret: bool = True) -> None:
    """Open a Tkinter dialog to set a simple API key credential.

    Args:
        title: Window title (e.g. "DeepSeek — API Key")
        provider_id: Provider ID to set after saving (e.g. "deepseek")
        cred_filename: JSON filename in ~/.config/clawdmeter/ (e.g. "deepseek-credentials.json")
        label: Field label (e.g. "DeepSeek API Key")
        help_text: Instructions shown below the field
        ts: Optional TrayState for refresh after save
    """
    import tkinter as tk
    from tkinter import messagebox

    config_dir = Path.home() / ".config" / "clawdmeter"
    cred_file = config_dir / cred_filename

    existing_key = ""
    if cred_file.exists():
        try:
            data = json.loads(cred_file.read_text(encoding="utf-8"))
            existing_key = data.get("api_key", "")
        except (OSError, json.JSONDecodeError):
            pass

    win = tk.Tk()
    win.title(title)
    win.resizable(False, False)
    win.configure(bg="#1e1e1e")
    win.update_idletasks()
    w, h = 500, 240
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")

    label_font = ("Segoe UI", 10, "bold")
    entry_font = ("Consolas", 10)
    btn_font = ("Segoe UI", 10)

    lbl_status = tk.Label(win, text="", bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 9))
    lbl_status.pack(anchor="w", **{"padx": 20, "pady": (4, 0)})

    def _set_status(msg: str, color: str = "#cccccc") -> None:
        lbl_status.config(text=msg, fg=color)
        win.update_idletasks()

    def _test_and_save() -> None:
        key = entry_key.get().strip()
        if not key:
            messagebox.showerror("Error", "API Key is required", parent=win)
            return
        _set_status("Saving…", "#5a7aff")

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            cred_file.write_text(
                json.dumps({"api_key": key}, indent=2), encoding="utf-8"
            )
        except OSError as e:
            _set_status("", "#cccccc")
            messagebox.showerror("Error", f"Failed to save:\n{e}", parent=win)
            return

        from daemon.config import set_provider
        set_provider(provider_id)

        if ts is not None:
            ts.request_refresh()

        _set_status(f"✅ Saved! Provider set to {provider_id}.", "#5a7aff")
        win.after(1200, win.destroy)

    pad = {"padx": 20, "pady": (20, 0)}
    pad_small = {"padx": 20, "pady": (8, 0)}
    pad_btn = {"padx": 20, "pady": (16, 20)}

    lbl_info = tk.Label(
        win, text=f"Paste your {label} below.",
        justify=tk.LEFT, bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 9),
    )
    lbl_info.pack(anchor="w", **pad)

    frm_key = tk.Frame(win, bg="#1e1e1e")
    frm_key.pack(fill="x", **pad_small)
    lbl = tk.Label(frm_key, text=label, bg="#1e1e1e", fg="#e0e0e0",
                   font=label_font, width=16, anchor="w")
    lbl.pack(side=tk.LEFT)
    entry_key = tk.Entry(frm_key, font=entry_font, bg="#2d2d2d", fg="#ffffff",
                         insertbackground="#ffffff", relief=tk.FLAT, bd=6,
                         show="*" if secret else "")
    entry_key.insert(0, existing_key)
    entry_key.pack(side=tk.LEFT, fill="x", expand=True)

    lbl_help = tk.Label(
        win, text=help_text,
        justify=tk.LEFT, bg="#1e1e1e", fg="#777777", font=("Segoe UI", 8),
    )
    lbl_help.pack(anchor="w", **{"padx": 20, "pady": (6, 0)})

    frm_btn = tk.Frame(win, bg="#1e1e1e")
    frm_btn.pack(fill="x", **pad_btn)

    btn_validate = tk.Button(
        frm_btn, text="✓  Save", command=_test_and_save,
        bg="#3a5fd7", fg="white", font=btn_font,
        relief=tk.FLAT, padx=20, pady=5, cursor="hand2",
    )
    btn_validate.pack(side=tk.RIGHT, padx=(8, 0))

    btn_cancel = tk.Button(frm_btn, text="Cancel", command=win.destroy,
                           bg="#3a3a3a", fg="#cccccc", font=btn_font,
                           relief=tk.FLAT, padx=20, pady=5, cursor="hand2")
    btn_cancel.pack(side=tk.RIGHT)

    win.bind("<Return>", lambda _: _test_and_save())
    entry_key.focus_set()
    win.mainloop()


# ── Provider settings dialogs ────────────────────────────────────────────

def _deepseek_dialog(ts: object = None) -> None:
    _apikey_dialog(
        title="DeepSeek — API Key",
        provider_id="deepseek",
        cred_filename="deepseek-credentials.json",
        label="DeepSeek API Key",
        help_text="API-only: key from platform.deepseek.com/api_keys. Remaining starts full and drains as credits are used.",
        ts=ts,
    )

def _openrouter_dialog(ts: object = None) -> None:
    _apikey_dialog(
        title="OpenRouter — API Key",
        provider_id="openrouter",
        cred_filename="openrouter-credentials.json",
        label="OpenRouter API Key",
        help_text="Get this from openrouter.ai/keys",
        ts=ts,
    )

def _minimax_credentials(config_dir: Path) -> str:
    """Return the saved MiniMax Coding Plan API key, if available."""
    cred_file = config_dir / "minimax-credentials.json"
    try:
        data = json.loads(cred_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("api_key", ""))


def _save_minimax_credentials(config_dir: Path, api_key: str) -> None:
    """Persist a MiniMax Coding Plan key."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "minimax-credentials.json").write_text(
        json.dumps({"api_key": api_key}, indent=2),
        encoding="utf-8",
    )


def _minimax_dialog(ts: object = None) -> None:
    """Open a dialog for the MiniMax Coding Plan key."""
    import tkinter as tk
    from tkinter import messagebox

    config_dir = Path.home() / ".config" / "clawdmeter"
    existing_key = _minimax_credentials(config_dir)

    win = tk.Tk()
    win.title("MiniMax — Credentials")
    win.resizable(False, False)
    win.configure(bg="#1e1e1e")
    win.update_idletasks()
    w, h = 540, 270
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")

    label_font = ("Segoe UI", 10, "bold")
    entry_font = ("Consolas", 10)
    btn_font = ("Segoe UI", 10)

    lbl_status = tk.Label(win, text="", bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 9))
    lbl_status.pack(anchor="w", padx=20, pady=(4, 0))

    def _set_status(msg: str, color: str = "#cccccc") -> None:
        lbl_status.config(text=msg, fg=color)
        win.update_idletasks()

    def _save() -> None:
        api_key = entry_key.get().strip()
        if not api_key:
            messagebox.showerror("Missing credentials", "MiniMax Coding Plan API Key is required.", parent=win)
            return
        try:
            _save_minimax_credentials(config_dir, api_key)
        except OSError as exc:
            messagebox.showerror("Save failed", f"Could not save credentials:\n{exc}", parent=win)
            return

        from daemon.config import set_provider
        set_provider("minimax")
        if ts is not None:
            ts.request_refresh()
        _set_status("✓ Saved — provider set to MiniMax.", "#5a7aff")
        win.after(1200, win.destroy)

    tk.Label(
        win,
        text="ใส่ Coding Plan API Key (sk-cp-*) จาก MiniMax เพื่อดูโควต้า Token Plan.",
        justify=tk.LEFT, bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 9),
    ).pack(anchor="w", padx=20, pady=(20, 0))

    def _field(label: str, value: str, *, secret: bool = False) -> tk.Entry:
        frame = tk.Frame(win, bg="#1e1e1e")
        frame.pack(fill="x", padx=20, pady=(12, 0))
        tk.Label(frame, text=label, bg="#1e1e1e", fg="#e0e0e0",
                 font=label_font, width=17, anchor="w").pack(side=tk.LEFT)
        entry = tk.Entry(frame, font=entry_font, bg="#2d2d2d", fg="#ffffff",
                         insertbackground="#ffffff", relief=tk.FLAT, bd=6,
                         show="*" if secret else "")
        entry.insert(0, value)
        entry.pack(side=tk.LEFT, fill="x", expand=True)
        return entry

    entry_key = _field("Coding Plan API Key", existing_key, secret=True)

    button_frame = tk.Frame(win, bg="#1e1e1e")
    button_frame.pack(fill="x", padx=20, pady=(20, 20))
    tk.Button(button_frame, text="✓  Save", command=_save,
              bg="#3a5fd7", fg="white", font=btn_font, relief=tk.FLAT,
              padx=20, pady=5, cursor="hand2").pack(side=tk.RIGHT, padx=(8, 0))
    tk.Button(button_frame, text="Cancel", command=win.destroy,
              bg="#3a3a3a", fg="#cccccc", font=btn_font, relief=tk.FLAT,
              padx=20, pady=5, cursor="hand2").pack(side=tk.RIGHT)

    win.bind("<Return>", lambda _: _save())
    entry_key.focus_set()
    win.mainloop()


def _zen_dialog(ts: object = None) -> None:
    """Open a Tkinter dialog to set OpenCode Zen credentials.

    Zen borrows workspace_id + auth_cookie from Go credentials.
    Total Budget is user-configurable for bar scaling.

    Args:
        ts: Optional TrayState — if provided, shows a notification and
            triggers provider refresh after saving.
    """
    import tkinter as tk
    from tkinter import messagebox

    config_dir = Path.home() / ".config" / "clawdmeter"
    zen_file = config_dir / "zen-credentials.json"
    go_file = config_dir / "opencode-go-credentials.json"

    # ── read existing ──────────────────────────────────────────────────
    existing_budget = ""
    if zen_file.exists():
        try:
            data = json.loads(zen_file.read_text(encoding="utf-8"))
            tb = data.get("total_budget")
            if tb is not None:
                existing_budget = str(tb)
        except (OSError, json.JSONDecodeError):
            pass

    go_wid = ""
    if go_file.exists():
        try:
            data = json.loads(go_file.read_text(encoding="utf-8"))
            go_wid = data.get("workspace_id", "")
        except (OSError, json.JSONDecodeError):
            pass

    win = tk.Tk()
    win.title("OpenCode Zen — Credentials")
    win.resizable(False, False)
    win.configure(bg="#1e1e1e")
    win.update_idletasks()
    w, h = 520, 300
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")

    label_font = ("Segoe UI", 10, "bold")
    entry_font = ("Consolas", 10)
    btn_font = ("Segoe UI", 10)

    # ── Status label ──
    lbl_status = tk.Label(
        win, text="", bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 9),
    )
    lbl_status.pack(anchor="w", **{"padx": 20, "pady": (4, 0)})

    def _set_status(msg: str, color: str = "#cccccc") -> None:
        lbl_status.config(text=msg, fg=color)
        win.update_idletasks()

    def _save() -> None:
        budget_str = entry_budget.get().strip()
        _set_status("Saving…", "#5a7aff")
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            data = {}
            if budget_str:
                try:
                    data["total_budget"] = float(budget_str)
                except ValueError:
                    messagebox.showerror("Error", "Total Budget must be a number", parent=win)
                    return
            zen_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except OSError as e:
            _set_status("", "#cccccc")
            messagebox.showerror("Error", f"Failed to save:\n{e}", parent=win)
            return

        from daemon.config import set_provider
        set_provider("zen")

        if ts is not None:
            ts.request_refresh()

        _set_status("✅ Saved! Provider set to Zen.", "#5a7aff")
        win.after(1200, win.destroy)

    pad = {"padx": 20, "pady": (20, 0)}
    pad_small = {"padx": 20, "pady": (8, 0)}
    pad_btn = {"padx": 20, "pady": (16, 20)}

    # ── Go workspace (read-only) ──
    if go_wid:
        frm_wid = tk.Frame(win, bg="#1e1e1e")
        frm_wid.pack(fill="x", **pad_small)
        lbl_wid = tk.Label(
            frm_wid, text="Workspace (from Go)", bg="#1e1e1e", fg="#888888",
            font=("Segoe UI", 9), anchor="w",
        )
        lbl_wid.pack(side=tk.LEFT)
        lbl_wid_val = tk.Label(
            frm_wid, text=go_wid, bg="#1e1e1e", fg="#5a7aff",
            font=("Consolas", 9), anchor="w",
        )
        lbl_wid_val.pack(side=tk.LEFT, padx=(8, 0))
    else:
        frm_wid = tk.Frame(win, bg="#1e1e1e")
        frm_wid.pack(fill="x", **pad_small)
        lbl_nogo = tk.Label(
            frm_wid, text="⚠  No Go credentials found — configure Go first",
            bg="#1e1e1e", fg="#d08050", font=("Segoe UI", 9), anchor="w",
        )
        lbl_nogo.pack()

    # ── Total Budget field ──
    frm_budget = tk.Frame(win, bg="#1e1e1e")
    frm_budget.pack(fill="x", **pad_small)
    lbl_budget = tk.Label(frm_budget, text="Total Budget ($)", bg="#1e1e1e", fg="#e0e0e0",
                          font=label_font, width=20, anchor="w")
    lbl_budget.pack(side=tk.LEFT)
    entry_budget = tk.Entry(frm_budget, font=entry_font, bg="#2d2d2d", fg="#ffffff",
                            insertbackground="#ffffff", relief=tk.FLAT, bd=6)
    entry_budget.insert(0, existing_budget)
    entry_budget.pack(side=tk.LEFT, fill="x", expand=True)

    lbl_budget_help = tk.Label(
        win, text="Set your total top-up amount so the bar shows correctly. (e.g. 20)",
        justify=tk.LEFT, bg="#1e1e1e", fg="#777777", font=("Segoe UI", 8),
    )
    lbl_budget_help.pack(anchor="w", **{"padx": 20, "pady": (4, 0)})

    # ── Buttons ──
    frm_btn = tk.Frame(win, bg="#1e1e1e")
    frm_btn.pack(fill="x", **pad_btn)

    btn_save = tk.Button(
        frm_btn, text="✓  Save", command=_save,
        bg="#3a5fd7", fg="white", font=btn_font,
        relief=tk.FLAT, padx=20, pady=5, cursor="hand2",
    )
    btn_save.pack(side=tk.RIGHT, padx=(8, 0))

    btn_cancel = tk.Button(frm_btn, text="Cancel", command=win.destroy,
                           bg="#3a3a3a", fg="#cccccc", font=btn_font,
                           relief=tk.FLAT, padx=20, pady=5, cursor="hand2")
    btn_cancel.pack(side=tk.RIGHT)

    win.bind("<Return>", lambda _: _save())
    entry_budget.focus_set()
    win.mainloop()


# ── OpenCode Go settings dialog ────────────────────────────────────────────

def _opencode_go_dialog(ts: object = None) -> None:
    """Open a Tkinter dialog to set OpenCode Go credentials.

    Args:
        ts: Optional TrayState — if provided, shows a notification and
            triggers provider refresh after saving.
    """
    import tkinter as tk
    from tkinter import messagebox

    config_dir = Path.home() / ".config" / "clawdmeter"
    cred_file = config_dir / "opencode-go-credentials.json"

    existing_wid = ""
    existing_cookie = ""
    if cred_file.exists():
        try:
            data = json.loads(cred_file.read_text(encoding="utf-8"))
            existing_wid = data.get("workspace_id", "")
            existing_cookie = data.get("auth_cookie", "")
        except (OSError, json.JSONDecodeError):
            pass

    win = tk.Tk()
    win.title("OpenCode Go — Credentials")
    win.resizable(False, False)
    win.configure(bg="#1e1e1e")
    win.update_idletasks()
    w, h = 560, 360
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")

    label_font = ("Segoe UI", 10, "bold")
    entry_font = ("Consolas", 10)
    btn_font = ("Segoe UI", 10)

    # ── Validation label (hidden by default) ──
    lbl_status = tk.Label(
        win, text="", bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 9),
    )
    lbl_status.pack(anchor="w", **{"padx": 20, "pady": (4, 0)})

    def _set_status(msg: str, color: str = "#cccccc") -> None:
        lbl_status.config(text=msg, fg=color)
        win.update_idletasks()

    def _entry_clipboard_action(entry: "tk.Entry", action: str):
        """Handle clipboard shortcuts explicitly for Tk entries on Windows."""
        try:
            if action == "paste":
                text = win.clipboard_get()
                if entry.selection_present():
                    entry.delete("sel.first", "sel.last")
                entry.insert(tk.INSERT, text)
                return "break"
            if action == "copy":
                text = entry.selection_get()
                win.clipboard_clear()
                win.clipboard_append(text)
                return "break"
            if action == "cut":
                text = entry.selection_get()
                win.clipboard_clear()
                win.clipboard_append(text)
                entry.delete("sel.first", "sel.last")
                return "break"
            if action == "select_all":
                entry.focus_set()
                entry.selection_range(0, tk.END)
                entry.icursor(tk.END)
                return "break"
        except tk.TclError:
            return "break"
        return None

    def _show_entry_context_menu(entry: "tk.Entry", event) -> str:
        menu = tk.Menu(win, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                       activebackground="#3a5fd7", activeforeground="#ffffff")
        menu.add_command(
            label="Cut",
            command=lambda: _entry_clipboard_action(entry, "cut"),
        )
        menu.add_command(
            label="Copy",
            command=lambda: _entry_clipboard_action(entry, "copy"),
        )
        menu.add_command(
            label="Paste",
            command=lambda: _entry_clipboard_action(entry, "paste"),
        )
        menu.add_separator()
        menu.add_command(
            label="Select All",
            command=lambda: _entry_clipboard_action(entry, "select_all"),
        )
        entry.focus_set()
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        return "break"

    def _install_entry_shortcuts(entry: "tk.Entry") -> None:
        entry.bind("<Control-v>",
                   lambda e, w=entry: _entry_clipboard_action(w, "paste"))
        entry.bind("<Control-V>",
                   lambda e, w=entry: _entry_clipboard_action(w, "paste"))
        entry.bind("<Shift-Insert>",
                   lambda e, w=entry: _entry_clipboard_action(w, "paste"))
        entry.bind("<Control-c>",
                   lambda e, w=entry: _entry_clipboard_action(w, "copy"))
        entry.bind("<Control-C>",
                   lambda e, w=entry: _entry_clipboard_action(w, "copy"))
        entry.bind("<Control-x>",
                   lambda e, w=entry: _entry_clipboard_action(w, "cut"))
        entry.bind("<Control-X>",
                   lambda e, w=entry: _entry_clipboard_action(w, "cut"))
        entry.bind("<Control-a>",
                   lambda e, w=entry: _entry_clipboard_action(w, "select_all"))
        entry.bind("<Control-A>",
                   lambda e, w=entry: _entry_clipboard_action(w, "select_all"))
        entry.bind("<Button-3>",
                   lambda e, w=entry: _show_entry_context_menu(w, e))

    def _test_and_save() -> None:
        """Validate the cookie against the dashboard, then save."""
        wid = entry_wid.get().strip()
        cookie = entry_cookie.get().strip()
        if not wid:
            messagebox.showerror("Error", "Workspace ID is required", parent=win)
            return
        if not cookie:
            messagebox.showerror("Error", "Auth Cookie is required", parent=win)
            return

        _set_status("⏳ Validating credentials…", "#cccccc")

        # Test the dashboard fetch (synchronous HTTP call)
        import urllib.request
        url = f"https://opencode.ai/workspace/{wid}/go"
        req = urllib.request.Request(url, headers={
            "Cookie": f"auth={cookie}",
            "User-Agent": "clawdmeter/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            _set_status("", "#cccccc")
            if e.code == 401 or e.code == 403:
                messagebox.showerror(
                    "Authentication Failed",
                    f"Server returned HTTP {e.code}.\n\n"
                    "Your auth cookie may be expired.\n"
                    "Open opencode.ai → F12 → Application → Cookies\n"
                    "and copy a fresh 'auth' cookie.",
                    parent=win,
                )
            else:
                messagebox.showerror(
                    "Connection Error",
                    f"HTTP {e.code} when contacting OpenCode.\n"
                    "Check your workspace ID and try again.",
                    parent=win,
                )
            return
        except (urllib.error.URLError, OSError) as e:
            _set_status("", "#cccccc")
            messagebox.showerror(
                "Network Error",
                f"Could not reach opencode.ai:\n{e}",
                parent=win,
            )
            return

        # Verify the page actually has usage data (not a login page)
        if "rollingUsage" not in html and "weeklyUsage" not in html:
            _set_status("", "#cccccc")
            messagebox.showerror(
                "Invalid Response",
                "The dashboard page didn't contain usage data.\n"
                "Check your workspace ID and auth cookie.",
                parent=win,
            )
            return

        _set_status("✅ Credentials valid — saving…", "#5a7aff")

        # Save to file
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            cred_data = json.dumps(
                {"workspace_id": wid, "auth_cookie": cookie}, indent=2
            )
            cred_file.write_text(cred_data, encoding="utf-8")
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(
                    str(cred_file), 0x80
                )
            except Exception:
                pass
        except OSError as e:
            _set_status("", "#cccccc")
            messagebox.showerror("Error", f"Failed to save:\n{e}", parent=win)
            return

        # Auto-set provider to "go"
        from daemon.config import set_provider
        set_provider("go")

        # Kick an immediate repoll so the device doesn't wait for the next 60s tick.
        if ts is not None:
            ts.request_refresh()

        _set_status("✅ Saved! Provider set to OpenCode Go. Refreshing now…", "#5a7aff")
        win.after(1200, win.destroy)

    # ── Widgets ────────────────────────────────────────

    pad = {"padx": 20, "pady": (20, 0)}
    pad_small = {"padx": 20, "pady": (8, 0)}
    pad_btn = {"padx": 20, "pady": (16, 20)}

    lbl_info = tk.Label(
        win,
        text="Paste your credentials below. I'll test them before saving.",
        justify=tk.LEFT, bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 9),
    )
    lbl_info.pack(anchor="w", **pad)

    # Workspace ID
    frm_id = tk.Frame(win, bg="#1e1e1e")
    frm_id.pack(fill="x", **pad_small)
    lbl_id = tk.Label(frm_id, text="Workspace ID", bg="#1e1e1e", fg="#e0e0e0",
                      font=label_font, width=14, anchor="w")
    lbl_id.pack(side=tk.LEFT)
    entry_wid = tk.Entry(frm_id, font=entry_font, bg="#2d2d2d", fg="#ffffff",
                         insertbackground="#ffffff", relief=tk.FLAT, bd=6)
    entry_wid.insert(0, existing_wid)
    entry_wid.pack(side=tk.LEFT, fill="x", expand=True)
    _install_entry_shortcuts(entry_wid)

    # Auth Cookie — masked with show/hide toggle
    frm_cookie = tk.Frame(win, bg="#1e1e1e")
    frm_cookie.pack(fill="x", **pad_small)
    lbl_cookie = tk.Label(frm_cookie, text="Auth Cookie", bg="#1e1e1e", fg="#e0e0e0",
                          font=label_font, width=14, anchor="w")
    lbl_cookie.pack(side=tk.LEFT)

    cookie_frame = tk.Frame(frm_cookie, bg="#2d2d2d", highlightthickness=0)
    cookie_frame.pack(side=tk.LEFT, fill="x", expand=True)

    cookie_visible = [False]  # mutable closure for toggle

    def _toggle_cookie_visibility() -> None:
        cookie_visible[0] = not cookie_visible[0]
        entry_cookie.config(show="" if cookie_visible[0] else "*")
        btn_eye.config(text="🙈" if cookie_visible[0] else "👁")

    entry_cookie = tk.Entry(cookie_frame, font=entry_font, bg="#2d2d2d", fg="#ffffff",
                            insertbackground="#ffffff", relief=tk.FLAT, bd=6,
                            show="*")
    entry_cookie.insert(0, existing_cookie)
    entry_cookie.pack(side=tk.LEFT, fill="x", expand=True)
    _install_entry_shortcuts(entry_cookie)

    btn_eye = tk.Button(cookie_frame, text="👁", command=_toggle_cookie_visibility,
                        bg="#2d2d2d", fg="#cccccc", relief=tk.FLAT,
                        font=("Segoe UI", 10), cursor="hand2", bd=0,
                        padx=6, pady=0)
    btn_eye.pack(side=tk.RIGHT)

    # How-to instructions
    lbl_help = tk.Label(
        win,
        text="How to get these: opencode.ai → log in → F12 → Application →\n"
             f"Cookies → select 'auth' → copy value",
        justify=tk.LEFT, bg="#1e1e1e", fg="#777777", font=("Segoe UI", 8),
    )
    lbl_help.pack(anchor="w", **{"padx": 20, "pady": (6, 0)})

    # Buttons
    frm_btn = tk.Frame(win, bg="#1e1e1e")
    frm_btn.pack(fill="x", **pad_btn)

    btn_validate = tk.Button(
        frm_btn, text="✓  Validate & Save", command=_test_and_save,
        bg="#3a5fd7", fg="white", font=btn_font,
        relief=tk.FLAT, padx=20, pady=5, cursor="hand2",
    )
    btn_validate.pack(side=tk.RIGHT, padx=(8, 0))

    btn_cancel = tk.Button(frm_btn, text="Cancel", command=win.destroy,
                           bg="#3a3a3a", fg="#cccccc", font=btn_font,
                           relief=tk.FLAT, padx=20, pady=5, cursor="hand2")
    btn_cancel.pack(side=tk.RIGHT)

    # Bind Enter key to save
    win.bind("<Return>", lambda _: _test_and_save())

    if existing_wid:
        entry_cookie.focus_set()
    else:
        entry_wid.focus_set()
    win.mainloop()


# ---------------------------------------------------------------------------
# single-instance guard (named kernel mutex — no stale-lock problem)
# ---------------------------------------------------------------------------

# Per-session mutex name. "Local\\" scopes it to the interactive logon, which is
# exactly the granularity we want: one tray per signed-in user. Both the headless
# autostart (HKCU\Run pythonw) and an ARSO-restored console instance live in the
# same session, so this name catches the duplicate-launch collision that produced
# the "mystery console window fighting the headless tray over BLE" field bug.
_SINGLETON_MUTEX_NAME = "Local\\Clawdmeter-tray-singleton"
_ERROR_ALREADY_EXISTS = 183


def _acquire_single_instance():
    """Acquire the process-wide single-instance lock.

    Returns a truthy handle to keep alive for the process lifetime if this is
    the first/only tray, or None if another Clawdmeter tray already owns the
    lock (the caller must then exit immediately, before touching BLE).

    Uses a named kernel mutex: Windows releases it automatically when the owning
    process dies, so there is no stale-lock cleanup (unlike a pidfile). We never
    CloseHandle it — the handle lives until process exit, which is precisely the
    lock lifetime we want.

    Off-Windows (Linux dev box / unit tests) this is a no-op that always
    succeeds — the tray only ever runs on Windows, and the dev box must stay
    importable for the pure-helper tests.
    """
    if sys.platform != "win32":
        return object()  # no-op sentinel; never blocks off-Windows

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]

    handle = kernel32.CreateMutexW(None, True, _SINGLETON_MUTEX_NAME)
    if not handle:
        # Couldn't create the mutex at all — fail OPEN so a kernel quirk never
        # stops the tray from starting; single-instance is best-effort hardening.
        return object()
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        return None  # another instance already holds it
    return handle


# ---------------------------------------------------------------------------
# main() — tray entry (pystray on main thread, daemon loop in bg thread)
# ---------------------------------------------------------------------------

def main() -> None:
    """Tray entry point: build icons, start daemon bg thread, run pystray.

    `import pystray` is intentionally INSIDE this function (not at module top)
    so the module can be imported on a GTK-less Linux dev box for unit tests
    of the pure helpers (TrayState, header_text) without pystray failing.
    """
    # Single-instance guard FIRST — before icons, the daemon thread, or any BLE
    # work. If another tray already owns the session mutex (e.g. ARSO restored a
    # console instance and the headless autostart also fired), exit silently.
    # Under pythonw there is no console to print to, so this is a quiet return.
    _instance_lock = _acquire_single_instance()
    if _instance_lock is None:
        return

    import asyncio as _asyncio
    import pystray
    from pystray import Menu, MenuItem

    import daemon.autostart_windows as autostart
    from daemon.config import discover_providers, provider_preference, set_provider
    from daemon.claude_usage_daemon_windows import main as daemon_main, log as daemon_log
    from daemon.petdex.petdex_engine import PetdexEngine, POOL_DIR
    from daemon.icon_assets import load_logo_rgba, build_state_icons

    # Build per-state icons once at startup; swap icon.icon per tick (never recomposite).
    base = load_logo_rgba(os.path.join(_REPO_ROOT, "firmware", "src", "logo.h"))
    images = build_state_icons(base)

    ts = TrayState()
    icon = pystray.Icon("Clawdmeter", images["scanning"], "Clawdmeter")
    _pet_engine = PetdexEngine()
    _pet_engine.discover()

    # --- Petdex helpers ---
    def _on_pet_select(slug: str, state_and_hold: tuple[str, int]) -> None:
        if ts.loop is None or ts.daemon_send_pet is None:
            return
        state, hold_ms = state_and_hold

        async def _send() -> None:
            await ts.daemon_send_pet(slug, state, hold_ms)
            _pet_engine.active_slug = slug
            # Tell the daemon to keep refreshing this pet
            import daemon.claude_usage_daemon_windows as _dw
            _dw._pet_active_slug = slug
            _dw._pet_active_state = state

        _asyncio.run_coroutine_threadsafe(_send(), ts.loop)

    def _on_stop_pet(_icon_ref, _item) -> None:
        """Tell the daemon to stop sending periodic pet refreshes."""
        import daemon.claude_usage_daemon_windows as _dw
        _dw._pet_active_slug = None
        _dw._pet_active_state = "idle"
        _pet_engine.active_slug = None

        async def _send_clear() -> None:
            if ts.daemon_send_pet is None:
                return
            # Clear on device: write empty payload
            try:
                await ts.daemon_send_pet("", "idle", 200)
            except Exception as e:
                log(f"Stop Pet: clear failed: {e}")

        if ts.loop is not None:
            _asyncio.run_coroutine_threadsafe(_send_clear(), ts.loop)
        log("Pet animation stopped")

    def _build_petdex_menu() -> Menu:
        _pet_engine.discover()
        items = []
        for slug, states in sorted(_pet_engine.pets.items()):
            checked = (slug == _pet_engine.active_slug)
            marker = "✓ " if checked else "  "
            items.append(MenuItem(
                f"{marker}{slug.capitalize()} ▶",
                Menu(
                    MenuItem("Apply", _pet_select_action(slug)),
                    MenuItem("Preview...", _pet_preview_action(slug)),
                )
            ))
        if not items:
            items.append(MenuItem("(no pets installed)", None, enabled=False))
        return Menu(*items)

    def _preview_pet_popup(slug: str) -> None:
        """Show a 200x200 preview of the pet's first idle frame."""
        import tkinter as tk
        from PIL import Image, ImageTk

        state_dir = POOL_DIR / slug / "idle"
        pngs = sorted(state_dir.glob("*.png"))
        if not pngs:
            return

        img = Image.open(pngs[0]).convert("RGB").resize((200, 200), Image.Resampling.NEAREST)

        def _show() -> None:
            root = tk.Tk()
            root.title(f"Petdex: {slug.capitalize()}")
            root.configure(bg="#050608")
            root.resizable(False, False)

            tk_img = ImageTk.PhotoImage(img)
            lbl = tk.Label(root, image=tk_img, bg="#050608")
            lbl.image = tk_img  # CRITICAL: prevent GC
            lbl.pack(padx=16, pady=(16, 8))

            btn_frame = tk.Frame(root, bg="#050608")
            btn_frame.pack(pady=(4, 12))

            tk.Button(btn_frame, text="Apply", width=10,
                      command=lambda: (_on_pet_select(slug, ("idle", 200)), root.destroy())
                      ).pack(side=tk.LEFT, padx=4)
            tk.Button(btn_frame, text="Close", width=10,
                      command=root.destroy).pack(side=tk.LEFT, padx=4)

            # Center on screen
            root.update_idletasks()
            x = (root.winfo_screenwidth() - root.winfo_width()) // 2
            y = (root.winfo_screenheight() - root.winfo_height()) // 2
            root.geometry(f"+{x}+{y}")

            root.mainloop()

        threading.Thread(target=_show, daemon=True).start()

    def _pet_select_action(slug: str):
        def _action(_icon_ref, _item) -> None:
            _on_pet_select(slug, ("idle", 200))
        return _action

    def _pet_preview_action(slug: str):
        def _action(_icon_ref, _item) -> None:
            _preview_pet_popup(slug)
        return _action

    # --- background thread: asyncio loop ---
    def _run_daemon() -> None:
        # daemon=True thread: an unhandled exception here would vanish silently
        # and freeze the tray on its last state forever (the field "frozen tray"
        # failure mode). Surface it instead — log the traceback to the rotating
        # file and flip the tray to an actionable error state.
        try:
            _asyncio.run(daemon_main(tray_state=ts))
        except Exception as e:  # last-resort thread guard
            import traceback
            daemon_log(f"Daemon thread crashed: {e!r}")
            daemon_log(traceback.format_exc())
            ts.set_error(f"daemon crashed: {type(e).__name__}")

    daemon_thread = threading.Thread(target=_run_daemon, daemon=True)
    daemon_thread.start()

    # --- menu ---
    def _on_restart(_icon_ref, _item) -> None:
        """Spawn new tray process, then kill this one (hot-reload)."""
        import subprocess
        pythonw = os.path.join(sys.base_exec_prefix, "pythonw.exe")
        script = os.path.abspath(__file__)
        subprocess.Popen([pythonw, script], cwd=os.getcwd())
        os._exit(0)

    def _on_quit(_icon_ref, _item) -> None:
        """Kill process immediately so autostart restarts with fresh credentials."""
        os._exit(1)

    def _on_toggle(_icon_ref, _item) -> None:
        if autostart.is_enabled():
            autostart.disable()
        else:
            # Pass THIS file explicitly — without it enable() defaults the Run
            # value to autostart_windows.py (which has no entry point and starts
            # nothing), silently breaking menu-enabled autostart.
            autostart.enable(tray_script=os.path.abspath(__file__))
        icon.update_menu()

    def _on_provider(provider_id: str) -> None:
        if set_provider(provider_id):
            daemon_log(f"Provider preference set: {provider_id}")
            ts.request_refresh()
        else:
            ts.set_error("could not save provider preference")
        icon.update_menu()

    def _on_provider_click(provider_id: str, _icon_ref, _item) -> None:
        _on_provider(provider_id)

    def _on_opencode_go_settings(_icon_ref, _item) -> None:
        """Open the Tkinter credential dialog in a separate thread so pystray doesn't block."""
        import threading as _t
        _t.Thread(target=lambda: _opencode_go_dialog(ts=ts), daemon=True).start()

    def _on_deepseek_settings(_icon_ref, _item) -> None:
        import threading as _t
        _t.Thread(target=lambda: _deepseek_dialog(ts=ts), daemon=True).start()

    def _on_openrouter_settings(_icon_ref, _item) -> None:
        import threading as _t
        _t.Thread(target=lambda: _openrouter_dialog(ts=ts), daemon=True).start()

    def _on_minimax_settings(_icon_ref, _item) -> None:
        import threading as _t
        _t.Thread(target=lambda: _minimax_dialog(ts=ts), daemon=True).start()

    def _on_zen_settings(_icon_ref, _item) -> None:
        import threading as _t
        _t.Thread(target=lambda: _zen_dialog(ts=ts), daemon=True).start()

    def _on_brightness_choice(pct: int):
        def _handler(_icon_ref, _item) -> None:
            try:
                _write_brightness_pct(pct)
                ts.request_refresh()
                icon.update_menu()
            except OSError as e:
                ts.set_error(f"brightness save failed: {e}")
        return _handler

    def _on_brightness_custom(_icon_ref, _item) -> None:
        import threading as _t
        _t.Thread(target=lambda: _show_brightness_dialog(ts.request_refresh), daemon=True).start()

    def _on_brightness_clear(_icon_ref, _item) -> None:
        _clear_brightness_pct()
        icon.update_menu()

    def _on_wifi_fallback(_icon_ref, _item) -> None:
        import threading as _t
        _t.Thread(target=lambda: _show_wifi_fallback_dialog(ts), daemon=True).start()

    def _build_brightness_menu():
        items = [
            MenuItem(f"{pct}%", _on_brightness_choice(pct),
                     checked=lambda _item, pct=pct: _read_brightness_pct() == pct,
                     radio=True)
            for pct in _BRIGHTNESS_PRESETS
        ]
        items.extend((
            Menu.SEPARATOR,
            MenuItem("Custom…", _on_brightness_custom),
            MenuItem("Clear (keep display setting)", _on_brightness_clear),
        ))
        return Menu(*items)

    def _provider_item(provider):
        return MenuItem(
            provider.label,
            partial(_on_provider_click, provider.id),
            checked=lambda _item, provider_id=provider.id: provider_preference() == provider_id,
        )

    def _build_device_menu():
        return Menu(
            MenuItem("Brightness", _build_brightness_menu()),
            MenuItem(lambda _item: wifi_runtime_label(ts), None, enabled=False),
            MenuItem(lambda _item: wifi_settings_label(cyd_configured=ts.wifi_configured_on_cyd),
                     None, enabled=False),
            MenuItem("Wi-Fi fallback…", _on_wifi_fallback),
        )

    def _build_mascot_menu():
        return Menu(
            MenuItem("Choose mascot", _build_petdex_menu()),
            Menu.SEPARATOR,
            MenuItem("Stop mascot", _on_stop_pet,
                     enabled=lambda _item: _pet_engine.active_slug is not None),
        )

    def _build_accounts_menu():
        return Menu(
            MenuItem("DeepSeek API key…", _on_deepseek_settings),
            MenuItem("MiniMax settings…", _on_minimax_settings),
            MenuItem("OpenRouter API key…", _on_openrouter_settings),
            MenuItem("Zen settings…", _on_zen_settings),
            MenuItem("OpenCode Go…", _on_opencode_go_settings),
        )

    icon.menu = Menu(
        # Non-clickable status header; text updates via update_menu() on state change.
        MenuItem(lambda _item: header_text(ts), None, enabled=False),
        MenuItem("Usage provider", Menu(*(_provider_item(provider) for provider in discover_providers()))),
        Menu.SEPARATOR,
        MenuItem("Display & CYD", _build_device_menu()),
        MenuItem("Mascot", _build_mascot_menu()),
        Menu.SEPARATOR,
        MenuItem("Accounts & API keys", _build_accounts_menu()),
        Menu.SEPARATOR,
        # Start-at-login toggle: checked= is a CALLABLE for live query (Pitfall 6).
        MenuItem("Run at sign-in", _on_toggle, checked=lambda _item: autostart.is_enabled()),
        MenuItem("Restart Clawdmeter", _on_restart),
        MenuItem("Quit Clawdmeter", _on_quit),
    )

    # --- setup callback (runs in pystray's setup thread, 1s poll) ---
    prev_state: dict = {"state": None, "last_sync": None, "wifi_notice_seq": 0,
                        "wifi_settings_seq": 0}

    def _refresh(_icon: pystray.Icon) -> None:
        _icon.visible = True
        while _icon._running:  # type: ignore[attr-defined]
            current = ts.state
            last_sync = ts.last_sync
            wifi_notice_changed = ts.wifi_notice_seq != prev_state["wifi_notice_seq"]
            wifi_settings_changed = ts.wifi_settings_seq != prev_state["wifi_settings_seq"]
            state_changed = current != prev_state["state"]
            # Refresh the tooltip/menu when last_sync advances too — not only on
            # state change. A healthy "connected" daemon polling a flat usage
            # value never changes state, so a transition-only refresh froze the
            # "last update HH:MM" tooltip and read as a dead daemon (SC#2 field
            # report: device + tooltip both looked stuck while polling was fine).
            if state_changed or last_sync != prev_state["last_sync"]:
                if state_changed:
                    _icon.icon = images[current]  # icon image depends on state only
                _icon.title = tray_title_text(ts)
                # D-04: toast ONLY on transition INTO error, not on every error tick.
                if current == "error" and prev_state["state"] != "error":
                    _icon.notify(ts.reason or "Clawdmeter error", "Clawdmeter")
                prev_state["state"] = current
                prev_state["last_sync"] = last_sync
                _icon.update_menu()
            if wifi_notice_changed:
                _icon.notify("CYD Wi-Fi connected", "Clawdmeter")
                prev_state["wifi_notice_seq"] = ts.wifi_notice_seq
            if wifi_settings_changed:
                _icon.update_menu()
                prev_state["wifi_settings_seq"] = ts.wifi_settings_seq
            time.sleep(1.0)

    # Blocks the main thread until icon.stop() is called from _on_quit.
    icon.run(setup=_refresh)


if __name__ == "__main__":
    main()
