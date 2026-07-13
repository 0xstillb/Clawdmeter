# Clawdmeter

A desk-side ESP32 dashboard for keeping an eye on Claude Code, Codex, and
other supported coding-provider usage.

It runs on a [Waveshare ESP32-S3-Touch-AMOLED-2.16](https://www.waveshare.com/esp32-s3-touch-amoled-2.16.htm?&aff_id=149786) as well as a few other alternative boards and pairs over Bluetooth, the splash screen plays pixel-art Clawd animations that get
busier when your usage rate climbs. The two side buttons send Space and
Shift+Tab over BLE HID for Claude Code's voice mode and mode-toggle shortcuts.

|              Usage meter              |              Clawd animation screen              |
| :-----------------------------------: | :----------------------------------------------: |
| ![Usage meter](assets/demo.jpeg) | ![Clawd animation screen](assets/demo.gif) |

The Clawd animations come from [claudepix](https://claudepix.vercel.app), [@amaanbuilds](https://x.com/amaanbuilds)'s library of pixel-art Clawd sprites, check it out, it's lovely.

## Screens

The device boots into the splash. Tap the screen anywhere to switch to the Usage view; tap again to flip back to the splash.

|              Splash               |              Usage              |
| :-------------------------------: | :-----------------------------: |
| ![Splash](screenshots/splash.png) | ![Usage](screenshots/usage.png) |
|   Splash; touch-toggle anytime    | Provider usage and reset time   |

While the splash is up, the middle (PWR) button cycles animations. **Hold the power button for 3 seconds, then release, to put the device into pairing mode** — this clears the saved Bluetooth bond and re-advertises. The firmware also auto-rotates animations every 20 s within the current usage-rate group, so a long stretch on the splash isn't just one Clawd on loop.

## Hardware

Boards supported out of the box:

- [Waveshare ESP32-S3-Touch-AMOLED-2.16](https://www.waveshare.com/esp32-s3-touch-amoled-2.16.htm?&aff_id=149786)
- [Waveshare ESP32-C6-Touch-AMOLED-2.16](https://www.waveshare.com/esp32-c6-touch-amoled-2.16.htm?&aff_id=149786) 
- [Waveshare ESP32-S3-Touch-AMOLED-1.8](https://www.waveshare.com/esp32-s3-touch-amoled-1.8.htm?&aff_id=149786)

> Please check if a pull request exists for your alternative hardware port before opening a new one, providing QA feedback and testing on the same hardware is more valuable than duplicate pull requests.

**Porting to another board:** the firmware is a thin HAL with per-board folders under `firmware/src/boards/`. Drop in a new folder and a new PlatformIO env — `main.cpp`, `ui.cpp`, and `splash.cpp` never need to change. See [`docs/porting/adding-a-board.md`](docs/porting/adding-a-board.md) for the walk-through and [`docs/porting/hal-contract.md`](docs/porting/hal-contract.md) for the interfaces a port must implement.

## First-time setup: ESP32 + host

Clawdmeter has two parts that must both be running:

1. **Firmware** on the ESP32 display — renders the UI, touch input, BLE, and
   HID buttons.
2. **Host daemon** on the computer where Claude Code/Codex is signed in —
   reads usage, then writes it to the display over Bluetooth.

### 1. Choose the correct firmware environment

Use the PlatformIO environment that matches the board. The two S3 AMOLED
boards are the primary, fully documented targets; the other environments are
available for their matching hardware.

| Board | PlatformIO environment | Notes |
| --- | --- | --- |
| Waveshare ESP32-S3-Touch-AMOLED-2.16 | `waveshare_amoled_216` | 480×480 AMOLED; three buttons; battery and rotation support. |
| Waveshare ESP32-S3-Touch-AMOLED-1.8 | `waveshare_amoled_18` | 368×448 AMOLED; original and later panel revisions are detected at boot. |
| Waveshare ESP32-C6-Touch-AMOLED-2.16 | `waveshare_amoled_216_c6` | C6 port; framebuffer screenshots are unsupported because it has no PSRAM. |
| Sunton 2432S028 variants | `sunton_2432s028r`, `sunton_2432s028rv2`, `sunton_2432s028rv3` and `_landscape` variants | Select the environment matching the panel controller and orientation. |

To see the authoritative list in your checkout, inspect
[`firmware/platformio.ini`](firmware/platformio.ini).

### 2. Install PlatformIO and build the firmware

Install [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html), then open a terminal in the repository root. Build before flashing so that pin, library, and board-selection errors are caught first.

```bash
# Build the 2.16-inch S3 AMOLED firmware
pio run -d firmware -e waveshare_amoled_216

# Build the 1.8-inch S3 AMOLED firmware
pio run -d firmware -e waveshare_amoled_18
```

If `pio` is not on your `PATH`, PlatformIO's usual installed location is
`~/.platformio/penv/bin/pio` on macOS/Linux and
`%USERPROFILE%\.platformio\penv\Scripts\pio.exe` on Windows.

### 3. Connect and flash the ESP32

Use a **data-capable USB cable**. The S3 boards expose native USB-JTAG/serial;
normally no manual boot-mode sequence is necessary. Close any serial monitor
before uploading.

```powershell
# Windows: discover the COM port in Device Manager, then flash.
pio run -d firmware -e waveshare_amoled_216 -t upload --upload-port COM5
pio run -d firmware -e waveshare_amoled_18  -t upload --upload-port COM5
```

```bash
# Linux
pio run -d firmware -e waveshare_amoled_216 -t upload --upload-port /dev/ttyACM0

# macOS
pio run -d firmware -e waveshare_amoled_18 -t upload --upload-port /dev/cu.usbmodem101
```

After a successful upload the device starts on the splash screen. Tap the
display to open Usage. A blank screen usually means an incorrect board
environment, a charge-only USB cable, or (for an S3 AMOLED port) missing OPI
PSRAM configuration — do not flash an environment intended for a different
panel.

### 4. Pair over Bluetooth, then install the host daemon

Pair **Clawdmeter** from the host operating system's Bluetooth settings. It is
also a BLE HID keyboard, so pairing is required for the physical buttons as
well as usage data. Then follow the OS-specific installer below.

The daemon scans for the name `Clawdmeter`, caches the resolved BLE address,
and refreshes usage about every 60 seconds. If you move to another physical
board, remove the old device from Bluetooth (or reset pairing on the device)
so the daemon can discover the new address.

### Verify a flashed screen

On PSRAM-capable boards, capture the live framebuffer after a UI change:

```bash
# Linux
./scripts/linux/screenshot.sh screenshot.png /dev/ttyACM0
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts\windows\screenshot.ps1 -ListPorts
powershell -ExecutionPolicy Bypass -File scripts\windows\screenshot.ps1 -Output screenshot.png -Port COM5
```

The C6 and non-PSRAM LCD environments report screenshot capture as unsupported.

## Updating an existing installation

```bash
git pull
pio run -d firmware -e waveshare_amoled_216 -t upload
```

Restart the host daemon afterwards: use **Restart** from the Windows tray,
`systemctl --user restart claude-usage-daemon` on Linux, or unload/load the
LaunchAgent on macOS. Re-run the OS installer if Python dependencies or the
autostart configuration changed.

## Repo layout

- `firmware/` — ESP32 firmware and board ports
- `daemon/` — shared host-daemon source and provider plugins
- `scripts/linux/`, `scripts/macos/`, `scripts/windows/` — OS-specific install/flash/run helpers
- `docs/user/` — end-user setup guides
- `docs/dev/` — architecture and design notes
- `docs/porting/` — board-porting documentation

## Prerequisites

- Linux (tested on Ubuntu), macOS, or Windows 10/11
- [PlatformIO CLI](https://docs.platformio.org/en/latest/core/installation/index.html)
- Linux: `curl`, `bluetoothctl`, `busctl` (BlueZ Bluetooth stack)
- macOS: `python3` (the installer sets up a venv with `bleak` and `httpx`)
- Windows: `python3` 3.11+ (the installer sets up a venv with `bleak`, `httpx`, and `pystray`)
- Claude Code and/or Codex signed in on the host computer

## macOS installation

The macOS host pieces — Python daemon, LaunchAgent, and flash helper — were ported by [Chris Davidson (@lorddavidson)](https://github.com/lorddavidson). Thanks Chris!

### Flash the firmware

```bash
./scripts/macos/flash.sh waveshare_amoled_216                       # auto-detects /dev/cu.usbmodem*
./scripts/macos/flash.sh waveshare_amoled_18  /dev/cu.usbmodem1101  # or pass an explicit USB serial port
```

The board env name is required. Run `./scripts/macos/flash.sh` with no args to see the available envs (scraped from `firmware/platformio.ini`).

### Pair the device

After flashing, open **System Settings → Bluetooth** and click *Connect* next to "Clawdmeter". The daemon will discover it on its next scan (~30 s).

### Install the daemon

The daemon reads your Claude OAuth token from the macOS Keychain (service `Claude Code-credentials`), polls usage every 60 s, and pushes it to the display over BLE.

```bash
./scripts/macos/install.sh
```

The installer creates a Python venv in `daemon/.venv/`, installs `bleak` and `httpx`, renders a LaunchAgent into `~/Library/LaunchAgents/com.user.claude-usage-daemon.plist`, and loads it. The first run is launched interactively so macOS prompts for Bluetooth permission.

Useful commands:

```bash
launchctl list | grep claude-usage                                          # check it's running
tail -F ~/Library/Logs/claude-usage-daemon.out.log                          # live logs
launchctl unload ~/Library/LaunchAgents/com.user.claude-usage-daemon.plist  # stop
launchctl load -w ~/Library/LaunchAgents/com.user.claude-usage-daemon.plist # start
```

## Linux installation

### Flash the firmware

```bash
./scripts/linux/flash.sh waveshare_amoled_216                  # defaults to /dev/ttyACM0
./scripts/linux/flash.sh waveshare_amoled_18  /dev/ttyACM1     # or pass an explicit USB serial port
```

The board env name is required. Run `./scripts/linux/flash.sh` with no args to see the available envs (scraped from `firmware/platformio.ini`).

### Pair the device

After flashing, the device advertises as "Clawdmeter". Pair it once:

```bash
# Scan for the device
bluetoothctl scan le

# When "Clawdmeter" appears, pair and trust it
bluetoothctl pair F4:12:FA:C0:8F:E5    # use your device's MAC
bluetoothctl trust F4:12:FA:C0:8F:E5
```

To re-pair later, hold the power button for 3 seconds then release — the device clears its saved bond and re-advertises.

### Install the daemon

The daemon polls your Claude usage every 60 seconds and sends it to the display over BLE.

```bash
./scripts/linux/install.sh
systemctl --user start claude-usage-daemon
```

Check status: `systemctl --user status claude-usage-daemon`

View logs: `journalctl --user -u claude-usage-daemon -f`

## Windows installation

Runs natively on Windows — no WSL required. A system-tray app polls your usage and pushes it over BLE, and starts automatically at login.

### Prerequisites

- **Native Windows** (not WSL).
- **Python 3.11+** from [python.org](https://www.python.org/downloads/) — check *"Add python.exe to PATH"* during install.
- **Claude Code and/or Codex** installed and signed in. Claude credentials are read from `%USERPROFILE%\.claude\.credentials.json` (falling back to `%LOCALAPPDATA%\Claude\` then `%APPDATA%\Claude\`); Codex auth is read from `%USERPROFILE%\.Codex\auth.json` or `%USERPROFILE%\.codex\auth.json`.
- The repo on a **native Windows path** (e.g. `%USERPROFILE%\Clawdmeter`), **not** a `\\wsl$` share — the installer refuses a WSL path.

### Flash the firmware

```powershell
pio run -d firmware -e waveshare_amoled_216 -t upload --upload-port COM5   # use your device's COM port
```

Run `pio run -d firmware` with no env to see the available board envs.

### Pair the device

The device is a bonded BLE HID keyboard, so pair it once: **Settings → Bluetooth & devices → Add device → Bluetooth**, then select "Clawdmeter". Pairing is **required** — it enables the physical buttons and keeps a persistent connection (the device keeps showing your last-synced usage even after the daemon quits). To undo, use **Remove device** (this disables the buttons).

### Install the daemon (recommended)

Easiest path: double-click `scripts/windows/Start Clawdmeter.cmd` from the repository folder.
It creates/checks `.venv`, installs the Windows dependencies, enables Start at
login, and starts the tray app without a console window.

Manual path from the repo root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
```

This creates a venv, installs `bleak`/`httpx`/`pystray`/`Pillow` from the in-repo requirements, registers a per-user login-autostart entry (`HKCU\…\Run`, no admin needed), and launches the tray app headlessly (no console window). `pip` may download those packages from PyPI if they are not already cached.

### Run manually instead (optional)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned, then retry
pip install -r daemon\requirements-windows.txt
python daemon\claude_usage_daemon_windows.py        # runs in the foreground; Ctrl+C to stop
```

### Tray icon and menu

The icon's corner bubble shows state — **green** Connected, **amber** Scanning, **red** Error — and hovering shows the status (`Connected · last update HH:MM`). A notification fires once when it enters Error (e.g. an expired token). Right-click for the menu:

- **Status header** — live state + last sync time.
- **Provider** — switch among the discovered providers without restarting; the choice is saved under `%LOCALAPPDATA%\Clawdmeter\config.json`.
- **Credentials** — configure DeepSeek, OpenRouter, Zen, or OpenCode Go when those provider plugins are installed. Zen uses the OpenCode Go workspace/auth credentials plus its own optional total-budget setting.
- **Start at login** — toggle autostart on/off.
- **Quit** — stops the daemon cleanly; leaves the Windows pairing intact (device keeps its last reading).

### Logs and troubleshooting

```powershell
Get-Content $env:LOCALAPPDATA\Clawdmeter\daemon.log -Tail 30        # view logs
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Clawdmeter /f   # remove autostart
```

| Symptom | Fix |
|---------|-----|
| `Device not found` | Power on the device; make sure it's in range and paired. |
| `No usage source found` | Sign in with Claude Code and/or Codex on this Windows machine first. |
| `Codex usage HTTP 401` | Sign in to Codex again so `auth.json` is refreshed. |
| `token expired` toast / `API HTTP 401` | Re-run `claude login`, then restart the daemon. |
| `Connection failed` | Toggle Windows Bluetooth off/on in Settings. |
| `Warning: running under Linux/WSL` | Run from a native PowerShell window, not a WSL shell. |

Full Windows tray/setup guide: [`docs/user/windows-daemon.md`](docs/user/windows-daemon.md)

## How it works

1. The daemon reads your usage-provider credentials. macOS/Linux currently read Claude Code OAuth credentials; Windows can auto-select the available provider and also supports provider-specific credentials from its tray menu.
2. Claude polling makes a minimal API call to `api.anthropic.com/v1/messages`; Codex polling reads the ChatGPT/Codex usage endpoint with the local Codex OAuth token.
3. The usage numbers are normalized into a BLE payload shape (`s`, `sr`, `w`, `wr`, `st`, `ok`, plus provider `p`). Codex accounts that expose only a weekly window are marked `weekly_only`; the firmware shows one Weekly card rather than a stale second limit.
4. The daemon connects to the ESP32 over BLE and writes a JSON payload to the GATT RX characteristic.
5. The firmware parses it and updates the LVGL dashboard.
6. The firmware also tracks the rate of change of the current usage value over a 5-minute window and picks splash animations from the matching mood group.
7. The two side buttons are independent of all of this — they send Space and Shift+Tab as BLE HID keyboard input to the paired host directly.

## Physical buttons

The AMOLED-2.16 board has three physical buttons. Left and right send HID
keys; the middle (PWR) button cycles splash animations and, held for 3 seconds,
triggers pairing mode.

| Button           | GPIO         | Function                                                       |
| ---------------- | ------------ | -------------------------------------------------------------- |
| **Left**         | GPIO 0       | Hold to send Space (Claude Code voice-mode push-to-talk)       |
| **Middle** (PWR) | AXP2101 PKEY | On splash: cycle animations. Hold 3s + release: pairing mode |
| **Right**        | GPIO 18      | Press to send Shift+Tab (Claude Code mode toggle)              |

Space and Shift+Tab go out as standard BLE HID keyboard reports, so they trigger in whatever window has focus on the paired host — not just Claude Code.

The AMOLED-1.8 board has the BOOT button (Space) and PWR button only; it has
no GPIO 18 / Shift+Tab button. Its screen orientation is fixed. The Sunton
ports have their own board-specific input capabilities.

## BLE protocol

The device advertises a custom GATT service alongside the standard HID keyboard service:

|                            | UUID                                   |
| -------------------------- | -------------------------------------- |
| **Data Service**           | `4c41555a-4465-7669-6365-000000000001` |
| RX Characteristic (write)  | `4c41555a-4465-7669-6365-000000000002` |
| TX Characteristic (notify) | `4c41555a-4465-7669-6365-000000000003` |
| **HID Service**            | `00001812-0000-1000-8000-00805f9b34fb` |

JSON payload format (written to RX):

```json
{ "s": 45, "sr": 120, "w": 28, "wr": 7200, "st": "allowed", "ok": true }
```

Fields: `s` = session %, `sr` = session reset (minutes), `w` = weekly %, `wr` = weekly reset (minutes), `st` = status, `ok` = success flag.

## Recompiling fonts

The `firmware/src/font_*.c` files are pre-compiled LVGL bitmap fonts.

```bash
npm install -g lv_font_conv
```

Generate each one (one at a time — `lv_font_conv` doesn't like loop-driven invocations) with `--no-compress` (required for LVGL 9):

```bash
# Tiempos Text (titles, 56px)
lv_font_conv --font assets/TiemposText-400-Regular.otf -r 0x20-0x7E \
  --size 56 --format lvgl --bpp 4 --no-compress \
  -o firmware/src/font_tiempos_56.c --lv-include "lvgl.h"

# Styrene B (large numbers 48, panel labels 28, small text 24, minimal 20)
for size in 48 28 24 20; do
  lv_font_conv --font assets/StyreneB-Regular.otf -r 0x20-0x7E \
    --size $size --format lvgl --bpp 4 --no-compress \
    -o firmware/src/font_styrene_${size}.c --lv-include "lvgl.h"
done

# DejaVu Sans Mono (32px, with spinner Unicode chars)
lv_font_conv --font assets/DejaVuSansMono.ttf \
  -r 0x20-0x7E,0xB7,0x2026,0x2722,0x2733,0x2736,0x273B,0x273D \
  --size 32 --format lvgl --bpp 4 --no-compress \
  -o firmware/src/font_mono_32.c --lv-include "lvgl.h"
```

**Important:** `lv_font_conv` v1.5.3 outputs LVGL 8 format. Each generated file must be patched for LVGL 9 compatibility:

1. Remove `#if LVGL_VERSION_MAJOR >= 8` guards around `font_dsc` and the font struct
2. Remove the `.cache` field from `font_dsc`
3. Add `.release_glyph = NULL`, `.kerning = 0`, `.static_bitmap = 0` to the font struct
4. Add `.fallback = NULL`, `.user_data = NULL` to the font struct

Without these patches, fonts compile but render as invisible.

### CJK support

`firmware/src/font_cjk_16.c` covers the full CJK Unified Ideographs basic
block (U+4E00–U+9FFF, ~20k glyphs) plus ASCII, CJK punctuation, and
halfwidth/fullwidth forms. Generated from [Noto Sans CJK SC](https://github.com/notofonts/noto-cjk)
(SIL OFL 1.1) at 16px, 2bpp:

```bash
lv_font_conv --font NotoSansCJKsc-Regular.otf --size 16 --bpp 2 \
  --no-compress --format lvgl --lv-include 'lvgl.h' \
  -r '0x20-0x7E,0xB7,0x2014,0x2018-0x2019,0x201C-0x201D,0x2026,0x3000-0x303F,0x4E00-0x9FFF,0xFF00-0xFFEF' \
  -o firmware/src/font_cjk_16.c
```

Then apply the four LVGL 9 patches above. Because the font has >65k of
glyph bitmap data, the build needs `-DLV_FONT_FMT_TXT_LARGE=1` in
`platformio.ini` build flags so font descriptor offsets switch from
16-bit to 32-bit.

The CJK font is used for the Activity screen's user-prompt row and todo
content rows. The headline (28pt Styrene B) and titles stay ASCII-only
to preserve the brand font — Chinese text in those slots renders as
empty boxes. Add a `font_cjk_28.c` if full coverage is needed (~1MB
more flash).

## Converting Lucide icons

The UI uses a small set of [Lucide](https://lucide.dev) icons (bluetooth + battery states) converted to RGB565 / RGB565A8 C arrays for LVGL.

```bash
node tools/png_to_lvgl.js assets/icon_bluetooth_48.png icon_bluetooth_data ICON_BLUETOOTH_WIDTH ICON_BLUETOOTH_HEIGHT
```

Default tint is white (`0xFFFFFF`); Lucide PNGs ship as black-on-transparent and would render invisible against the dark UI without it. Pass `--no-tint` for pre-coloured artwork like the logo. Battery icons use RGB565A8 (alpha plane) so they blend cleanly over the splash; the rest are baked RGB565 over the panel colour. Paste the converter output into `firmware/src/icons.h`.

## Splash animations

The animations come from [claudepix.vercel.app](https://claudepix.vercel.app),
a library of Clawd sprites. `tools/scrape_claudepix.js` evaluates the
site's JavaScript in a Node VM to pull out frame data and palettes, then
`tools/convert_to_c.js` turns everything into RGB565 C arrays and writes
`firmware/src/splash_animations.h`.

To re-pull (e.g. when the source library updates):

```bash
node tools/scrape_claudepix.js
node tools/convert_to_c.js
pio run -d firmware -t upload
```

See `tools/README.md` for details.

## Credits

- Pixel-art Clawd animation by [@amaanbuilds](https://x.com/amaanbuilds), sourced from [claudepix.vercel.app](https://claudepix.vercel.app). Frame data and palettes scraped + converted by the tooling in `tools/`.
- Lucide icon set ([lucide.dev](https://lucide.dev), MIT) for bluetooth and battery UI glyphs.
- Anthropic brand fonts (Tiempos Text, Styrene B) — see licensing warning below.

## Licensing gray area warning

The software in this repository uses and adheres to the Anthropic brand guidelines and uses the same proprietary fonts that Anthropic has a license for but this software uses without permission as well as using assets from Anthropic such as the copyrighted Clawd mascot so even though the code in this repo is non-proprietary I will not license it myself under a copyleft license since this repo includes proprietary fonts and copyrighted assets. Please be aware of this if you fork or copy the code from this repo. **You have been warned!**
