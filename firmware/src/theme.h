#pragma once
#include <lvgl.h>

// Hermes-inspired design tokens used by the small-screen 2432S028 UI refresh.
// Keep the aliases below so older shared code keeps compiling while the newer
// screens can opt into the richer palette directly.
#define THEME_BG         lv_color_hex(0x08090c)
#define THEME_PANEL      lv_color_hex(0x262a33)
#define THEME_PANEL_ALT  lv_color_hex(0x1c2028)
#define THEME_PANEL_EDGE lv_color_hex(0x5c6678)
#define THEME_TEXT       lv_color_hex(0xf5f1e8)
#define THEME_DIM        lv_color_hex(0xc4bfb0)
#define THEME_BLUE       lv_color_hex(0x5a7aff)
#define THEME_YELLOW     lv_color_hex(0xffd53d)
#define THEME_GREEN      lv_color_hex(0x34b55a)
#define THEME_ORANGE     lv_color_hex(0xffaa77)
#define THEME_TRACK      lv_color_hex(0x383d46)

#define THEME_ACCENT THEME_BLUE
#define THEME_AMBER  THEME_YELLOW
#define THEME_RED    THEME_ORANGE
#define THEME_BAR_BG THEME_TRACK
