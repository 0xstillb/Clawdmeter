#include "ui.h"
#include "usage_payload.h"
#include "splash.h"
#include "icons.h"
#include "theme.h"
#include "hal/board_caps.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <lvgl.h>

LV_FONT_DECLARE(font_ui_12);
LV_FONT_DECLARE(font_ui_14);
LV_FONT_DECLARE(font_ui_16);
LV_FONT_DECLARE(font_ui_11);
LV_FONT_DECLARE(font_ui_9);
LV_FONT_DECLARE(font_ui_bold_9);
LV_FONT_DECLARE(font_ui_bold_10);
LV_FONT_DECLARE(font_ui_bold_11);
LV_FONT_DECLARE(font_ui_bold_12);
LV_FONT_DECLARE(font_ui_bold_14);
LV_FONT_DECLARE(font_ui_bold_16);
LV_FONT_DECLARE(font_ui_bold_20);
LV_FONT_DECLARE(font_ui_bold_24);
LV_FONT_DECLARE(font_ui_bold_26);
LV_FONT_DECLARE(font_ui_bold_28);
LV_FONT_DECLARE(font_ui_bold_48);

#define COL_BG         THEME_BG
#define COL_SCREEN     lv_color_hex(0x050608)
#define COL_PANEL      THEME_PANEL
#define COL_PANEL_ALT  THEME_PANEL_ALT
#define COL_PANEL_EDGE THEME_PANEL_EDGE
#define COL_TEXT       THEME_TEXT
#define COL_DIM        THEME_DIM
#define COL_BLUE       THEME_BLUE
#define COL_YELLOW     THEME_YELLOW
#define COL_GREEN      THEME_GREEN
#define COL_ORANGE     THEME_ORANGE
#define COL_TRACK      THEME_TRACK

enum layout_mode_t {
    LAYOUT_PORTRAIT_SMALL,
    LAYOUT_LANDSCAPE_SMALL,
    LAYOUT_PORTRAIT_TALL,
    LAYOUT_LARGE,
};

struct Layout {
    layout_mode_t mode;
    int16_t scr_w;
    int16_t scr_h;
    int16_t pad_t;
    int16_t header_h;
    int16_t chip_x;
    int16_t chip_y;
    int16_t chip_w;
    int16_t chip_h;
    int16_t chip_radius;
    int16_t title_x;
    int16_t title_y;
    int16_t title_w;
    int16_t provider_y;
    int16_t bt_x;
    int16_t bt_y;
    int16_t agent_x;
    int16_t agent_y;
    int16_t agent_size;
    int16_t battery_x;
    int16_t battery_y;
    int16_t flow_x;
    int16_t flow_y;
    int16_t flow_w;
    int16_t flow_h;
    int16_t flow_dot;
    int16_t card_x;
    int16_t card2_x;
    int16_t card_w;
    int16_t card_h;
    int16_t card1_y;
    int16_t card2_y;
    int16_t card_radius;
    int16_t card_pad_l;
    int16_t card_pad_r;
    int16_t card_pad_t;
    int16_t card_pad_b;
    int16_t kicker_y;
    int16_t pct_y;
    int16_t pill_y;
    int16_t bar_y;
    int16_t bar_h;
    int16_t meta_y;
    int16_t meta_dot;
    int16_t meta_right_w;
    int16_t pair_hero_x;
    int16_t pair_hero_y;
    int16_t pair_hero_size;
    int16_t pair_steps_x;
    int16_t pair_steps_y;
    int16_t pair_step_w;
    int16_t pair_step_h;
    int16_t pair_step_gap;
    int16_t idle_creature_size;
    int16_t idle_creature_dy;
    int16_t idle_label_y;
    bool show_kicker;
    bool pair_row;
    const lv_font_t* title_font;
    const lv_font_t* provider_font;
    const lv_font_t* chip_font;
    const lv_font_t* kicker_font;
    const lv_font_t* metric_font;
    const lv_font_t* pill_font;
    const lv_font_t* meta_font;
    const lv_font_t* pair_font;
    const lv_font_t* idle_font;
};

struct PanelWidgets {
    lv_obj_t* root;
    lv_obj_t* kicker;
    lv_obj_t* pct;
    lv_obj_t* pill;
    lv_obj_t* bar;
    lv_obj_t* bar_fill;
    lv_obj_t* meta_dot;
    lv_obj_t* meta_left;
    lv_obj_t* meta_right;
};

static Layout L = {};
static lv_image_dsc_t battery_dscs[5];
static uint16_t brand_canvas_buf[54 * 54];
static uint16_t ble_canvas_buf[14 * 16];
static uint16_t pair_ble_canvas_buf[26 * 42];
static uint8_t idle_canvas_buf[20 * 20 * 3];  // RGB565A8: 2 bytes RGB + 1 byte alpha per pixel
static uint16_t agent_canvas_buf[28 * 28];
static uint16_t flow_canvas_buf[420 * 5];
static lv_obj_t* usage_container = nullptr;
static lv_obj_t* header_group = nullptr;
static lv_obj_t* brand_chip = nullptr;
static lv_obj_t* brand_canvas = nullptr;
static lv_obj_t* brand_chip_label = nullptr;
static lv_obj_t* lbl_title = nullptr;
static lv_obj_t* lbl_provider = nullptr;
static lv_obj_t* lbl_ble = nullptr;
static lv_obj_t* agent_badge = nullptr;
static lv_obj_t* agent_canvas = nullptr;
static lv_obj_t* battery_img = nullptr;
static lv_obj_t* usage_group = nullptr;
static lv_obj_t* pair_group = nullptr;
static lv_obj_t* idle_group = nullptr;
static lv_obj_t* idle_canvas = nullptr;
static lv_obj_t* idle_z_labels[4] = {nullptr, nullptr, nullptr, nullptr};
static lv_obj_t* flow_track = nullptr;
static lv_obj_t* flow_canvas = nullptr;
static lv_obj_t* flow_dot = nullptr;
static lv_obj_t* usage_bg_glow = nullptr;
static lv_obj_t* idle_label = nullptr;
static lv_obj_t* pair_steps[3] = {nullptr, nullptr, nullptr};
static PanelWidgets panel_top = {};
static PanelWidgets panel_bottom = {};

static const char HERMES_HEADER_FRAME[] =
    "00000000011100000000"
    "00000111100111000000"
    "00011111110011100000"
    "00011111000011010000"
    "01000012011201110000"
    "01111111111111111000"
    "01111101111011011000"
    "01110111111111111000"
    "01100001001101111000"
    "00010000001111111100"
    "00000000001111111100"
    "00000000001111111100"
    "00010000011111111100"
    "00010000011011111010"
    "10111001011011111011"
    "11111111011111111010"
    "10011111101111111111"
    "00101111010111111100"
    "00110111010100001100"
    "00001110000000000000";

// Sine wave LUT (48 steps, 0-255 range) for idle glow / breathe animations.
// Entry 0 = 128 (zero crossing), entry 12 = 255 (peak), entry 36 = 1 (trough).
static const uint8_t SINE_48[48] = {
    128, 144, 160, 176, 191, 205, 217, 228, 237, 245, 250, 253,
    255, 253, 250, 245, 237, 228, 217, 205, 191, 176, 160, 144,
    128, 111,  95,  79,  64,  50,  38,  27,  18,  10,   5,   2,
      1,   2,   5,  10,  18,  27,  38,  50,  64,  79,  95, 111,
};

static screen_t current_screen = SCREEN_USAGE;
static uint32_t s_last_screen_change = 0;
static bool s_ble_connected = false;
static bool data_received = false;
static int view_state = -1;  // 0 pair, 1 idle, 2 usage
static int forced_view_override = -1;
static uint32_t last_data_ms = 0;
static const uint32_t DATA_FRESH_MS = 120000;
static UsageData current_usage = {};
static uint8_t flow_anim_phase = 0;
static uint32_t flow_anim_ms = 0;
static uint32_t header_anim_ms = 0;
static uint8_t header_anim_phase = 0;
static uint32_t idle_anim_ms = 0;
static uint8_t idle_anim_phase = 0;
static uint32_t idle_glow_ms = 0;
static uint8_t idle_glow_phase = 0;
static uint32_t idle_breathe_ms = 0;
static uint8_t idle_breathe_phase = 0;
static uint32_t idle_base_scale = 0;
static uint32_t pair_scan_ms = 0;
static uint32_t idle_cursor_ms = 0;
static uint32_t card_glow_ms = 0;
static bool idle_cursor_on = true;
static lv_obj_t* idle_glow_obj = nullptr;
static lv_obj_t* pair_scan_ring = nullptr;
static lv_obj_t* pair_scan_rings[3] = {nullptr, nullptr, nullptr};
static int pair_scan_phase = 0;
static uint8_t card_glow_phase = 0;
static int16_t idle_glow_w = 0;
static int16_t idle_glow_h = 0;
static int16_t pair_scan_base = 0;

static void compute_layout(const BoardCaps& c) {
    memset(&L, 0, sizeof(L));
    L.scr_w = c.width;
    L.scr_h = c.height;

    if (c.width > c.height) {
        L.mode = LAYOUT_LANDSCAPE_SMALL;
        L.pad_t = 8;
        L.header_h = 64;
        L.chip_x = 10;
        L.chip_y = 7;
        L.chip_w = 60;
        L.chip_h = 58;
        L.chip_radius = 14;
        L.title_x = 72;
        L.title_y = 6;
        L.title_w = 160;
        L.provider_y = 36;
        L.bt_x = 266;
        L.bt_y = 18;
        L.agent_size = 22;
        L.agent_x = 286;
        L.agent_y = 16;
        L.battery_x = 230;
        L.battery_y = 12;
        L.flow_x = 10;
        L.flow_y = 68;
        L.flow_w = 300;
        L.flow_h = 2;
        L.flow_dot = 4;
        L.card_x = 10;
        L.card2_x = L.card_x;
        L.card_w = 300;
        L.card_h = 82;
        L.card1_y = 74;
        L.card2_y = 156;
        L.card_radius = 12;
        L.card_pad_l = 10;
        L.card_pad_r = 10;
        L.card_pad_t = 6;
        L.card_pad_b = 5;
        L.kicker_y = 0;
        L.pct_y = 12;
        L.pill_y = 4;
        L.bar_y = 45;
        L.bar_h = 9;
        L.meta_y = 61;
        L.meta_dot = 6;
        L.meta_right_w = 78;
        L.pair_hero_x = 22;
        L.pair_hero_y = 98;
        L.pair_hero_size = 90;
        L.pair_steps_x = 136;
        L.pair_steps_y = 100;
        L.pair_step_w = 148;
        L.pair_step_h = 21;
        L.pair_step_gap = 6;
        L.idle_creature_size = 140;
        L.idle_creature_dy = -6;
        L.idle_label_y = -8;
        L.show_kicker = false;
        L.pair_row = true;
        L.title_font = &font_ui_bold_24;
        L.provider_font = &font_ui_bold_10;
        L.chip_font = &font_ui_bold_24;
        L.kicker_font = &font_ui_bold_10;
        L.metric_font = &font_ui_bold_24;
        L.pill_font = &font_ui_bold_10;
        L.meta_font = &font_ui_11;
        L.pair_font = &font_ui_bold_11;
        L.idle_font = &font_ui_12;
    } else if (c.height <= 340) {
        L.mode = LAYOUT_PORTRAIT_SMALL;
        L.pad_t = 12;
        L.header_h = 68;
        L.chip_x = 12;
        L.chip_y = 12;
        L.chip_w = 62;
        L.chip_h = 60;
        L.chip_radius = 16;
        L.title_x = 80;
        L.title_y = 16;
        L.title_w = 104;
        L.provider_y = 42;
        L.bt_x = 189;
        L.bt_y = 24;
        L.agent_size = 18;
        L.agent_x = 210;
        L.agent_y = 21;
        L.battery_x = 184;
        L.battery_y = 18;
        L.flow_x = 12;
        L.flow_y = 78;
        L.flow_w = 211;
        L.flow_h = 3;
        L.flow_dot = 5;
        L.card_x = 12;
        L.card2_x = L.card_x;
        L.card_w = 216;
        L.card_h = 78;
        L.card1_y = 86;
        L.card2_y = 172;
        L.card_radius = 12;
        L.card_pad_l = 10;
        L.card_pad_r = 10;
        L.card_pad_t = 8;
        L.card_pad_b = 6;
        L.kicker_y = 0;
        L.pct_y = 14;
        L.pill_y = 2;
        L.bar_y = 41;
        L.bar_h = 12;
        L.meta_y = 59;
        L.meta_dot = 6;
        L.meta_right_w = 84;
        L.pair_hero_x = 80;
        L.pair_hero_y = 102;
        L.pair_hero_size = 80;
        L.pair_steps_x = 44;
        L.pair_steps_y = 194;
        L.pair_step_w = 152;
        L.pair_step_h = 18;
        L.pair_step_gap = 6;
        L.idle_creature_size = 156;
        L.idle_creature_dy = -2;
        L.idle_label_y = -8;
        L.show_kicker = true;
        L.pair_row = false;
        L.title_font = &font_ui_bold_20;
        L.provider_font = &font_ui_bold_12;
        L.chip_font = &font_ui_bold_24;
        L.kicker_font = &font_ui_bold_12;
        L.metric_font = &font_ui_bold_28;
        L.pill_font = &font_ui_bold_14;
        L.meta_font = &font_ui_12;
        L.pair_font = &font_ui_12;
        L.idle_font = &font_ui_14;
    } else if (c.height >= 460) {
        L.mode = LAYOUT_LARGE;
        L.pad_t = 22;
        L.header_h = 98;
        L.chip_x = 22;
        L.chip_y = 22;
        L.chip_w = 82;
        L.chip_h = 82;
        L.chip_radius = 18;
        L.title_x = 118;
        L.title_y = 30;
        L.title_w = 230;
        L.provider_y = 70;
        L.bt_x = 380;
        L.bt_y = 34;
        L.agent_size = 28;
        L.agent_x = 414;
        L.agent_y = 30;
        L.battery_x = 358;
        L.battery_y = 26;
        L.flow_x = 22;
        L.flow_y = 116;
        L.flow_w = 410;
        L.flow_h = 5;
        L.flow_dot = 8;
        L.card_x = 22;
        L.card2_x = L.card_x;
        L.card_w = 436;
        L.card_h = 142;
        L.card1_y = 132;
        L.card2_y = 290;
        L.card_radius = 18;
        L.card_pad_l = 18;
        L.card_pad_r = 18;
        L.card_pad_t = 16;
        L.card_pad_b = 14;
        L.kicker_y = 0;
        L.pct_y = 24;
        L.pill_y = 6;
        L.bar_y = 80;
        L.bar_h = 18;
        L.meta_y = 110;
        L.meta_dot = 8;
        L.meta_right_w = 170;
        L.pair_hero_x = 46;
        L.pair_hero_y = 176;
        L.pair_hero_size = 132;
        L.pair_steps_x = 212;
        L.pair_steps_y = 182;
        L.pair_step_w = 200;
        L.pair_step_h = 28;
        L.pair_step_gap = 12;
        L.idle_creature_size = 208;
        L.idle_creature_dy = -18;
        L.idle_label_y = -22;
        L.show_kicker = true;
        L.pair_row = true;
        L.title_font = &font_ui_bold_28;
        L.provider_font = &font_ui_bold_16;
        L.chip_font = &font_ui_bold_28;
        L.kicker_font = &font_ui_bold_16;
        L.metric_font = &font_ui_bold_48;
        L.pill_font = &font_ui_bold_20;
        L.meta_font = &font_ui_14;
        L.pair_font = &font_ui_16;
        L.idle_font = &font_ui_16;
    } else {
        L.mode = LAYOUT_PORTRAIT_TALL;
        L.pad_t = 20;
        L.header_h = 88;
        L.chip_x = 20;
        L.chip_y = 20;
        L.chip_w = 72;
        L.chip_h = 72;
        L.chip_radius = 18;
        L.title_x = 102;
        L.title_y = 28;
        L.title_w = 176;
        L.provider_y = 60;
        L.bt_x = 296;
        L.bt_y = 30;
        L.agent_size = 24;
        L.agent_x = 322;
        L.agent_y = 27;
        L.battery_x = 274;
        L.battery_y = 23;
        L.flow_x = 20;
        L.flow_y = 102;
        L.flow_w = 318;
        L.flow_h = 4;
        L.flow_dot = 7;
        L.card_x = 20;
        L.card2_x = L.card_x;
        L.card_w = 328;
        L.card_h = 118;
        L.card1_y = 116;
        L.card2_y = 246;
        L.card_radius = 16;
        L.card_pad_l = 16;
        L.card_pad_r = 16;
        L.card_pad_t = 14;
        L.card_pad_b = 12;
        L.kicker_y = 0;
        L.pct_y = 18;
        L.pill_y = 6;
        L.bar_y = 62;
        L.bar_h = 16;
        L.meta_y = 90;
        L.meta_dot = 7;
        L.meta_right_w = 136;
        L.pair_hero_x = 118;
        L.pair_hero_y = 154;
        L.pair_hero_size = 108;
        L.pair_steps_x = 84;
        L.pair_steps_y = 274;
        L.pair_step_w = 200;
        L.pair_step_h = 24;
        L.pair_step_gap = 10;
        L.idle_creature_size = 188;
        L.idle_creature_dy = -10;
        L.idle_label_y = -16;
        L.show_kicker = true;
        L.pair_row = false;
        L.title_font = &font_ui_bold_28;
        L.provider_font = &font_ui_bold_14;
        L.chip_font = &font_ui_bold_28;
        L.kicker_font = &font_ui_bold_14;
        L.metric_font = &font_ui_bold_48;
        L.pill_font = &font_ui_bold_16;
        L.meta_font = &font_ui_14;
        L.pair_font = &font_ui_14;
        L.idle_font = &font_ui_14;
    }
}

static void init_icon_dsc_rgb565a8(lv_image_dsc_t* dsc, int w, int h, const uint8_t* data) {
    dsc->header.w = w;
    dsc->header.h = h;
    dsc->header.cf = LV_COLOR_FORMAT_RGB565A8;
    dsc->header.stride = w * 2;
    dsc->data = data;
    dsc->data_size = w * h * 3;
}

static void init_battery_icons(void) {
    init_icon_dsc_rgb565a8(&battery_dscs[0], ICON_BATTERY_W, ICON_BATTERY_H, icon_battery_data);
    init_icon_dsc_rgb565a8(&battery_dscs[1], ICON_BATTERY_LOW_W, ICON_BATTERY_LOW_H, icon_battery_low_data);
    init_icon_dsc_rgb565a8(&battery_dscs[2], ICON_BATTERY_MEDIUM_W, ICON_BATTERY_MEDIUM_H, icon_battery_medium_data);
    init_icon_dsc_rgb565a8(&battery_dscs[3], ICON_BATTERY_FULL_W, ICON_BATTERY_FULL_H, icon_battery_full_data);
    init_icon_dsc_rgb565a8(&battery_dscs[4], ICON_BATTERY_CHARGING_W, ICON_BATTERY_CHARGING_H, icon_battery_charging_data);
}

static uint16_t make_rgb565(uint8_t r, uint8_t g, uint8_t b) {
    return ((uint16_t)(r & 0xf8) << 8) | ((uint16_t)(g & 0xfc) << 3) | (b >> 3);
}

static uint16_t blend_rgb565(uint16_t bg, uint16_t fg, uint8_t alpha) {
    const uint8_t bg_r = (uint8_t)(((bg >> 11) & 0x1f) * 255 / 31);
    const uint8_t bg_g = (uint8_t)(((bg >> 5) & 0x3f) * 255 / 63);
    const uint8_t bg_b = (uint8_t)((bg & 0x1f) * 255 / 31);
    const uint8_t fg_r = (uint8_t)(((fg >> 11) & 0x1f) * 255 / 31);
    const uint8_t fg_g = (uint8_t)(((fg >> 5) & 0x3f) * 255 / 63);
    const uint8_t fg_b = (uint8_t)((fg & 0x1f) * 255 / 31);

    const uint8_t out_r = (uint8_t)((bg_r * (255 - alpha) + fg_r * alpha) / 255);
    const uint8_t out_g = (uint8_t)((bg_g * (255 - alpha) + fg_g * alpha) / 255);
    const uint8_t out_b = (uint8_t)((bg_b * (255 - alpha) + fg_b * alpha) / 255);
    return make_rgb565(out_r, out_g, out_b);
}

static void draw_square_565(uint16_t* buf, int w, int h, int cx, int cy, int size, uint16_t color) {
    const int r = size / 2;
    for (int y = cy - r; y <= cy + r; ++y) {
        if (y < 0 || y >= h) continue;
        for (int x = cx - r; x <= cx + r; ++x) {
            if (x < 0 || x >= w) continue;
            buf[y * w + x] = color;
        }
    }
}

static void draw_rect_565(uint16_t* buf, int w, int h, int x0, int y0, int rw, int rh, uint16_t color) {
    for (int y = y0; y < y0 + rh; ++y) {
        if (y < 0 || y >= h) continue;
        for (int x = x0; x < x0 + rw; ++x) {
            if (x < 0 || x >= w) continue;
            buf[y * w + x] = color;
        }
    }
}

static void render_hermes_header_icon(int mode, uint8_t phase) {
    const uint16_t bg = make_rgb565(0x05, 0x06, 0x08);
    const uint16_t blue = make_rgb565(0x5a, 0x7a, 0xff);
    const uint16_t yellow = make_rgb565(0xff, 0xd5, 0x3d);
    const uint16_t body = make_rgb565(0xec, 0xe6, 0xdb);
    const uint16_t shade = make_rgb565(0xde, 0xda, 0xd0);

    for (int i = 0; i < 54 * 54; ++i) brand_canvas_buf[i] = bg;

    for (int sy = 0; sy < 20; ++sy) {
        for (int sx = 0; sx < 20; ++sx) {
            char code = HERMES_HEADER_FRAME[sy * 20 + sx];
            if (code == '0') continue;
            const int x = (sx * 27 + 5) / 10;
            const int y = (sy * 27 + 5) / 10;
            draw_rect_565(brand_canvas_buf, 54, 54, x, y, 3, 3, code == '2' ? shade : body);
        }
    }

    if (mode == 2) {
        for (int i = 0; i < 5; ++i) {
            const int ph = (phase + i * 8) % 40;
            if (ph >= 30) continue;
            draw_square_565(brand_canvas_buf, 54, 54, 38 + i * 3, 10 + (ph * 24) / 40, ph < 20 ? 3 : 2, yellow);
        }
    } else if (mode == 0) {
        static const int orbit[][2] = {
            {51, 27}, {48, 39}, {39, 48}, {27, 51}, {15, 48}, {6, 39},
            {3, 27}, {6, 15}, {15, 6}, {27, 3}, {39, 6}, {48, 15},
        };
        const int a = phase % 12;
        const int b = (a + 6) % 12;
        draw_square_565(brand_canvas_buf, 54, 54, orbit[a][0], orbit[a][1], 5, blue);
        draw_square_565(brand_canvas_buf, 54, 54, orbit[b][0], orbit[b][1], 3, blue);
    }

    if (brand_canvas) lv_obj_invalidate(brand_canvas);
}

static void render_hermes_idle_icon(uint8_t phase) {
    const uint8_t dim = 190 + (phase < 24 ? phase : 48 - phase);
    const uint16_t body = make_rgb565((0xec * dim) / 214, (0xe6 * dim) / 214, (0xdb * dim) / 214);
    const uint16_t shade = make_rgb565((0xde * dim) / 214, (0xda * dim) / 214, (0xd0 * dim) / 214);

    uint16_t* rgb = reinterpret_cast<uint16_t*>(idle_canvas_buf);
    uint8_t* alpha = idle_canvas_buf + 20 * 20 * 2;
    for (int i = 0; i < 20 * 20; ++i) {
        const char code = HERMES_HEADER_FRAME[i];
        if (code == '0') {
            rgb[i] = 0;          // RGB value doesn't matter when alpha=0
            alpha[i] = 0;        // fully transparent
        } else {
            rgb[i] = (code == '2') ? shade : body;
            alpha[i] = 255;      // fully opaque
        }
    }

    if (idle_canvas) lv_obj_invalidate(idle_canvas);
}

static void draw_line_565(uint16_t* buf, int w, int h, int x0, int y0, int x1, int y1, uint16_t color) {
    int dx = abs(x1 - x0);
    int sx = x0 < x1 ? 1 : -1;
    int dy = -abs(y1 - y0);
    int sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    while (true) {
        if (x0 >= 0 && x0 < w && y0 >= 0 && y0 < h) buf[y0 * w + x0] = color;
        if (x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}

static void draw_line_thick_565(uint16_t* buf, int w, int h, int x0, int y0, int x1, int y1, uint16_t color, int thickness) {
    for (int o = -thickness / 2; o <= thickness / 2; ++o) {
        draw_line_565(buf, w, h, x0 + o, y0, x1 + o, y1, color);
        draw_line_565(buf, w, h, x0, y0 + o, x1, y1 + o, color);
    }
}

static void render_ble_icon(void) {
    const uint16_t bg = make_rgb565(0x05, 0x06, 0x08);
    const uint16_t blue = make_rgb565(0x5a, 0x7a, 0xff);
    for (int i = 0; i < 14 * 16; ++i) ble_canvas_buf[i] = bg;

    draw_line_thick_565(ble_canvas_buf, 14, 16, 7, 0, 7, 15, blue, 1);
    draw_line_thick_565(ble_canvas_buf, 14, 16, 3, 4, 10, 10, blue, 1);
    draw_line_thick_565(ble_canvas_buf, 14, 16, 10, 4, 3, 10, blue, 1);
}

static void render_pair_ble_icon(void) {
    const uint16_t bg = make_rgb565(0x05, 0x06, 0x08);
    const uint16_t blue = make_rgb565(0x5a, 0x7a, 0xff);
    for (int i = 0; i < 26 * 42; ++i) pair_ble_canvas_buf[i] = bg;

    draw_line_thick_565(pair_ble_canvas_buf, 26, 42, 13, 0, 13, 41, blue, 3);
    draw_line_thick_565(pair_ble_canvas_buf, 26, 42, 5, 10, 21, 25, blue, 3);
    draw_line_thick_565(pair_ble_canvas_buf, 26, 42, 21, 10, 5, 25, blue, 3);
}

static void render_agent_badge_icon(bool connected) {
    const int size = L.agent_size > 0 ? L.agent_size : 22;
    const uint16_t screen_bg = make_rgb565(0x0d, 0x10, 0x16);
    const uint16_t accent = make_rgb565(connected ? 0x34 : 0xff, connected ? 0xb5 : 0xaa, connected ? 0x5a : 0x77);
    const uint16_t bg = blend_rgb565(screen_bg, accent, connected ? 31 : 38);
    const uint16_t fg = accent;

    for (int i = 0; i < size * size; ++i) agent_canvas_buf[i] = bg;

    const int dot = size <= 18 ? 4 : 5;
    const int pad = size <= 18 ? 3 : 4;
    const int left = pad;
    const int right = size - pad - dot;
    const int top = pad;
    const int bottom = size - pad - dot;
    const int mid_x = (size - dot) / 2;
    const int mid_y = (top + bottom) / 2;

    draw_rect_565(agent_canvas_buf, size, size, left, top, dot, dot, fg);
    draw_rect_565(agent_canvas_buf, size, size, right, top, dot, dot, fg);
    draw_rect_565(agent_canvas_buf, size, size, mid_x, bottom, dot, dot, fg);

    draw_line_thick_565(agent_canvas_buf, size, size, left + dot - 1, top + 2, right, top + 2, fg, 1);
    draw_line_thick_565(agent_canvas_buf, size, size, left + dot - 1, top + dot, mid_x + 1, bottom, fg, 1);
    draw_line_thick_565(agent_canvas_buf, size, size, right, top + dot, mid_x + dot - 1, bottom, fg, 1);
    draw_line_thick_565(agent_canvas_buf, size, size, left + 1, mid_y, right - 1, mid_y, fg, 1);

    if (!connected) {
        draw_line_thick_565(agent_canvas_buf, size, size, size / 2 + 1, 3, size / 2 - 2, size - 4, fg, 1);
    }

    if (agent_canvas) lv_obj_invalidate(agent_canvas);
}

static void render_flow_line(uint8_t phase) {
    if (!flow_canvas) return;

    const int w = L.flow_w;
    const int h = L.flow_h;
    const uint16_t base = make_rgb565(0x1f, 0x24, 0x2c);
    const uint16_t edge = make_rgb565(0x2b, 0x31, 0x3b);
    const uint16_t glow = make_rgb565(0x72, 0x95, 0xff);

    const int radius = (w * 26) / 100;
    const int travel = w + radius * 2;
    const int center = -radius + (int)(((int32_t)travel * phase) / 47);

    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const int dist = abs(x - center);
            uint16_t color = blend_rgb565(base, edge, 90);
            if (dist < radius) {
                const uint32_t t = 255u - (uint32_t)(dist * 255) / (uint32_t)radius;
                const uint8_t a = (uint8_t)((t * t) / 255u);  // softer falloff near the tail
                color = blend_rgb565(color, glow, a);
            }
            flow_canvas_buf[y * w + x] = color;
        }
    }

    lv_obj_invalidate(flow_canvas);
}

static const char* provider_text(UsageProvider provider) {
    switch (provider) {
        case USAGE_PROVIDER_CLAUDE: return "CLAUDE";
        case USAGE_PROVIDER_CODEX: return "CODEX";
        case USAGE_PROVIDER_OPENROUTER: return "OPENROUTER";
        case USAGE_PROVIDER_ZEN: return "ZEN";
        case USAGE_PROVIDER_GO: return "OPENCODE GO";
        default: return "NO DATA";
    }
}

static void snake_to_words(const char* src, char* dst, size_t dst_size) {
    if (!dst_size) return;
    if (!src || !src[0]) {
        snprintf(dst, dst_size, "awaiting data");
        return;
    }

    size_t out = 0;
    for (size_t i = 0; src[i] && out + 1 < dst_size; ++i) {
        char ch = src[i];
        dst[out++] = (ch == '_') ? ' ' : ch;
    }
    dst[out] = '\0';
}

static void format_panel_heading(const UsagePanelData* panel, bool top, char* buf, size_t buf_size) {
    if (!panel || !panel->valid) {
        snprintf(buf, buf_size, "%s", top ? "Current window" : "Weekly cap");
        return;
    }

    if (strcmp(panel->kind, "window_short") == 0) {
        snprintf(buf, buf_size, "Current window");
    } else if (strcmp(panel->kind, "window_long") == 0) {
        snprintf(buf, buf_size, "Weekly cap");
    } else if (strcmp(panel->kind, "budget_daily") == 0) {
        snprintf(buf, buf_size, "Daily budget");
    } else if (strcmp(panel->kind, "wallet_depletion") == 0) {
        snprintf(buf, buf_size, "Wallet balance");
    } else if (panel->label[0]) {
        snprintf(buf, buf_size, "%s", panel->label);
    } else {
        snprintf(buf, buf_size, "%s", top ? "Current window" : "Weekly cap");
    }
}

static void format_panel_meta_left(const UsagePanelData* panel, bool top, char* buf, size_t buf_size) {
    if (!panel || !panel->valid) {
        snprintf(buf, buf_size, "%s", L.mode == LAYOUT_LANDSCAPE_SMALL ? "awaiting" : "awaiting data");
        return;
    }

    if (L.mode == LAYOUT_LANDSCAPE_SMALL && strcmp(panel->kind, "window_short") == 0) {
        snprintf(buf, buf_size, "left_now");
    } else if (L.mode == LAYOUT_LANDSCAPE_SMALL && strcmp(panel->kind, "window_long") == 0) {
        snprintf(buf, buf_size, "week_left");
    } else if (strcmp(panel->kind, "window_short") == 0) {
        snprintf(buf, buf_size, "window left");
    } else if (strcmp(panel->kind, "window_long") == 0) {
        snprintf(buf, buf_size, "week left");
    } else if (strcmp(panel->kind, "budget_daily") == 0) {
        snprintf(buf, buf_size, "day left");
    } else if (strcmp(panel->kind, "wallet_depletion") == 0) {
        snprintf(buf, buf_size, "wallet left");
    } else if (panel->kind[0]) {
        snake_to_words(panel->kind, buf, buf_size);
    } else if (panel->label[0]) {
        snprintf(buf, buf_size, "%s", panel->label);
    } else {
        snprintf(buf, buf_size, "%s", top ? "usage" : "cap");
    }
}

static void format_panel_meta_right(const UsagePanelData* panel, char* buf, size_t buf_size) {
    if (!panel || !panel->valid) {
        snprintf(buf, buf_size, "---");
        return;
    }

    if (L.mode != LAYOUT_LANDSCAPE_SMALL) {
        usage_panel_display_subtext(panel, buf, buf_size);
        return;
    }

    if (!panel->has_reset) {
        snprintf(buf, buf_size, "%s", panel->subtext[0] ? panel->subtext : "---");
        return;
    }

    if (panel->reset_mins < 0) {
        snprintf(buf, buf_size, "---");
    } else if (panel->reset_mins < 1440) {
        snprintf(buf, buf_size, "reset: %02dh%02dm", panel->reset_mins / 60, panel->reset_mins % 60);
    } else {
        snprintf(buf, buf_size, "reset: %dd%02dh", panel->reset_mins / 1440, (panel->reset_mins % 1440) / 60);
    }
}

static const char* default_pill_text(bool top) {
    return top ? "Current" : "Weekly";
}

static lv_obj_t* make_transparent_box(lv_obj_t* parent, int x, int y, int w, int h) {
    lv_obj_t* obj = lv_obj_create(parent);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_size(obj, w, h);
    lv_obj_set_style_bg_opa(obj, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(obj, 0, 0);
    lv_obj_set_style_pad_all(obj, 0, 0);
    lv_obj_clear_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(obj, LV_OBJ_FLAG_EVENT_BUBBLE);
    return obj;
}

static void build_screen_grid(lv_obj_t* parent) {
    if (L.mode != LAYOUT_LANDSCAPE_SMALL) return;

    for (int x = 0; x < L.scr_w; x += 14) {
        lv_obj_t* line = lv_obj_create(parent);
        lv_obj_set_pos(line, x, 0);
        lv_obj_set_size(line, 1, L.scr_h);
        lv_obj_set_style_bg_color(line, lv_color_hex(0xffffff), 0);
        lv_obj_set_style_bg_opa(line, (lv_opa_t)12, 0);
        lv_obj_set_style_border_width(line, 0, 0);
        lv_obj_set_style_pad_all(line, 0, 0);
        lv_obj_clear_flag(line, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_flag(line, LV_OBJ_FLAG_EVENT_BUBBLE);
    }

    for (int y = 0; y < L.scr_h; y += 14) {
        lv_obj_t* line = lv_obj_create(parent);
        lv_obj_set_pos(line, 0, y);
        lv_obj_set_size(line, L.scr_w, 1);
        lv_obj_set_style_bg_color(line, lv_color_hex(0xffffff), 0);
        lv_obj_set_style_bg_opa(line, (lv_opa_t)12, 0);
        lv_obj_set_style_border_width(line, 0, 0);
        lv_obj_set_style_pad_all(line, 0, 0);
        lv_obj_clear_flag(line, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_flag(line, LV_OBJ_FLAG_EVENT_BUBBLE);
    }
}

static void style_card_shell(lv_obj_t* panel, lv_color_t accent) {
    const bool landscape = L.mode == LAYOUT_LANDSCAPE_SMALL;
    const bool secondary = lv_color_eq(accent, COL_YELLOW);
    lv_color_t top = landscape ? lv_color_hex(0x313844) : COL_PANEL;
    lv_color_t bottom = landscape ? lv_color_hex(0x171c24) : COL_PANEL_ALT;
    if (secondary && landscape) {
        top = lv_color_hex(0x343941);
        bottom = lv_color_hex(0x191d23);
    }

    lv_obj_set_style_bg_color(panel, top, 0);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_grad_color(panel, bottom, 0);
    lv_obj_set_style_bg_grad_dir(panel, LV_GRAD_DIR_VER, 0);
    lv_obj_set_style_radius(panel, L.card_radius, 0);
    lv_obj_set_style_border_width(panel, 1, 0);
    lv_obj_set_style_border_color(panel, accent, 0);
    lv_obj_set_style_border_opa(panel, landscape ? (lv_opa_t)108 : LV_OPA_COVER, 0);
    lv_obj_set_style_shadow_width(panel, landscape ? 18 : 0, 0);
    lv_obj_set_style_shadow_color(panel, accent, 0);
    lv_obj_set_style_shadow_opa(panel, landscape ? (lv_opa_t)42 : LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_left(panel, L.card_pad_l, 0);
    lv_obj_set_style_pad_right(panel, L.card_pad_r, 0);
    lv_obj_set_style_pad_top(panel, L.card_pad_t, 0);
    lv_obj_set_style_pad_bottom(panel, L.card_pad_b, 0);
}

static void style_pill(lv_obj_t* pill, lv_color_t accent) {
    lv_obj_set_style_text_font(pill, L.pill_font, 0);
    const bool secondary = lv_color_eq(accent, COL_YELLOW);
    lv_color_t text = secondary ? lv_color_hex(0xffe998) : lv_color_hex(0xa8c0ff);
    lv_color_t bg = secondary ? lv_color_hex(0x352f19) : lv_color_hex(0x1d2540);
    lv_obj_set_style_text_color(pill, L.mode == LAYOUT_LANDSCAPE_SMALL ? text : COL_TEXT, 0);
    lv_obj_set_style_bg_color(pill, L.mode == LAYOUT_LANDSCAPE_SMALL ? bg : COL_PANEL_ALT, 0);
    lv_obj_set_style_bg_opa(pill, L.mode == LAYOUT_LANDSCAPE_SMALL ? (lv_opa_t)166 : LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(pill, 1, 0);
    lv_obj_set_style_border_color(pill, accent, 0);
    lv_obj_set_style_border_opa(pill, L.mode == LAYOUT_LANDSCAPE_SMALL ? (lv_opa_t)108 : LV_OPA_COVER, 0);
    lv_obj_set_style_radius(pill, LV_RADIUS_CIRCLE, 0);
    if (L.mode == LAYOUT_LANDSCAPE_SMALL) {
        lv_obj_set_style_pad_left(pill, 8, 0);
        lv_obj_set_style_pad_right(pill, 8, 0);
        lv_obj_set_style_pad_top(pill, 2, 0);
        lv_obj_set_style_pad_bottom(pill, 2, 0);
    } else {
        lv_obj_set_style_pad_left(pill, 10, 0);
        lv_obj_set_style_pad_right(pill, 10, 0);
        lv_obj_set_style_pad_top(pill, 3, 0);
        lv_obj_set_style_pad_bottom(pill, 3, 0);
    }
}

static lv_obj_t* make_bar(lv_obj_t* parent, int y, lv_color_t accent, lv_obj_t** fill_out) {
    lv_obj_t* bar = lv_obj_create(parent);
    const bool secondary = lv_color_eq(accent, COL_YELLOW);
    const lv_color_t fill_start = secondary ? lv_color_hex(0xd0a12b) : lv_color_hex(0x3658cb);
    const lv_color_t fill_end = secondary ? lv_color_hex(0xf4dc86) : lv_color_hex(0x7e9fff);
    lv_obj_set_pos(bar, 0, y);
    lv_obj_set_size(bar, L.card_w - L.card_pad_l - L.card_pad_r, L.bar_h);
    lv_obj_set_style_bg_color(bar, COL_TRACK, 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(bar, 1, 0);
    lv_obj_set_style_border_color(bar, lv_color_hex(0x434955), 0);
    lv_obj_set_style_border_opa(bar, (lv_opa_t)80, 0);
    lv_obj_set_style_radius(bar, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_pad_all(bar, 0, 0);
    lv_obj_set_style_clip_corner(bar, true, 0);
    lv_obj_clear_flag(bar, LV_OBJ_FLAG_SCROLLABLE);

    const int inner_h = L.bar_h > 2 ? L.bar_h - 2 : L.bar_h;
    lv_obj_t* fill = lv_obj_create(bar);
    lv_obj_set_pos(fill, 1, (L.bar_h - inner_h) / 2);
    lv_obj_set_size(fill, 0, inner_h);
    lv_obj_set_style_bg_color(fill, fill_start, 0);
    lv_obj_set_style_bg_opa(fill, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_grad_color(fill, fill_end, 0);
    lv_obj_set_style_bg_grad_dir(fill, LV_GRAD_DIR_HOR, 0);
    lv_obj_set_style_border_width(fill, 0, 0);
    lv_obj_set_style_radius(fill, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_shadow_width(fill, 8, 0);
    lv_obj_set_style_shadow_color(fill, accent, 0);
    lv_obj_set_style_shadow_opa(fill, secondary ? (lv_opa_t)34 : (lv_opa_t)44, 0);
    lv_obj_clear_flag(fill, LV_OBJ_FLAG_SCROLLABLE);
    if (fill_out) *fill_out = fill;
    return bar;
}

static void init_panel_widgets(PanelWidgets* widgets, lv_obj_t* parent, int x, int y, lv_color_t accent) {
    widgets->root = lv_obj_create(parent);
    lv_obj_set_pos(widgets->root, x, y);
    lv_obj_set_size(widgets->root, L.card_w, L.card_h);
    style_card_shell(widgets->root, accent);
    lv_obj_clear_flag(widgets->root, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(widgets->root, LV_OBJ_FLAG_EVENT_BUBBLE);

    widgets->kicker = lv_label_create(widgets->root);
    lv_obj_set_style_text_font(widgets->kicker, L.kicker_font, 0);
    lv_obj_set_style_text_color(widgets->kicker, COL_DIM, 0);
    lv_obj_set_pos(widgets->kicker, 0, L.kicker_y);
    if (!L.show_kicker) lv_obj_add_flag(widgets->kicker, LV_OBJ_FLAG_HIDDEN);

    widgets->pct = lv_label_create(widgets->root);
    lv_obj_set_style_text_font(widgets->pct, L.metric_font, 0);
    lv_obj_set_style_text_color(widgets->pct, COL_TEXT, 0);
    lv_obj_set_pos(widgets->pct, 0, L.pct_y);

    widgets->pill = lv_label_create(widgets->root);
    style_pill(widgets->pill, accent);
    lv_obj_align(widgets->pill, LV_ALIGN_TOP_RIGHT, 0, L.pill_y);

    widgets->bar = make_bar(widgets->root, L.bar_y, accent, &widgets->bar_fill);

    widgets->meta_dot = lv_obj_create(widgets->root);
    lv_obj_set_size(widgets->meta_dot, L.meta_dot, L.meta_dot);
    lv_obj_set_style_bg_color(widgets->meta_dot, accent, 0);
    lv_obj_set_style_bg_opa(widgets->meta_dot, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(widgets->meta_dot, 0, 0);
    lv_obj_set_style_radius(widgets->meta_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_pos(widgets->meta_dot, 0, L.meta_y + 2);

    widgets->meta_left = lv_label_create(widgets->root);
    lv_obj_set_width(widgets->meta_left, L.card_w - L.card_pad_l - L.card_pad_r - L.meta_right_w - L.meta_dot - 12);
    lv_obj_set_style_text_font(widgets->meta_left, L.meta_font, 0);
    lv_obj_set_style_text_color(widgets->meta_left, COL_DIM, 0);
    lv_obj_set_pos(widgets->meta_left, L.meta_dot + 6, L.meta_y);

    widgets->meta_right = lv_label_create(widgets->root);
    lv_obj_set_width(widgets->meta_right, L.meta_right_w);
    lv_obj_set_style_text_font(widgets->meta_right, L.meta_font, 0);
    lv_obj_set_style_text_color(widgets->meta_right, COL_DIM, 0);
    lv_obj_set_style_text_align(widgets->meta_right, LV_TEXT_ALIGN_RIGHT, 0);
    lv_obj_align(widgets->meta_right, LV_ALIGN_TOP_RIGHT, 0, L.meta_y);
}

static void set_usage_panel(PanelWidgets* widgets, const UsagePanelData* panel, bool top) {
    char heading[40];
    char meta_left[40];
    char meta_right[48];
    format_panel_heading(panel, top, heading, sizeof(heading));
    format_panel_meta_left(panel, top, meta_left, sizeof(meta_left));

    if (L.show_kicker) lv_label_set_text(widgets->kicker, heading);

    if (!panel || !panel->valid) {
        lv_label_set_text(widgets->pct, "---%");
        lv_label_set_text(widgets->pill, default_pill_text(top));
        if (widgets->bar_fill) lv_obj_set_width(widgets->bar_fill, 0);
        lv_label_set_text(widgets->meta_left, meta_left);
        lv_label_set_text(widgets->meta_right, "---");
        return;
    }

    const int pct = static_cast<int>(panel->pct + 0.5f);
    lv_label_set_text_fmt(widgets->pct, "%d%%", pct);
    lv_label_set_text(widgets->pill, panel->label[0] ? panel->label : default_pill_text(top));
    if (widgets->bar_fill) {
        const int track_w = L.card_w - L.card_pad_l - L.card_pad_r;
        const int inner_w = track_w > 2 ? track_w - 2 : track_w;
        const int inner_h = L.bar_h > 2 ? L.bar_h - 2 : L.bar_h;
        int fill_w = (inner_w * pct) / 100;
        if (pct > 0 && fill_w < inner_h) fill_w = inner_h;
        if (fill_w > inner_w) fill_w = inner_w;
        lv_obj_set_size(widgets->bar_fill, fill_w, inner_h);
    }
    lv_label_set_text(widgets->meta_left, meta_left);
    format_panel_meta_right(panel, meta_right, sizeof(meta_right));
    lv_label_set_text(widgets->meta_right, meta_right);
}

static void set_idle_label_text(bool with_cursor) {
    lv_label_set_text(idle_label, with_cursor ? "STANDING BY |" : "STANDING BY");
}

static void style_pair_step(lv_obj_t* step, int state) {
    lv_color_t border = state == 1 ? COL_BLUE : (state == 2 ? COL_GREEN : COL_PANEL_EDGE);
    lv_color_t fill = state == 1 ? lv_color_hex(0x1b2640) : COL_PANEL_ALT;
    lv_color_t text = state == 1 ? COL_TEXT : (state == 2 ? COL_TEXT : COL_DIM);
    if (L.mode == LAYOUT_LANDSCAPE_SMALL) {
        border = state == 1 ? COL_BLUE : lv_color_hex(0x3a3c40);
        fill = state == 1 ? lv_color_hex(0x1a2440) : COL_SCREEN;
        text = state == 1 ? COL_TEXT : (state == 2 ? COL_BLUE : COL_DIM);
    }
    lv_obj_set_style_bg_color(step, fill, 0);
    lv_obj_set_style_bg_opa(step, state == 1 ? LV_OPA_COVER : (L.mode == LAYOUT_LANDSCAPE_SMALL ? LV_OPA_TRANSP : LV_OPA_COVER), 0);
    lv_obj_set_style_border_width(step, L.mode == LAYOUT_LANDSCAPE_SMALL ? 0 : 1, 0);
    lv_obj_set_style_border_color(step, border, 0);
    lv_obj_set_style_text_color(step, text, 0);
}

static lv_obj_t* make_pair_step(lv_obj_t* parent, const char* text, int x, int y, int state) {
    lv_obj_t* step = lv_label_create(parent);
    lv_label_set_text(step, text);
    lv_obj_set_pos(step, x, y);
    lv_obj_set_width(step, L.pair_step_w);
    lv_obj_set_style_text_font(step, L.pair_font, 0);
    lv_obj_set_style_radius(step, L.mode == LAYOUT_LANDSCAPE_SMALL ? 6 : 999, 0);
    lv_obj_set_style_pad_left(step, 10, 0);
    lv_obj_set_style_pad_right(step, 10, 0);
    lv_obj_set_style_pad_top(step, L.mode == LAYOUT_LANDSCAPE_SMALL ? 4 : 5, 0);
    lv_obj_set_style_pad_bottom(step, L.mode == LAYOUT_LANDSCAPE_SMALL ? 4 : 5, 0);
    style_pair_step(step, state);
    return step;
}

static void build_pair_group(lv_obj_t* parent) {
    pair_group = make_transparent_box(parent, 0, 0, L.scr_w, L.scr_h);
    lv_obj_add_flag(pair_group, LV_OBJ_FLAG_EVENT_BUBBLE);

    pair_scan_ring = lv_obj_create(pair_group);
    lv_obj_set_pos(pair_scan_ring, L.pair_hero_x, L.pair_hero_y);
    lv_obj_set_size(pair_scan_ring, L.pair_hero_size, L.pair_hero_size);
    lv_obj_set_style_bg_opa(pair_scan_ring, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(pair_scan_ring, 0, 0);
    lv_obj_set_style_pad_all(pair_scan_ring, 0, 0);
    lv_obj_set_style_radius(pair_scan_ring, LV_RADIUS_CIRCLE, 0);
    lv_obj_clear_flag(pair_scan_ring, LV_OBJ_FLAG_SCROLLABLE);

    pair_scan_base = L.pair_hero_size - 12;
    for (int i = 0; i < 3; ++i) {
        pair_scan_rings[i] = lv_obj_create(pair_group);
        lv_obj_set_size(pair_scan_rings[i], pair_scan_base, pair_scan_base);
        lv_obj_set_style_bg_opa(pair_scan_rings[i], LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(pair_scan_rings[i], 2, 0);
        lv_obj_set_style_border_color(pair_scan_rings[i], COL_BLUE, 0);
        lv_obj_set_style_border_opa(pair_scan_rings[i], (lv_opa_t)140, 0);
        lv_obj_set_style_radius(pair_scan_rings[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_pad_all(pair_scan_rings[i], 0, 0);
        lv_obj_clear_flag(pair_scan_rings[i], LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_center(pair_scan_rings[i]);
        lv_obj_align_to(pair_scan_rings[i], pair_scan_ring, LV_ALIGN_CENTER, 0, 0);
    }

    lv_obj_t* bt = lv_canvas_create(pair_scan_ring);
    lv_canvas_set_buffer(bt, pair_ble_canvas_buf, 26, 42, LV_COLOR_FORMAT_RGB565);
    lv_obj_set_style_bg_opa(bt, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(bt, 0, 0);
    lv_obj_center(bt);

    const char* button = "Hold screen for 3s";
    if (L.pair_row) {
        pair_steps[0] = make_pair_step(pair_group, L.mode == LAYOUT_LANDSCAPE_SMALL ? "Board detected" : "Board ready", L.pair_steps_x, L.pair_steps_y, 2);
        pair_steps[1] = make_pair_step(pair_group, L.mode == LAYOUT_LANDSCAPE_SMALL ? "Establishing link..." : button, L.pair_steps_x, L.pair_steps_y + L.pair_step_h + L.pair_step_gap, 1);
        pair_steps[2] = make_pair_step(pair_group, L.mode == LAYOUT_LANDSCAPE_SMALL ? "Agent attached" : "Release to pair", L.pair_steps_x, L.pair_steps_y + 2 * (L.pair_step_h + L.pair_step_gap), 0);
    } else {
        pair_steps[0] = make_pair_step(pair_group, "Board ready", L.pair_steps_x, L.pair_steps_y, 2);
        pair_steps[1] = make_pair_step(pair_group, button, L.pair_steps_x, L.pair_steps_y + L.pair_step_h + L.pair_step_gap, 1);
        pair_steps[2] = make_pair_step(pair_group, "Release to pair", L.pair_steps_x, L.pair_steps_y + 2 * (L.pair_step_h + L.pair_step_gap), 0);
    }
}

static void build_idle_group(lv_obj_t* parent) {
    idle_group = make_transparent_box(parent, 0, 0, L.scr_w, L.scr_h);
    lv_obj_add_flag(idle_group, LV_OBJ_FLAG_EVENT_BUBBLE);

    idle_glow_obj = lv_obj_create(idle_group);
    idle_glow_w = L.idle_creature_size + 20;
    idle_glow_h = L.idle_creature_size + 32;
    lv_obj_set_size(idle_glow_obj, idle_glow_w, idle_glow_h);
    lv_obj_set_style_bg_color(idle_glow_obj, COL_BLUE, 0);
    lv_obj_set_style_bg_opa(idle_glow_obj, (lv_opa_t)10, 0);
    lv_obj_set_style_border_width(idle_glow_obj, 1, 0);
    lv_obj_set_style_border_color(idle_glow_obj, COL_BLUE, 0);
    lv_obj_set_style_border_opa(idle_glow_obj, (lv_opa_t)15, 0);
    lv_obj_set_style_shadow_width(idle_glow_obj, 18, 0);
    lv_obj_set_style_shadow_color(idle_glow_obj, COL_BLUE, 0);
    lv_obj_set_style_shadow_opa(idle_glow_obj, (lv_opa_t)10, 0);
    lv_obj_set_style_radius(idle_glow_obj, 20, 0);
    lv_obj_clear_flag(idle_glow_obj, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_align(idle_glow_obj, LV_ALIGN_CENTER, 0, L.idle_creature_dy);
    idle_canvas = lv_canvas_create(idle_group);
    lv_canvas_set_buffer(idle_canvas, idle_canvas_buf, 20, 20, LV_COLOR_FORMAT_RGB565A8);
    idle_base_scale = (uint32_t)((L.idle_creature_size * 256) / 20);
    lv_image_set_scale(idle_canvas, idle_base_scale);
    lv_image_set_antialias(idle_canvas, false);
    lv_obj_align(idle_canvas, LV_ALIGN_CENTER, 0, L.idle_creature_dy);

    idle_label = lv_label_create(idle_group);
    lv_obj_set_style_text_font(idle_label, L.idle_font, 0);
    lv_obj_set_style_text_color(idle_label, COL_DIM, 0);
    lv_obj_align(idle_label, LV_ALIGN_BOTTOM_MID, 0, L.idle_label_y);
    set_idle_label_text(true);

    for (int i = 0; i < 4; ++i) {
        idle_z_labels[i] = lv_label_create(idle_group);
        lv_label_set_text(idle_z_labels[i], "Z");
        lv_obj_set_style_text_font(idle_z_labels[i], &font_ui_bold_12, 0);
        lv_obj_set_style_text_color(idle_z_labels[i], COL_BLUE, 0);
        lv_obj_set_style_opa(idle_z_labels[i], LV_OPA_50, 0);
        lv_obj_align(idle_z_labels[i], LV_ALIGN_CENTER, -54 + i * 18, -70);
    }
}

static void update_brand_chip(void) {
    const char* provider = provider_text(current_usage.provider);
    char glyph[2] = {'H', '\0'};
    if (data_received && provider[0] && provider[0] != 'N') glyph[0] = provider[0];
    lv_label_set_text(brand_chip_label, glyph);
}

static void update_header_provider(void) {
    lv_label_set_text(lbl_provider, data_received ? provider_text(current_usage.provider) : "Not found");
    update_brand_chip();
}

static void update_header_connection_state(void) {
    const bool connected = s_ble_connected;
    lv_obj_set_style_border_color(brand_chip, COL_BLUE, 0);
    lv_obj_set_style_text_color(brand_chip_label, connected ? COL_TEXT : COL_DIM, 0);
    lv_obj_set_style_opa(lbl_ble, connected ? (lv_opa_t)179 : LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(agent_badge, connected ? COL_GREEN : COL_ORANGE, 0);
    lv_obj_set_style_bg_opa(agent_badge, connected ? (lv_opa_t)34 : (lv_opa_t)40, 0);
    lv_obj_set_style_border_color(agent_badge, connected ? COL_GREEN : COL_ORANGE, 0);
    lv_obj_set_style_border_opa(agent_badge, connected ? (lv_opa_t)74 : (lv_opa_t)84, 0);
    render_agent_badge_icon(connected);
    if (flow_dot) {
        lv_obj_set_style_bg_color(flow_dot, COL_BLUE, 0);
        lv_obj_set_style_shadow_width(flow_dot, 4, 0);
        lv_obj_set_style_shadow_color(flow_dot, COL_BLUE, 0);
        lv_obj_set_style_shadow_opa(flow_dot, (lv_opa_t)38, 0);
    }
}

static void update_header_title_for_view(int view) {
    if (!lbl_title) return;
    if (view == 0) {
        lv_label_set_text(lbl_title, "Pairing");
    } else if (view == 1) {
        lv_label_set_text(lbl_title, "Standing by");
    } else {
        lv_label_set_text(lbl_title, "Usage");
    }
}

static void apply_battery_visibility(void) {
    if (!battery_img) return;
    if (!board_caps().has_battery || current_screen != SCREEN_USAGE || view_state == 1) {
        lv_obj_add_flag(battery_img, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(battery_img, LV_OBJ_FLAG_HIDDEN);
    }
}

static void apply_view_state(int view) {
    view_state = view;
    update_header_title_for_view(view);
    if (view == 2) {
        lv_obj_clear_flag(usage_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(pair_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(idle_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(header_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(flow_track, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(flow_canvas, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(flow_dot, LV_OBJ_FLAG_HIDDEN);
    } else if (view == 1) {
        lv_obj_add_flag(usage_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(pair_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(idle_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(header_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(flow_track, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(flow_canvas, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(flow_dot, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(usage_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(pair_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(idle_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(header_group, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(flow_track, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(flow_canvas, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(flow_dot, LV_OBJ_FLAG_HIDDEN);
    }

    apply_battery_visibility();
    update_header_connection_state();
}

static void update_view_state(void) {
    if (current_screen != SCREEN_USAGE) return;
    const uint32_t now = lv_tick_get();
    int next = 0;
    if (!s_ble_connected) {
        next = 0;  // Pair
    } else if (data_received && (now - last_data_ms) < DATA_FRESH_MS) {
        next = 2;  // Usage — data is fresh
    } else {
        next = 1;  // Idle — data stale or never received
    }

    if (!s_ble_connected) {
        forced_view_override = -1;
    } else if (forced_view_override >= 0) {
        next = forced_view_override;
    }

    if (next == view_state) return;
    apply_view_state(next);
}

static void global_click_cb(lv_event_t* e) {
    (void)e;
    if (current_screen == SCREEN_USAGE) {
        ui_show_screen(SCREEN_SPLASH);
    }
}

static void init_usage_screen(lv_obj_t* scr) {
    usage_container = lv_obj_create(scr);
    lv_obj_set_size(usage_container, L.scr_w, L.scr_h);
    lv_obj_set_pos(usage_container, 0, 0);
    lv_obj_set_style_bg_color(usage_container, L.mode == LAYOUT_LANDSCAPE_SMALL ? lv_color_hex(0x0d1016) : COL_SCREEN, 0);
    lv_obj_set_style_bg_opa(usage_container, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_grad_color(usage_container, COL_SCREEN, 0);
    lv_obj_set_style_bg_grad_dir(usage_container, LV_GRAD_DIR_VER, 0);
    lv_obj_set_style_border_width(usage_container, 0, 0);
    lv_obj_set_style_pad_all(usage_container, 0, 0);
    lv_obj_clear_flag(usage_container, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(usage_container, global_click_cb, LV_EVENT_CLICKED, nullptr);

    usage_bg_glow = lv_obj_create(usage_container);
    lv_obj_set_size(usage_bg_glow, L.scr_w - 38, 92);
    lv_obj_align(usage_bg_glow, LV_ALIGN_TOP_MID, 0, -28);
    lv_obj_set_style_bg_color(usage_bg_glow, COL_BLUE, 0);
    lv_obj_set_style_bg_opa(usage_bg_glow, (lv_opa_t)11, 0);
    lv_obj_set_style_border_width(usage_bg_glow, 0, 0);
    lv_obj_set_style_radius(usage_bg_glow, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_shadow_width(usage_bg_glow, 44, 0);
    lv_obj_set_style_shadow_color(usage_bg_glow, COL_BLUE, 0);
    lv_obj_set_style_shadow_opa(usage_bg_glow, (lv_opa_t)12, 0);
    lv_obj_clear_flag(usage_bg_glow, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_move_background(usage_bg_glow);

    build_screen_grid(usage_container);

    header_group = make_transparent_box(usage_container, 0, 0, L.scr_w, L.header_h + L.pad_t);

    brand_chip = lv_obj_create(header_group);
    lv_obj_set_pos(brand_chip, L.chip_x, L.chip_y);
    lv_obj_set_size(brand_chip, L.chip_w, L.chip_h);
    lv_obj_set_style_bg_color(brand_chip, COL_PANEL_ALT, 0);
    lv_obj_set_style_bg_opa(brand_chip, L.mode == LAYOUT_LANDSCAPE_SMALL ? LV_OPA_TRANSP : LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(brand_chip, L.mode == LAYOUT_LANDSCAPE_SMALL ? 0 : 1, 0);
    lv_obj_set_style_border_color(brand_chip, COL_BLUE, 0);
    lv_obj_set_style_radius(brand_chip, L.chip_radius, 0);
    lv_obj_set_style_pad_all(brand_chip, 0, 0);
    lv_obj_clear_flag(brand_chip, LV_OBJ_FLAG_SCROLLABLE);

    brand_canvas = lv_canvas_create(brand_chip);
    lv_canvas_set_buffer(brand_canvas, brand_canvas_buf, 54, 54, LV_COLOR_FORMAT_RGB565);
    lv_obj_center(brand_canvas);

    brand_chip_label = lv_label_create(brand_chip);
    lv_label_set_text(brand_chip_label, "H");
    lv_obj_set_style_text_font(brand_chip_label, L.chip_font, 0);
    lv_obj_set_style_text_color(brand_chip_label, COL_TEXT, 0);
    lv_obj_center(brand_chip_label);
    lv_obj_add_flag(brand_chip_label, LV_OBJ_FLAG_HIDDEN);

    lbl_title = lv_label_create(header_group);
    lv_label_set_text(lbl_title, "Usage");
    lv_obj_set_width(lbl_title, L.title_w);
    lv_obj_set_style_text_font(lbl_title, L.title_font, 0);
    lv_obj_set_style_text_color(lbl_title, lv_color_hex(0xf7f3ea), 0);
    lv_obj_set_pos(lbl_title, L.title_x, L.title_y);

    lbl_provider = lv_label_create(header_group);
    lv_label_set_text(lbl_provider, "Not found");
    lv_obj_set_style_text_font(lbl_provider, L.provider_font, 0);
    lv_obj_set_style_text_color(lbl_provider, lv_color_hex(0xcfc8b8), 0);
    lv_obj_set_style_bg_color(lbl_provider, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_bg_opa(lbl_provider, L.mode == LAYOUT_LANDSCAPE_SMALL ? (lv_opa_t)10 : LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(lbl_provider, 1, 0);
    lv_obj_set_style_border_color(lbl_provider, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_border_opa(lbl_provider, L.mode == LAYOUT_LANDSCAPE_SMALL ? (lv_opa_t)26 : LV_OPA_COVER, 0);
    lv_obj_set_style_radius(lbl_provider, 3, 0);
    lv_obj_set_style_pad_left(lbl_provider, L.mode == LAYOUT_LANDSCAPE_SMALL ? 4 : 1, 0);
    lv_obj_set_style_pad_right(lbl_provider, L.mode == LAYOUT_LANDSCAPE_SMALL ? 4 : 5, 0);
    lv_obj_set_style_pad_top(lbl_provider, 1, 0);
    lv_obj_set_style_pad_bottom(lbl_provider, 1, 0);
    lv_obj_set_pos(lbl_provider, L.title_x, L.provider_y);

    lbl_ble = lv_canvas_create(header_group);
    lv_canvas_set_buffer(lbl_ble, ble_canvas_buf, 14, 16, LV_COLOR_FORMAT_RGB565);
    lv_obj_set_style_bg_opa(lbl_ble, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(lbl_ble, 0, 0);
    lv_obj_set_pos(lbl_ble, L.bt_x, L.bt_y);

    agent_badge = lv_obj_create(header_group);
    lv_obj_set_pos(agent_badge, L.agent_x, L.agent_y);
    lv_obj_set_size(agent_badge, L.agent_size, L.agent_size);
    lv_obj_set_style_bg_color(agent_badge, COL_GREEN, 0);
    lv_obj_set_style_bg_opa(agent_badge, (lv_opa_t)34, 0);
    lv_obj_set_style_border_width(agent_badge, 1, 0);
    lv_obj_set_style_border_color(agent_badge, COL_GREEN, 0);
    lv_obj_set_style_border_opa(agent_badge, (lv_opa_t)74, 0);
    lv_obj_set_style_radius(agent_badge, 7, 0);
    lv_obj_set_style_shadow_width(agent_badge, 0, 0);
    lv_obj_clear_flag(agent_badge, LV_OBJ_FLAG_SCROLLABLE);

    agent_canvas = lv_canvas_create(agent_badge);
    lv_canvas_set_buffer(agent_canvas, agent_canvas_buf, L.agent_size, L.agent_size, LV_COLOR_FORMAT_RGB565);
    lv_obj_set_style_bg_opa(agent_canvas, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(agent_canvas, 0, 0);
    lv_obj_center(agent_canvas);
    render_agent_badge_icon(true);

    if (board_caps().has_battery) {
        battery_img = lv_image_create(header_group);
        lv_image_set_src(battery_img, &battery_dscs[3]);
        lv_obj_set_size(battery_img, 28, 28);
        lv_obj_set_pos(battery_img, L.battery_x, L.battery_y);
    }

    flow_track = lv_obj_create(usage_container);
    lv_obj_set_pos(flow_track, L.flow_x, L.flow_y);
    lv_obj_set_size(flow_track, L.flow_w, L.flow_h);
    lv_obj_set_style_bg_color(flow_track, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_bg_opa(flow_track, (lv_opa_t)8, 0);
    lv_obj_set_style_border_width(flow_track, 1, 0);
    lv_obj_set_style_border_color(flow_track, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_border_opa(flow_track, (lv_opa_t)12, 0);
    lv_obj_set_style_radius(flow_track, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_pad_all(flow_track, 0, 0);
    lv_obj_clear_flag(flow_track, LV_OBJ_FLAG_SCROLLABLE);

    flow_canvas = lv_canvas_create(flow_track);
    lv_canvas_set_buffer(flow_canvas, flow_canvas_buf, L.flow_w, L.flow_h, LV_COLOR_FORMAT_RGB565);
    lv_obj_set_style_bg_opa(flow_canvas, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(flow_canvas, 0, 0);
    lv_obj_set_pos(flow_canvas, 0, 0);
    render_flow_line(20);

    flow_dot = lv_obj_create(usage_container);
    lv_obj_set_size(flow_dot, L.flow_dot, L.flow_dot);
    lv_obj_set_style_bg_color(flow_dot, COL_BLUE, 0);
    lv_obj_set_style_bg_opa(flow_dot, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(flow_dot, 0, 0);
    lv_obj_set_style_radius(flow_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_pos(flow_dot, L.flow_x + L.flow_w, L.flow_y - 1);
    lv_obj_clear_flag(flow_dot, LV_OBJ_FLAG_SCROLLABLE);

    usage_group = make_transparent_box(usage_container, 0, 0, L.scr_w, L.scr_h);
    init_panel_widgets(&panel_top, usage_group, L.card_x, L.card1_y, COL_BLUE);
    init_panel_widgets(&panel_bottom, usage_group, L.card2_x, L.card2_y, COL_YELLOW);
    set_usage_panel(&panel_top, nullptr, true);
    set_usage_panel(&panel_bottom, nullptr, false);

    build_pair_group(usage_container);
    build_idle_group(usage_container);
    update_header_provider();
    update_view_state();
}

void ui_init(void) {
    const BoardCaps caps = board_caps();
    compute_layout(caps);
    init_battery_icons();
    render_hermes_header_icon(0, 0);
    render_hermes_idle_icon(0);
    render_ble_icon();
    render_pair_ble_icon();

    lv_obj_t* scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, COL_BG, 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);

    init_usage_screen(scr);
    splash_init(scr);
    splash_hide();
    ui_show_screen(SCREEN_USAGE);
}

void ui_update(const UsageData* data) {
    if (!data) return;
    current_usage = *data;
    data_received = data->valid;
    if (data->valid) last_data_ms = lv_tick_get();

    update_header_provider();
    set_usage_panel(&panel_top, &data->top, true);
    set_usage_panel(&panel_bottom, &data->bottom, false);
    update_view_state();
}

void ui_tick_anim(void) {
    if (current_screen != SCREEN_USAGE) return;
    update_view_state();

    const uint32_t now = lv_tick_get();
    if ((view_state == 2 || view_state == 0) && now - flow_anim_ms >= 35) {
        flow_anim_ms = now;
        flow_anim_phase = (uint8_t)((flow_anim_phase + 1) % 48);
        const int tri = flow_anim_phase <= 24 ? flow_anim_phase : 48 - flow_anim_phase;
        render_flow_line(flow_anim_phase);
        if (flow_dot) {
            lv_obj_set_pos(flow_dot, L.flow_x + L.flow_w, L.flow_y - 1);
            lv_obj_set_style_opa(flow_dot, (lv_opa_t)(92 + (163 * tri) / 24), 0);
        }
    }

    if ((view_state == 2 || view_state == 0) && now - header_anim_ms >= (view_state == 2 ? 130 : 500)) {
        header_anim_ms = now;
        header_anim_phase = (uint8_t)(header_anim_phase + 1);
        render_hermes_header_icon(view_state, header_anim_phase);
    }

    if (view_state == 2 && now - card_glow_ms >= 90) {
        card_glow_ms = now;
        card_glow_phase = (uint8_t)((card_glow_phase + 1) % 48);
        const uint32_t s_top = SINE_48[card_glow_phase];
        const uint32_t s_bottom = SINE_48[(card_glow_phase + 12) % 48];
        if (panel_top.root) {
            lv_obj_set_style_shadow_opa(panel_top.root, (lv_opa_t)(18 + (24 * s_top) / 255), 0);
            lv_obj_set_style_border_opa(panel_top.root, (lv_opa_t)(24 + (24 * s_top) / 255), 0);
        }
        if (panel_bottom.root) {
            lv_obj_set_style_shadow_opa(panel_bottom.root, (lv_opa_t)(14 + (18 * s_bottom) / 255), 0);
            lv_obj_set_style_border_opa(panel_bottom.root, (lv_opa_t)(20 + (18 * s_bottom) / 255), 0);
        }
    }

    if (view_state == 1) {
        if (now - idle_anim_ms >= 80) {
            idle_anim_ms = now;
            idle_anim_phase = (uint8_t)((idle_anim_phase + 1) % 48);
            render_hermes_idle_icon(idle_anim_phase);

            // Hero breathe: animate scale and translateY (7s cycle, 48-step sine)
            if (now - idle_breathe_ms >= 146) {
                idle_breathe_ms = now;
                idle_breathe_phase = (uint8_t)((idle_breathe_phase + 1) % 48);
                const uint32_t s = SINE_48[idle_breathe_phase];  // 0–255
                // scale: base + 0..+2.5% (0–25/1000)
                uint32_t breathe_scale = idle_base_scale +
                    (uint32_t)((uint64_t)idle_base_scale * 25u * s / 255u / 1000u);
                lv_image_set_scale(idle_canvas, breathe_scale);
                // translateY: 0..-3 px (move up when s > 128)
                int16_t breathe_y = -(int16_t)((int32_t)s * 3 / 255);
                lv_obj_set_style_translate_y(idle_canvas, breathe_y, 0);
            }

            for (int i = 0; i < 4; ++i) {
                if (!idle_z_labels[i]) continue;
                const int ph = (idle_anim_phase + i * 12) % 48;
                const int y = -58 - ph;
                lv_opa_t opa = LV_OPA_70;
                if (ph < 8) opa = (lv_opa_t)(40 + ph * 18);
                else if (ph > 34) opa = (lv_opa_t)(200 - (ph - 34) * 12);
                lv_obj_set_style_opa(idle_z_labels[i], opa, 0);
                lv_obj_align(idle_z_labels[i], LV_ALIGN_CENTER, -54 + i * 18, y);
            }
        }

        // Glow pulse (~25s cycle: 48 × 522ms = 25.056s)
        if (now - idle_glow_ms >= 522) {
            idle_glow_ms = now;
            idle_glow_phase = (uint8_t)((idle_glow_phase + 1) % 48);
            const uint32_t gf = SINE_48[idle_glow_phase];
            if (idle_glow_obj) {
                const int16_t w = idle_glow_w + (int16_t)((idle_glow_w * 4 / 100) * gf / 255u);
                const int16_t h = idle_glow_h + (int16_t)((idle_glow_h * 4 / 100) * gf / 255u);
                lv_obj_set_size(idle_glow_obj, w, h);
                lv_obj_align(idle_glow_obj, LV_ALIGN_CENTER, 0, L.idle_creature_dy);
                lv_obj_set_style_bg_opa(idle_glow_obj, (lv_opa_t)(10 + (15 * gf) / 255u), 0);
                lv_obj_set_style_border_opa(idle_glow_obj, (lv_opa_t)(8 + (7 * gf) / 255u), 0);
                lv_obj_set_style_shadow_opa(idle_glow_obj, (lv_opa_t)(8 + (12 * gf) / 255u), 0);
            }
        }

        if (now - idle_cursor_ms >= 600) {
            idle_cursor_ms = now;
            idle_cursor_on = !idle_cursor_on;
            set_idle_label_text(idle_cursor_on);
        }
    }

    if (view_state == 0 && pair_scan_ring) {
        if (now - pair_scan_ms >= 33) {
            pair_scan_ms = now;
            pair_scan_phase = (pair_scan_phase + 1) % 75;
            static const int offsets[3] = {0, 24, 48};
            for (int i = 0; i < 3; ++i) {
                lv_obj_t* ring = pair_scan_rings[i];
                if (!ring) continue;
                const int local = (pair_scan_phase + offsets[i]) % 75;
                const uint32_t p = (uint32_t)local * 255u / 74u;
                const uint32_t ease = 255u - ((255u - p) * (255u - p) / 255u);  // ease-out
                const int16_t size = (int16_t)(pair_scan_base * (35u + (135u * ease) / 255u) / 100u);
                const lv_opa_t opa = (lv_opa_t)(180u - (180u * ease) / 255u);
                const uint8_t bw = (uint8_t)(2u + (ease < 96u ? 1u : 0u));
                lv_obj_set_size(ring, size, size);
                lv_obj_align_to(ring, pair_scan_ring, LV_ALIGN_CENTER, 0, 0);
                lv_obj_set_style_border_width(ring, bw, 0);
                lv_obj_set_style_border_opa(ring, opa, 0);
            }
        }
    }
}

void ui_show_screen(screen_t screen) {
    current_screen = screen;
    s_last_screen_change = lv_tick_get();
    if (screen == SCREEN_SPLASH) {
        forced_view_override = -1;
        if (!splash_get_root()) {
            current_screen = SCREEN_USAGE;
            splash_hide();
            if (usage_container) lv_obj_clear_flag(usage_container, LV_OBJ_FLAG_HIDDEN);
            update_view_state();
            return;
        }
        if (usage_container) lv_obj_add_flag(usage_container, LV_OBJ_FLAG_HIDDEN);
        splash_show();
        return;
    }

    splash_hide();
    if (usage_container) lv_obj_clear_flag(usage_container, LV_OBJ_FLAG_HIDDEN);
    update_view_state();
}

void ui_toggle_splash(void) {
    if (current_screen == SCREEN_SPLASH) ui_show_screen(SCREEN_USAGE);
    else ui_show_screen(SCREEN_SPLASH);
}

screen_t ui_get_current_screen(void) {
    return current_screen;
}

int ui_get_view_state(void) {
    return view_state;
}

uint32_t ui_get_last_screen_change_time(void) {
    return s_last_screen_change;
}
void ui_force_view(int view) {
    if (view < 0 || view > 2) return;
    if (current_screen != SCREEN_USAGE) return;
    forced_view_override = view;
    apply_view_state(view);
}

bool ui_is_ble_connected(void) {
    return s_ble_connected;
}


void ui_update_ble_status(ble_state_t state, const char* name, const char* mac) {
    (void)name;
    (void)mac;
    s_ble_connected = (state == BLE_STATE_CONNECTED);
    if (!s_ble_connected) forced_view_override = -1;
    update_view_state();
}

void ui_update_battery(int percent, bool charging) {
    if (!battery_img) return;

    int idx = 0;
    if (charging) idx = 4;
    else if (percent < 20) idx = 1;
    else if (percent < 50) idx = 2;
    else idx = 3;

    lv_image_set_src(battery_img, &battery_dscs[idx]);
    apply_battery_visibility();
}
