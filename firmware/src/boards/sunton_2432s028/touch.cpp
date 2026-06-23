#include "../../hal/touch_hal.h"
#include "board.h"
#include <Arduino.h>
#include <SPI.h>

namespace {
constexpr uint32_t TOUCH_SPI_HZ = 2500000;
constexpr uint8_t CMD_X = 0xD0;
constexpr uint8_t CMD_Y = 0x90;

// Typical CYD/XPT2046 raw ranges. If a panel revision is mirrored, these are
// the only values that should need tuning.
constexpr int RAW_X_MIN = 300;
constexpr int RAW_X_MAX = 3800;
constexpr int RAW_Y_MIN = 300;
constexpr int RAW_Y_MAX = 3800;

SPIClass touch_spi(HSPI);
SPISettings touch_settings(TOUCH_SPI_HZ, MSBFIRST, SPI_MODE0);

static int clamp_i32(int value, int low, int high) {
    if (value < low) return low;
    if (value > high) return high;
    return value;
}

static uint16_t read_axis(uint8_t cmd) {
    touch_spi.transfer(cmd);
    uint16_t hi = touch_spi.transfer(0x00);
    uint16_t lo = touch_spi.transfer(0x00);
    return (uint16_t)(((hi << 8) | lo) >> 3);
}

static uint16_t read_axis_avg(uint8_t cmd) {
    uint32_t sum = 0;
    constexpr int samples = 4;
    for (int i = 0; i < samples; ++i) sum += read_axis(cmd);
    return (uint16_t)(sum / samples);
}

static uint16_t map_raw(int raw, int in_min, int in_max, int out_min, int out_max) {
    const int lo = (in_min < in_max) ? in_min : in_max;
    const int hi = (in_min < in_max) ? in_max : in_min;
    raw = clamp_i32(raw, lo, hi);
    long value = map(raw, in_min, in_max, out_min, out_max);
    return (uint16_t)clamp_i32((int)value, out_min, out_max);
}
}

void touch_hal_init(void) {
    pinMode(TP_IRQ, INPUT);
    pinMode(TP_CS, OUTPUT);
    digitalWrite(TP_CS, HIGH);
    touch_spi.begin(TP_SCLK, TP_MISO, TP_MOSI, TP_CS);
    Serial.println("touch: XPT2046 init OK");
}

void touch_hal_read(uint16_t* x, uint16_t* y, bool* pressed) {
    if (digitalRead(TP_IRQ) == HIGH) {
        *pressed = false;
        return;
    }

    touch_spi.beginTransaction(touch_settings);
    digitalWrite(TP_CS, LOW);
    delayMicroseconds(2);
    const uint16_t raw_x = read_axis_avg(CMD_X);
    const uint16_t raw_y = read_axis_avg(CMD_Y);
    digitalWrite(TP_CS, HIGH);
    touch_spi.endTransaction();

#ifdef BOARD_LCD_LANDSCAPE
    *x = map_raw(raw_y, RAW_Y_MIN, RAW_Y_MAX, 0, LCD_WIDTH - 1);
    *y = map_raw(raw_x, RAW_X_MAX, RAW_X_MIN, 0, LCD_HEIGHT - 1);
#else
    *x = map_raw(raw_x, RAW_X_MIN, RAW_X_MAX, 0, LCD_WIDTH - 1);
    *y = map_raw(raw_y, RAW_Y_MIN, RAW_Y_MAX, 0, LCD_HEIGHT - 1);
#endif
    *pressed = true;
}
