#include <Arduino.h>
#include <Wire.h>
#include <lvgl.h>
#include <esp_heap_caps.h>

#include "data.h"
#include "usage_payload.h"
#include "ui.h"
#include "ble.h"
#include "splash.h"
#include "usage_rate.h"
#include "idle.h"
#include "idle_cfg.h"
#include "brightness.h"

#include "hal/board_caps.h"
#include "hal/display_hal.h"
#include "hal/touch_hal.h"
#include "hal/input_hal.h"
#include "hal/power_hal.h"
#include "hal/imu_hal.h"

static UsageData usage = {};

static bool     touch_down = false;
static bool     touch_released = false;
static uint32_t touch_down_ms = 0;
static uint32_t touch_release_held_ms = 0;

static void note_touch_sample(bool pressed) {
    const uint32_t now = millis();
    if (pressed && !touch_down) {
        touch_down = true;
        touch_released = false;
        touch_down_ms = now;
        touch_release_held_ms = 0;
    } else if (!pressed && touch_down) {
        touch_down = false;
        touch_released = true;
        touch_release_held_ms = now - touch_down_ms;
    }
}

// ---- LVGL draw buffers (partial render mode) ----
// PSRAM-equipped boards (S3) can comfortably hold larger strips. PSRAM-free
// boards (e.g. ESP32-C6) allocate from internal SRAM, so we shrink the strip
// — 480×20 RGB565 = 19 KB × 2 buffers = 38 KB, fits beside everything else.
#ifdef BOARD_HAS_PSRAM
#define BUF_LINES 40
#define LV_BUF_CAPS (MALLOC_CAP_SPIRAM)
#else
#define BUF_LINES 20
#define LV_BUF_CAPS (MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)
#endif
static uint16_t* buf1 = nullptr;
static uint16_t* buf2 = nullptr;
static bool screenshot_stream_active = false;
static uint32_t screenshot_stream_bytes = 0;

static uint32_t my_tick(void) { return millis(); }

static void my_flush_cb(lv_display_t* disp, const lv_area_t* area, uint8_t* px_map) {
    int32_t w = area->x2 - area->x1 + 1;
    int32_t h = area->y2 - area->y1 + 1;
    display_hal_draw_bitmap(area->x1, area->y1, w, h, (uint16_t*)px_map);
    if (screenshot_stream_active) {
        const uint32_t tile_bytes = (uint32_t)w * (uint32_t)h * 2U;
        Serial.printf("SCREENSHOT_TILE %ld %ld %ld %ld %lu\n",
                      (long)area->x1, (long)area->y1, (long)w, (long)h,
                      (unsigned long)tile_bytes);
        Serial.flush();
        Serial.write(px_map, tile_bytes);
        Serial.flush();
        Serial.println();
        screenshot_stream_bytes += tile_bytes;
    }
    lv_display_flush_ready(disp);
}

static void rounder_cb(lv_event_t* e) {
    lv_area_t* area = (lv_area_t*)lv_event_get_param(e);
    display_hal_round_area(&area->x1, &area->y1, &area->x2, &area->y2);
}

// Touch policy is driven by IDLE_WAKE_ON_TOUCH:
//   true  → a press edge while asleep wakes the device and the first touch is
//           swallowed (mirrors the button wake-consumption); a press while
//           awake counts as activity.
//   false → touch never counts as activity and is fully swallowed while the
//           panel is dark, so pets/sleeves can't wake it overnight and LVGL
//           can't quietly toggle splash<->usage on a black panel.
// Wake-touch release flag (set by my_touch_cb when idle wake completes)
static bool wake_touch_release_seen = false;
static void my_touch_cb(lv_indev_t* indev, lv_indev_data_t* data) {
    uint16_t x, y;
    bool pressed;
    touch_hal_read(&x, &y, &pressed);
    const bool raw_pressed = pressed;

    if (IDLE_WAKE_ON_TOUCH) {
        static bool touch_was = false;
        static bool touch_wake_swallowed = false;
        if (raw_pressed && !touch_was) {
            // Press edge — consume as wake if asleep.
            if (idle_consume_wake_press()) {
                touch_wake_swallowed = true;
                pressed = false;
            }
        } else if (!raw_pressed && touch_was) {
            // Release edge.
            if (touch_wake_swallowed) {
                touch_wake_swallowed = false;
                pressed = false;
                wake_touch_release_seen = true;
            }
        } else if (raw_pressed && touch_wake_swallowed) {
            // Held finger through wake — keep hiding until release.
            pressed = false;
        }
        touch_was = raw_pressed;
    } else if (idle_is_asleep()) {
        pressed = false;
    }

    note_touch_sample(pressed);

    if (pressed) {
        data->point.x = x;
        data->point.y = y;
        data->state = LV_INDEV_STATE_PRESSED;
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

// ---- Serial command buffer ----
#define CMD_BUF_SIZE 64
static char cmd_buf[CMD_BUF_SIZE];
static int cmd_pos = 0;

static void send_screenshot_streamed(void) {
    const uint32_t w = board_caps().width;
    const uint32_t h = board_caps().height;
    const uint32_t raw_size = w * h * 2U;

    screenshot_stream_active = true;
    screenshot_stream_bytes = 0;

    Serial.printf("SCREENSHOT_BEGIN %lu %lu %lu\n",
                  (unsigned long)w, (unsigned long)h, (unsigned long)raw_size);
    Serial.flush();

    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(NULL);

    screenshot_stream_active = false;
    if (screenshot_stream_bytes != raw_size) {
        Serial.printf("SCREENSHOT_MISMATCH %lu %lu\n",
                      (unsigned long)screenshot_stream_bytes,
                      (unsigned long)raw_size);
    }
    Serial.println("SCREENSHOT_END");
}

static void send_screenshot() {
#ifndef BOARD_HAS_PSRAM
    send_screenshot_streamed();
#else
    const uint32_t w = board_caps().width;
    const uint32_t h = board_caps().height;
    const uint32_t row_bytes = w * 2;
    const uint32_t buf_size = row_bytes * h;
    uint8_t* sbuf = (uint8_t*)heap_caps_malloc(buf_size, MALLOC_CAP_SPIRAM);
    if (!sbuf) {
        Serial.println("SCREENSHOT_ERR");
        return;
    }

    lv_draw_buf_t draw_buf;
    lv_draw_buf_init(&draw_buf, w, h, LV_COLOR_FORMAT_RGB565, row_bytes, sbuf, buf_size);

    lv_result_t res = lv_snapshot_take_to_draw_buf(lv_screen_active(), LV_COLOR_FORMAT_RGB565, &draw_buf);
    if (res != LV_RESULT_OK) {
        heap_caps_free(sbuf);
        Serial.println("SCREENSHOT_ERR");
        return;
    }

    Serial.printf("SCREENSHOT_START %lu %lu %lu\n",
        (unsigned long)w, (unsigned long)h, (unsigned long)buf_size);
    Serial.flush();
    Serial.write(sbuf, buf_size);
    Serial.flush();
    Serial.println();
    Serial.println("SCREENSHOT_END");
    heap_caps_free(sbuf);
#endif
}

static void check_serial_cmd() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            cmd_buf[cmd_pos] = '\0';
            if (strcmp(cmd_buf, "screenshot") == 0) send_screenshot();
            cmd_pos = 0;
        } else if (cmd_pos < CMD_BUF_SIZE - 1) {
            cmd_buf[cmd_pos++] = c;
        }
    }
}

// Each board provides this. Must bring up the shared I2C bus (Wire.begin
// with the board's SDA/SCL pins) and any board-private hardware that has
// to settle before display/touch (e.g. an IO expander gating the LCD
// reset line). Called exactly once at the start of setup().
extern "C" void board_init(void);

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println("{\"ready\":true}");

    board_init();

    display_hal_init();
    display_hal_begin();
    idle_init();        // takes over panel brightness and starts the idle timer
    brightness_init();  // load the user's saved brightness level and apply via idle

    power_hal_init();
    imu_hal_init();
    touch_hal_init();

    // ---- LVGL ----
    const int W = board_caps().width;
    const int H = board_caps().height;

    lv_init();
    lv_tick_set_cb(my_tick);

    buf1 = (uint16_t*)heap_caps_malloc(W * BUF_LINES * 2, LV_BUF_CAPS);
    buf2 = (uint16_t*)heap_caps_malloc(W * BUF_LINES * 2, LV_BUF_CAPS);

    lv_display_t* disp = lv_display_create(W, H);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(disp, my_flush_cb);
    lv_display_set_buffers(disp, buf1, buf2, W * BUF_LINES * 2,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_add_event_cb(disp, rounder_cb, LV_EVENT_INVALIDATE_AREA, NULL);

    lv_indev_t* indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, my_touch_cb);

    ble_init();
    input_hal_init();

    ui_init();
    ui_update_ble_status(ble_get_state(), ble_get_device_name(), ble_get_mac_address());
    ui_update_battery(power_hal_battery_pct(), power_hal_is_charging());
    ui_show_screen(SCREEN_SPLASH);

    Serial.printf("Dashboard ready (%s, %dx%d), waiting for data on BLE...\n",
        board_caps().name, W, H);
}

static ble_state_t last_ble_state = BLE_STATE_INIT;

// Hold-to-pair gesture: hold the PWR button ~3s, then RELEASE → clear all BLE
// bonds and re-advertise. Clearing on *release* (not while held) is deliberate:
// holding to power the device OFF (AXP hardware shutdown at 8s) must not wipe
// the bond — a power-off hold never releases before shutdown. To stop a
// "chicken-out" release just before 8s from pairing, the gesture disarms at 6s.
//
//   ~1.5s long-press edge → PENDING
//   3.0s (+1500)          → ARMED   (release from here clears bonds)
//   6.0s (+4500)          → DISARMED (no clear; AXP powers off at 8s)
#define PAIR_ARM_AFTER_LONG_MS    1500   // 3.0s total
#define PAIR_DISARM_AFTER_LONG_MS 4500   // 6.0s total
enum pair_state_t { PAIR_IDLE, PAIR_PENDING, PAIR_ARMED };
static pair_state_t pair_state        = PAIR_IDLE;
static uint32_t     pair_long_seen_ms = 0;

static void pair_tick(void) {
    if (pair_state == PAIR_IDLE && power_hal_pwr_long_pressed()) {
        pair_state = PAIR_PENDING;
        pair_long_seen_ms = millis();
        (void)power_hal_pwr_released();  // drain any stale release edge
        Serial.println("PWR long-press: hold to ~3s then release to pair");
        return;
    }
    if (pair_state == PAIR_IDLE) return;

    if (power_hal_pwr_released()) {
        if (pair_state == PAIR_ARMED) {
            Serial.println("Pair: released in window — clearing bonds, advertising");
            ble_clear_bonds();
        } else {
            Serial.println("Pair: released too early — cancelled");
        }
        pair_state = PAIR_IDLE;
        return;
    }

    uint32_t held = millis() - pair_long_seen_ms;
    if (pair_state == PAIR_PENDING && held >= PAIR_ARM_AFTER_LONG_MS) {
        pair_state = PAIR_ARMED;
        Serial.println("Pair: armed — release to pair");
    } else if (pair_state == PAIR_ARMED && held >= PAIR_DISARM_AFTER_LONG_MS) {
        pair_state = PAIR_IDLE;  // power-off territory; don't pair
        Serial.println("Pair: disarmed (holding toward power-off)");
    }
}




// Touch hold UX state
static bool     touch_hold_active = false;
static uint32_t touch_hold_hint_clear = 0;
static constexpr uint32_t SPLASH_TAP_MAX_MS = 800;
static constexpr uint32_t SPLASH_PAIR_MS = 3000;
// Replaces splash_touch_tick() — handles all touch UX navigation:
//   Splash -> tap -> Usage (force view=2 if BLE connected)
//   Usage -> tap -> Splash  (via global_click_cb in ui.cpp)
//   Idle -> tap -> Usage (if BLE connected) else Splash
//   Idle (asleep) -> wake-tap -> Usage (if BLE connected) else Splash
//   Splash/Pairing -> hold 3s + release -> ble_clear_bonds()
static void touch_ux_tick(void) {
    const screen_t screen = ui_get_current_screen();
    const uint32_t now = millis();
    static uint32_t last_nav_ms = 0;

    // ---- 0. Navigation cooldown — ignore stale touch events within 400ms
    //         of the last UI navigation (prevents ghost-touch toggling from
    //         XPT2046 noise or carry-over events after screen switch)
    if (touch_released && now - last_nav_ms < 400) {
        touch_released = false;
    }
    if (wake_touch_release_seen && now - last_nav_ms < 400) {
        wake_touch_release_seen = false;
    }

    // Track last navigation time (macro to set at each navigation point)
    #define NAV_COOLDOWN() do { last_nav_ms = now; } while(0)

    // ---- 1. Hold progress (visual update while finger held down) ----
    if (touch_down && !wake_touch_release_seen) {
        const uint32_t held = now - touch_down_ms;
        if (held >= 500 && held < SPLASH_PAIR_MS &&
            (screen == SCREEN_SPLASH || (screen == SCREEN_USAGE && ui_get_view_state() == 0))) {
            touch_hold_active = true;
            char buf[32];
            int remaining = 3 - (int)(held / 1000);
            if (remaining < 1) remaining = 1;
            snprintf(buf, sizeof(buf), "Hold %ds to pair...", remaining);
            if (screen == SCREEN_SPLASH) splash_set_hint(buf);
        } else if (held >= SPLASH_PAIR_MS && touch_hold_active) {
            if (screen == SCREEN_SPLASH) splash_set_hint("Release to pair !");
        }
    }

    // ---- 2. Touch release ----
    if (touch_released) {
        const bool on_splash_or_pairing =
            screen == SCREEN_SPLASH ||
            (screen == SCREEN_USAGE && ui_get_view_state() == 0);

        if (touch_release_held_ms >= SPLASH_PAIR_MS && on_splash_or_pairing) {
            // Held >= 3s -> clear bonds
            Serial.println("Touch UX: 3s hold -> clearing bonds");
            ble_clear_bonds();
            touch_hold_active = false;
            if (screen == SCREEN_SPLASH) {
                splash_set_hint("Bonds cleared !");
                touch_hold_hint_clear = now + 2000;
            }
        } else if (touch_release_held_ms <= SPLASH_TAP_MAX_MS) {
            // Tap navigation
            touch_hold_active = false;
            if (screen == SCREEN_SPLASH) {
                // Only navigate if this touch started while already on Splash,
                // not carried over from a tap on Usage/Pairing that already
                // toggled screen via global_click_cb (stale release guard)
                if (touch_down_ms > ui_get_last_screen_change_time()) {
                    ui_show_screen(SCREEN_USAGE);
                    NAV_COOLDOWN();
                    if (ui_is_ble_connected()) {
                        ui_force_view(2);
                    }
                }
            } else if (screen == SCREEN_USAGE && ui_get_view_state() == 1) {
                // On idle (view=1) — tap -> Usage if BLE connected, else Splash
                // LVGL click events don't bubble from idle_canvas children to
                // usage_container, so global_click_cb won't fire for taps on
                // the creature. Handle via raw touch state instead.
                if (touch_down_ms > ui_get_last_screen_change_time()) {
                    if (ui_is_ble_connected()) {
                        ui_force_view(2);
                    } else {
                        ui_show_screen(SCREEN_SPLASH);
                    }
                    NAV_COOLDOWN();
                }
            }
            // Usage/Pairing -> Splash handled by global_click_cb in LVGL
        } else if (touch_release_held_ms > SPLASH_TAP_MAX_MS && touch_release_held_ms < SPLASH_PAIR_MS) {
            // Released in between mid-range -> cancel hold
            touch_hold_active = false;
            if (screen == SCREEN_SPLASH) splash_set_hint("tap to enter  /  hold 3s to pair");
        }

        touch_released = false;
    }

    // ---- 3. Idle wake-touch release (touch swallowed by my_touch_cb) ----
    if (wake_touch_release_seen) {
        wake_touch_release_seen = false;
        touch_hold_active = false;
        if (screen == SCREEN_USAGE) {
            if (ui_is_ble_connected()) {
                ui_force_view(2);
            } else {
                ui_show_screen(SCREEN_SPLASH);
            }
            NAV_COOLDOWN();
        }
    }

    // ---- 4. Hint reset after "Bonds cleared" ----
    if (touch_hold_hint_clear && now >= touch_hold_hint_clear) {
        touch_hold_hint_clear = 0;
        if (screen == SCREEN_SPLASH) splash_set_hint("tap to enter  /  hold 3s to pair");
    }
}
void loop() {
    idle_tick();
    lv_timer_handler();
    ui_tick_anim();
    ble_tick();
    power_hal_tick();
    imu_hal_tick();
    splash_tick();
    touch_ux_tick();
    // Rotation transition (blank + ramp) would fight the idle fade — skip
    // ticks while the panel is dark. A rotation that happens during sleep
    // is detected by the next tick after wake and ramped in then.
    if (!idle_is_asleep()) display_hal_tick();

    // ---- Physical buttons ----
    //   PRIMARY   → HID Space  (Claude Code voice-mode PTT)
    //   SECONDARY → HID Shift+Tab  (mode toggle; only if the board has one)
    //   Touch     → on splash: tap enters dashboard, hold ~3s + release
    //               clears BLE bonds for pairing.
    //   BOOT/PWR  → fallback physical controls on boards that expose them.
    // First press from sleep is consumed as a wake-only event by
    // idle_consume_wake_press(); the normal action fires from the second
    // press. Activity bookkeeping happens inside idle_consume_wake_press
    // so no separate idle_note_activity() call is needed here.
    {
        static bool primary_was = false;
        static bool primary_wake_swallowed = false;
        bool primary_now = input_hal_is_held(INPUT_BTN_PRIMARY);
        if (primary_now != primary_was) {
            if (primary_now) {
                if (idle_consume_wake_press()) primary_wake_swallowed = true;
                else                            ble_keyboard_press(0x2C, 0);  // HID Space, no mods
            } else {
                if (primary_wake_swallowed) primary_wake_swallowed = false;
                else                        ble_keyboard_release();
            }
            primary_was = primary_now;
        }

        if (board_caps().button_count >= 2) {
            static bool secondary_was = false;
            static bool secondary_wake_swallowed = false;
            bool secondary_now = input_hal_is_held(INPUT_BTN_SECONDARY);
            if (secondary_now != secondary_was) {
                if (secondary_now) {
                    if (idle_consume_wake_press()) secondary_wake_swallowed = true;
                    else                            ble_keyboard_press(0x2B, 0x02);  // HID Tab + LEFT_SHIFT
                } else {
                    if (secondary_wake_swallowed) secondary_wake_swallowed = false;
                    else                          ble_keyboard_release();
                }
                secondary_was = secondary_now;
            }
        }

        if (power_hal_pwr_pressed()) {
            if (!idle_consume_wake_press()) {
                // On splash: cycle animations. On the usage view: cycle
                // screen brightness (single non-splash view, no more screens).
                if (ui_get_current_screen() == SCREEN_SPLASH) splash_next();
                else                                          brightness_cycle();
            }
        }

        pair_tick();
    }

    ble_state_t bs = ble_get_state();
    if (bs != last_ble_state) {
        last_ble_state = bs;
        ui_update_ble_status(bs, ble_get_device_name(), ble_get_mac_address());
    }

    static int  last_pct      = -2;
    static bool last_charging = false;
    int  pct      = power_hal_battery_pct();
    bool charging = power_hal_is_charging();
    if (pct != last_pct || charging != last_charging) {
        last_pct = pct;
        last_charging = charging;
        ui_update_battery(pct, charging);
    }

    check_serial_cmd();

    if (ble_has_data()) {
        if (usage_parse_json(ble_get_data(), &usage)) {
            int g_before = usage_rate_group();
            float rate_pct = usage.top.pct;
            if (strcmp(usage.plan_type, "prepaid") == 0) {
                // Prepaid: animation follows remaining balance level
                splash_set_prepaid_balance((int)usage.bottom.pct);
            } else {
                // Subscription: top.pct is remaining % — invert to get used %
                rate_pct = 100.0f - rate_pct;
                usage_rate_sample(rate_pct);
                int g_after = usage_rate_group();
                if (g_after != g_before) {
                    Serial.printf("usage rate: group %d -> %d (s=%.2f%%)\n",
                        g_before, g_after, usage.top.pct);
                    if (splash_is_active()) splash_pick_for_current_rate();
                }
            }
            ui_update(&usage);
            ble_send_ack();
        } else {
            ble_send_nack();
        }
    }

    delay(5);
}
