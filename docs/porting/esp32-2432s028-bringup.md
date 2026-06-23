# ESP32-2432S028 bring-up status

This document tracks the real hardware bring-up state of the Sunton / Cheap
Yellow Display 2.8-inch `240x320` port in Clawdmeter.

## Current status

Hardware-verified in this session:
- board family: ESP32-2432S028 / Sunton CYD 2.8-inch
- MCU reported by boot log: `ESP32-D0WD-V3`
- working display controller path: `ILI9341-v1`
- working firmware env: `sunton_2432s028r_landscape`
- confirmed not needed for this board: `sunton_2432s028rv3_landscape`

What we observed on the real board:
- backlight and SPI panel init work
- the diagnostic full-screen color test flashes red, green, blue, then white
- the shared UI boots and renders
- the first successful UI image was clipped / not full-screen until the native
  panel geometry fix below was applied

## Root causes found

### 1. White screen was not one bug

There were two separate issues:

1. Wrong panel guess:
   `ST7789` (`sunton_2432s028rv3_landscape`) flashed successfully but the
   screen stayed effectively blank.
2. Splash failure on PSRAM-free board:
   splash allocation failed, and the shared UI originally hid the usage screen
   when `SCREEN_SPLASH` was requested, leaving a blank-looking screen even
   though the app was alive.

### 2. Clipped / partial UI was a geometry bug

The panel driver was being constructed with the logical rotated size
`320x240`. `Arduino_GFX` already swaps width/height internally when
`rotation=1`, so the constructor must receive the physical native panel size
`240x320`.

Without that, the address window and clipping bounds were wrong and the image
rendered only into part of the display.

## Code changes made

### Splash fallback

File:
`firmware/src/ui.cpp`

Change:
- if `SCREEN_SPLASH` is requested but `splash_get_root()` is null, fall back to
  `SCREEN_USAGE` instead of hiding the whole usage view

Relevant code:
- `ui_show_screen()` fallback branch

### Native panel geometry fix

File:
`firmware/src/boards/sunton_2432s028/display.cpp`

Changes:
- added:
  - `PANEL_NATIVE_WIDTH = 240`
  - `PANEL_NATIVE_HEIGHT = 320`
- changed `Arduino_ILI9341` / `Arduino_ST7789` constructors to use native panel
  size instead of `LCD_WIDTH` / `LCD_HEIGHT`

This keeps the shared HAL/UI dimensions logical (`320x240` in landscape) while
feeding the display driver the physical panel size it expects before rotation.

### Diagnostic color sequence

File:
`firmware/src/boards/sunton_2432s028/display.cpp`

Temporary but currently useful:
- after `gfx->begin()`, firmware fills the panel with red, green, blue, then
  white to separate panel-init failures from LVGL/UI failures

This helped confirm the display path was alive on hardware.

## Latest confirmed boot log

The currently working build reports:

```text
display: begin=1 variant=ILI9341-v1 rot=1 size=320x240
```

Other useful boot lines seen:

```text
splash: failed to alloc canvas buffer
Dashboard ready (Sunton ESP32-2432S028, 320x240), waiting for data on BLE...
```

The splash allocation failure is still present, but it no longer causes the
screen to disappear because the UI now falls back to `SCREEN_USAGE`.

## Known-good flash command

From `firmware/`:

```sh
uvx platformio run -e sunton_2432s028r_landscape -t upload
```

On this machine during bring-up, upload was done with:

```sh
uvx platformio run -e sunton_2432s028r_landscape -t upload --upload-port COM7
```

## Variants tested

Tested on real hardware:
- `sunton_2432s028rv3_landscape`
  - booted
  - no useful image
  - not the right panel path for this board
- `sunton_2432s028r_landscape`
  - correct panel path
  - color test visible
  - UI visible
  - required geometry fix to fill screen correctly

Not allowed to finish uploading in this session:
- `sunton_2432s028rv2_landscape`
  - build was started once
  - stopped before upload so it would not overwrite the working firmware

## Remaining work

1. Confirm visually that the latest `sunton_2432s028r_landscape` build now uses
   the full screen after the native-size fix.
2. Remove or gate the diagnostic color flash once bring-up is considered done.
3. Decide whether splash should stay disabled on this board or be reworked to
   use a smaller internal-SRAM canvas.
4. Calibrate and enable touch in `firmware/src/boards/sunton_2432s028/touch.cpp`.
5. Run BLE + daemon smoke testing once display bring-up is signed off.

## Practical next step

If the current flashed build still shows small margins or clipping, inspect the
panel offsets next in `display.cpp`. The controller family is now known, so the
next likely knob is not panel type but column/row offset or rotation-specific
start coordinates.
