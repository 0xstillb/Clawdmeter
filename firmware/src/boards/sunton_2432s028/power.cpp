#include "../../hal/power_hal.h"
#include "board.h"
#include <Arduino.h>

// This board has no dedicated power-management button. We reuse the BOOT key
// for the long-hold pair gesture only; short presses remain owned by input_hal
// for HID Space and intentionally do not cycle brightness.

namespace {
constexpr uint32_t PWR_POLL_MS = 30;
constexpr uint32_t PWR_LONG_MS = 1500;
}

static bool last_pressed = false;
static bool long_fired = false;
static bool pwr_long_flag = false;
static bool pwr_released_flag = false;
static uint32_t press_started_ms = 0;
static uint32_t last_poll_ms = 0;

void power_hal_init(void) {
    pinMode(BTN_BACK_GPIO, INPUT_PULLUP);
    last_pressed = (digitalRead(BTN_BACK_GPIO) == LOW);
    long_fired = false;
    pwr_long_flag = false;
    pwr_released_flag = false;
}

void power_hal_tick(void) {
    uint32_t now = millis();
    if (now - last_poll_ms < PWR_POLL_MS) return;
    last_poll_ms = now;

    bool pressed = (digitalRead(BTN_BACK_GPIO) == LOW);
    if (pressed && !last_pressed) {
        press_started_ms = now;
        long_fired = false;
    } else if (pressed && last_pressed) {
        if (!long_fired && (now - press_started_ms >= PWR_LONG_MS)) {
            pwr_long_flag = true;
            long_fired = true;
        }
    } else if (!pressed && last_pressed) {
        pwr_released_flag = true;
        long_fired = false;
    }

    last_pressed = pressed;
}

int  power_hal_battery_pct(void) { return -1; }
bool power_hal_is_charging(void) { return false; }
bool power_hal_is_vbus_in(void)  { return false; }   // no battery — USB always present, no PMU to detect
bool power_hal_pwr_pressed(void) { return false; }

bool power_hal_pwr_long_pressed(void) {
    if (pwr_long_flag) {
        pwr_long_flag = false;
        return true;
    }
    return false;
}

bool power_hal_pwr_released(void) {
    if (pwr_released_flag) {
        pwr_released_flag = false;
        return true;
    }
    return false;
}
