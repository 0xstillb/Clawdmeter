#include "brightness.h"
#include "idle.h"
#include <Preferences.h>
#include <Arduino.h>

// Four-step ramp. The default (index 2) is 200 — identical to the prior
// hard-coded DISPLAY_DEFAULT_BRIGHTNESS, so cycling is purely additive.
static const uint8_t LEVELS[] = {64, 128, 200, 255};
#define LEVELS_COUNT (sizeof(LEVELS) / sizeof(LEVELS[0]))
#define DEFAULT_IDX  2

static uint8_t cur_idx = DEFAULT_IDX;
static uint8_t current_level = LEVELS[DEFAULT_IDX];

static uint8_t level_to_pct(uint8_t level) {
    return (uint8_t)(((uint16_t)level * 100U + 127U) / 255U);
}

static uint8_t pct_to_level(uint8_t pct) {
    return (uint8_t)(((uint16_t)pct * 255U + 50U) / 100U);
}

static uint8_t closest_level_idx(uint8_t level) {
    uint8_t closest = 0;
    int best_delta = 256;
    for (uint8_t i = 0; i < LEVELS_COUNT; ++i) {
        const int delta = abs((int)LEVELS[i] - (int)level);
        if (delta < best_delta) {
            closest = i;
            best_delta = delta;
        }
    }
    return closest;
}

void brightness_init(void) {
    Preferences prefs;
    prefs.begin("clawdmeter", true);
    uint8_t saved_pct = prefs.getUChar("brt_pct", 0xFF);
    uint8_t saved_idx = prefs.getUChar("brt_idx", 0xFF);
    prefs.end();

    if (saved_pct <= 100) {
        const uint8_t level = pct_to_level(saved_pct);
        cur_idx = closest_level_idx(level);
        current_level = level;
        idle_set_awake_brightness(level);
        Serial.printf("Brightness init: level=%u (%u%%)\n", level, saved_pct);
        return;
    }
    if (saved_idx < LEVELS_COUNT) cur_idx = saved_idx;
    current_level = LEVELS[cur_idx];
    idle_set_awake_brightness(current_level);
    Serial.printf("Brightness init: level=%u (idx=%u)\n", current_level, cur_idx);
}

void brightness_cycle(void) {
    cur_idx = (cur_idx + 1) % LEVELS_COUNT;
    current_level = LEVELS[cur_idx];

    Preferences prefs;
    prefs.begin("clawdmeter", false);
    prefs.putUChar("brt_idx", cur_idx);
    prefs.putUChar("brt_pct", level_to_pct(current_level));
    prefs.end();

    idle_set_awake_brightness(current_level);
    Serial.printf("Brightness cycled: level=%u (idx=%u)\n", current_level, cur_idx);
}

uint8_t brightness_get(void) {
    return current_level;
}

uint8_t brightness_get_pct(void) {
    return level_to_pct(brightness_get());
}

void brightness_set_pct(uint8_t pct) {
    if (pct > 100) pct = 100;
    const uint8_t level = pct_to_level(pct);
    cur_idx = closest_level_idx(level);
    current_level = level;

    Preferences prefs;
    prefs.begin("clawdmeter", false);
    prefs.putUChar("brt_pct", pct);
    prefs.end();

    idle_set_awake_brightness(level);
    Serial.printf("Brightness set: level=%u (%u%%)\n", level, pct);
}
