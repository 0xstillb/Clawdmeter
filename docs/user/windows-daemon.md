# Windows Setup and Run Guide

This guide covers running the Clawdmeter Windows daemon on native Windows hardware.
It includes the turnkey `scripts/windows/install.ps1` bootstrap (tray icon + login autostart),
the manual-run fallback, and how to manage or remove autostart.

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **Native Windows** | Must run on real Windows — not WSL. The script prints a warning and BLE will not work under WSL. |
| **Python 3.11+** | Download from [python.org](https://www.python.org/downloads/) if not already installed. Ensure "Add python.exe to PATH" is checked during install. |
| **Claude Code and/or Codex installed** | Install the client you want to track and sign in at least once so its local auth file exists. |
| **Clawdmeter powered on** | The device must be powered on and in range before the daemon starts. |
| **Paired with Windows Bluetooth** | Pair the device once via **Settings → Bluetooth & devices → Add device** (see [Pair the device](#pair-the-device-one-time)). This is required — the device is a bonded BLE HID keyboard, so pairing enables its physical buttons and keeps a persistent connection that shows your last usage even when the daemon is stopped. |

### Where are my credentials?

`claude login` writes the OAuth token to (first match wins):

1. `%USERPROFILE%\.claude\.credentials.json` — primary path (confirmed by Claude Code docs)
2. `%LOCALAPPDATA%\Claude\.credentials.json` — fallback
3. `%APPDATA%\Claude\.credentials.json` — fallback

The daemon probes these paths in order. You can also set `CLAUDE_CREDENTIALS_PATH` to an
absolute path or `CLAUDE_CONFIG_DIR` to a directory to override the search entirely.

Codex stores its auth state at:

1. `%USERPROFILE%\.Codex\auth.json` — first Windows probe
2. `%USERPROFILE%\.codex\auth.json` — fallback
3. `%CODEX_HOME%\auth.json` — if `CODEX_HOME` is set, it overrides both defaults

By default the Windows daemon auto-selects a provider in this order:

1. Codex, if a readable `auth.json` is present
2. Claude, if a readable `.credentials.json` is present

You can switch this from the tray menu: **Provider → Auto / Codex / Claude**.
The choice is saved to `%LOCALAPPDATA%\Clawdmeter\config.json` and takes effect
on the next poll, without restarting the daemon. For scripts, `CLAWDMETER_PROVIDER`
is still supported as a fallback when no config file has been written.

> **Security note:** The credentials file contains your OAuth token. Never share its contents
> or embed it in scripts. The daemon reads it from disk and uses it only as the API
> `Authorization` header — tokens are never written to any log, tooltip, or notification.

---

## Pair the device (one time)

The Clawdmeter is a **bonded BLE HID keyboard** as well as a usage display — its firmware
enables bonding (`NimBLEDevice::setSecurityAuth`) and advertises the HID service so its
physical buttons act as a keyboard (Space / Shift+Tab). Pair it with Windows **once**,
before running the daemon:

1. Put the device on its Bluetooth waiting screen (powered on, not yet connected).
2. Open **Settings → Bluetooth & devices → Add device → Bluetooth**.
3. Select **Clawdmeter** and complete pairing.

**Why this is required:**

- **Keyboard buttons** — HID over BLE requires bonding on Windows. Without pairing, the
  device's buttons won't reach the PC.
- **Persistent point-in-time view** — once paired, Windows maintains the BLE link and
  auto-reconnects the device whenever it is in range. This is intentional: the device keeps
  showing your **last-synced** usage even after you Quit the daemon, as a glanceable
  point-in-time view. Quitting the daemon releases only its data connection — it does **not**
  drop the Windows pairing, so the device stays connected to Windows.

To undo, use **Settings → Bluetooth & devices → (device) → Remove device**. Removing the
pairing disables the keyboard buttons.

---

## Setup (one time)

Open a PowerShell terminal and `cd` to the repository root.

### Easiest path: double-click launcher

Double-click `scripts/windows/Start Clawdmeter.cmd` from the repository folder. It will:

1. Create `.venv` if needed.
2. Install/check the Windows dependencies.
3. Enable **Start at login**.
4. Start the tray app with no console window.

After that, use the tray menu for **Provider**, **Start at login**, and **Quit**.

### Manual setup

**1. Create a virtual environment**

```powershell
python -m venv .venv
```

**2. Activate it**

```powershell
.venv\Scripts\Activate.ps1
```

If you see a scripts-execution-policy error, run:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
Then repeat the `Activate.ps1` step.

**3. Install dependencies**

```powershell
pip install -r daemon\requirements-windows.txt
```

This installs `bleak` (WinRT BLE), `httpx` (async HTTP for the usage APIs),
plus the tray dependencies `pystray` and `Pillow`.

---

## Running the daemon

With the venv active and the Clawdmeter powered on:

```powershell
python daemon\claude_usage_daemon_windows.py
```

### Optional: force a provider for manual/script runs

```powershell
$env:CLAWDMETER_PROVIDER = "codex"
python daemon\claude_usage_daemon_windows.py
```

Valid values are `auto`, `codex`, and `claude`. `auto` is the default. The tray
menu config wins over this environment variable once `%LOCALAPPDATA%\Clawdmeter\config.json`
exists.

### Optional: force a BLE address

If Windows pairing already exists and scan-by-name is flaky on your machine, you can
pin the BLE address explicitly:

```powershell
$env:CLAWDMETER_BLE_ADDRESS = "AA:BB:CC:DD:EE:FF"
python daemon\claude_usage_daemon_windows.py
```

Without the override, the daemon now tries targets in this order:

1. `CLAWDMETER_BLE_ADDRESS`, if set
2. the last successfully connected BLE address cached under `%LOCALAPPDATA%\Clawdmeter`
3. active scan by the advertised name `Clawdmeter`

### Expected console output

```
[HH:MM:SS] === Clawdmeter Usage Daemon (BLE, Windows) ===
[HH:MM:SS] Poll interval: 60s
[HH:MM:SS] Scanning for 'Clawdmeter' (8.0s)...
[HH:MM:SS] Found: XX:XX:XX:XX:XX:XX
[HH:MM:SS] Connecting to XX:XX:XX:XX:XX:XX...
[HH:MM:SS] Connected
[HH:MM:SS] Sending: {"s":42,"sr":180,"w":17,"wr":8820,"st":"allowed","ok":true,"p":"codex"}
```

- **The device must be paired with Windows first** (see [Pair the device](#pair-the-device-one-time)).
  The daemon then connects over that existing link via `BleakScanner` + `BleakClient`; it does
  not pop its own pairing dialog.
- The daemon builds a provider-aware payload internally, then writes the compact legacy-compatible
  shape shown above over BLE. This keeps Windows GATT writes small while still tagging the provider
  as `p`.
- After `Connected`, the daemon polls the selected provider immediately and sends the first
  payload within a few seconds of connect. With valid credentials the device should leave its
  waiting screen and show current + weekly percentages within about 10 seconds of launch.
- The daemon then re-polls every 60 seconds while connected. If the device fires a refresh
  request (e.g., after a button press), an immediate re-poll occurs without waiting for the
  60-second interval.
- If the device disconnects or goes out of range, the daemon logs `Device disconnected` and
  re-scans automatically with exponential backoff (starting at 1 second, capped at 60 seconds).

### Stopping

Press **Ctrl+C** in the terminal. The daemon logs `Daemon stopping` and exits cleanly.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Warning: running under Linux/WSL` | Running in WSL, not native Windows | Run from a native PowerShell or Command Prompt on Windows |
| `Scanning for 'Clawdmeter'… Device not found` | Clawdmeter is off, out of range, or showing a non-Bluetooth screen | Power on the device and ensure it is on the Bluetooth waiting screen |
| `Trying cached device address: ...` then `Connection lost` | The remembered BLE address is stale after reflashing or swapping boards | Let the daemon retry once; it clears the stale cache and falls back to a fresh scan automatically |
| `No usage source found` | Neither Claude nor Codex credentials were found | Sign in with Claude Code and/or Codex on this Windows machine first |
| `Codex sign-in missing; skipping poll` | Codex was selected in the tray menu or `CLAWDMETER_PROVIDER=codex` was set, but no Codex `auth.json` was found | Confirm `%USERPROFILE%\.Codex\auth.json` exists or set `CODEX_HOME` correctly |
| `API HTTP 401` | Token expired | Re-run `claude login` in a terminal to refresh the token, then restart the daemon |
| `Codex usage HTTP 401` followed by refresh failure logs | Codex access token could not be refreshed | Sign in to Codex again on this Windows machine so `auth.json` is updated |
| `Connection failed` | WinRT BLE initialisation issue | Ensure Windows Bluetooth is on; try toggling Bluetooth off/on in Windows Settings |

---

## Tray icon, login autostart, and turnkey install

### One-command install (recommended)

> **Copy the repo to a native Windows path first.** Clone or copy this repository
> to a Windows location such as `%USERPROFILE%\Clawdmeter` — **not** a WSL share
> (`\\wsl$\...` or `\\wsl.localhost\...`). Installing from the WSL share would point
> the virtual environment and the login-autostart entry at a path that disappears when
> WSL shuts down, defeating the whole point of the Windows daemon. The installer
> detects a WSL path and refuses to run, telling you how to relocate.
>
> ```powershell
> Copy-Item -Recurse '\\wsl.localhost\Ubuntu\home\<you>\repos\Clawdmeter' "$env:USERPROFILE\Clawdmeter"
> cd "$env:USERPROFILE\Clawdmeter"
> ```

Run this once from the repository root in PowerShell (a native Windows path):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
```

The script does four things in order and logs progress at each step:

1. Creates a Python virtual environment at `.venv`.
2. Installs dependencies from `daemon\requirements-windows.txt` (bleak, httpx, pystray, Pillow).
3. Registers the tray app to launch automatically at login via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` — per-user, no admin required.
4. Launches the tray app immediately (headless — no console window).

The script installs only the packages listed in the in-repo `daemon\requirements-windows.txt`;
`pip` may download them from PyPI if they are not already cached on the machine.

### Tray icon and status

After install, the Clawdmeter icon appears in the Windows notification area:

| State | Icon bubble | Tooltip |
|-------|-------------|---------|
| Connected | green | `Connected · last update HH:MM` |
| Scanning | amber | `Scanning…` |
| Error | red | `Error: token expired — run claude login` |

Hover over the icon to see the current status tooltip. A notification fires once when the
daemon first enters the Error state (e.g. after a token expiry).

### Tray menu

Right-click the tray icon for the menu:

- **Status header** (non-clickable) — live status + last data sync time.
- **Provider** — choose Auto, Codex, or Claude. The menu is generated from the
  daemon provider registry so future providers can be added in one place.
- **Start at login** (checkable toggle) — enables or disables autostart at runtime.
  Reflects the current registry state each time the menu opens.
- **Quit** — stops the daemon cleanly and exits with no lingering process. It releases the
  daemon's own data connection but does **not** drop the Windows Bluetooth pairing — the
  device stays connected to Windows and keeps showing your last-synced usage (point-in-time
  view).

### Disabling or removing autostart

Use the tray menu toggle, or remove the registry value manually:

```powershell
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Clawdmeter /f
```

### WSL independence

The daemon operates fully independently of WSL. Credentials are read from native Windows
paths (`%USERPROFILE%\.claude\.credentials.json`, `%USERPROFILE%\.Codex\auth.json`, and
their fallbacks); BLE uses the WinRT stack directly. Running `wsl --shutdown` does not
affect the BLE link, and the daemon starts correctly even in a fresh Windows session
where WSL has never been launched.

---

## What is NOT covered here

- PyInstaller / one-file `.exe` packaging — v2
