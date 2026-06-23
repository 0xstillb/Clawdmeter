#include "../../hal/display_hal.h"
#include "board.h"
#include <Arduino.h>
#include <Arduino_GFX_Library.h>

namespace {
constexpr uint32_t BL_FREQ_HZ = 12000;
constexpr uint8_t BL_RES_BITS = 8;
constexpr int16_t PANEL_NATIVE_WIDTH = 240;
constexpr int16_t PANEL_NATIVE_HEIGHT = 320;

#if defined(CYD_LCD_ST7789)
constexpr const char* PANEL_VARIANT = "ST7789-v3";
#elif defined(CYD_LCD_ILI9341_TYPE2)
constexpr const char* PANEL_VARIANT = "ILI9341-v2";
#else
constexpr const char* PANEL_VARIANT = "ILI9341-v1";
#endif
}

static Arduino_DataBus* bus = nullptr;
static Arduino_TFT*     gfx = nullptr;

static void backlight_begin(void) {
    ledcAttach(LCD_BL, BL_FREQ_HZ, BL_RES_BITS);
    ledcWrite(LCD_BL, 200);
}

void display_hal_init(void) {
    bus = new Arduino_ESP32SPI(LCD_DC, LCD_CS, LCD_SCLK, LCD_MOSI, LCD_MISO, VSPI, true);

#if defined(CYD_LCD_ST7789)
    gfx = new Arduino_ST7789(
        bus, LCD_RESET, LCD_ROTATION, false,
        PANEL_NATIVE_WIDTH, PANEL_NATIVE_HEIGHT, 0, 0, 0, 0,
        st7789_type1_init_operations, sizeof(st7789_type1_init_operations));
#elif defined(CYD_LCD_ILI9341_TYPE2)
    gfx = new Arduino_ILI9341(
        bus, LCD_RESET, LCD_ROTATION, false,
        PANEL_NATIVE_WIDTH, PANEL_NATIVE_HEIGHT, 0, 0, 0, 0,
        ili9341_type2_init_operations, sizeof(ili9341_type2_init_operations));
#else
    gfx = new Arduino_ILI9341(
        bus, LCD_RESET, LCD_ROTATION, false,
        PANEL_NATIVE_WIDTH, PANEL_NATIVE_HEIGHT, 0, 0, 0, 0,
        ili9341_type1_init_operations, sizeof(ili9341_type1_init_operations));
#endif
}

void display_hal_begin(void) {
    backlight_begin();
    if (!gfx) return;
    const bool ok = gfx->begin();
    Serial.printf("display: begin=%d variant=%s rot=%d size=%dx%d\n",
                  ok ? 1 : 0, PANEL_VARIANT, LCD_ROTATION, LCD_WIDTH, LCD_HEIGHT);
}

void display_hal_set_brightness(uint8_t level) {
    ledcWrite(LCD_BL, level);
}

void display_hal_fill_screen(uint16_t color) {
    if (gfx) gfx->fillScreen(color);
}

void display_hal_draw_bitmap(int32_t x, int32_t y, int32_t w, int32_t h,
                             const uint16_t* pixels) {
    if (gfx) gfx->draw16bitRGBBitmap(x, y, (uint16_t*)pixels, w, h);
}

void display_hal_tick(void) {
    // No IMU-driven rotation on this board.
}

void display_hal_round_area(int32_t* x1, int32_t* y1, int32_t* x2, int32_t* y2) {
    (void)x1;
    (void)y1;
    (void)x2;
    (void)y2;
}
