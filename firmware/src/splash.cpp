#include "splash.h"
#include "pet_buffer.h"
#include "splash_animations.h"
#include "theme.h"
#include "usage_rate.h"
#include "hal/board_caps.h"
#include <Arduino.h>
#include <string.h>
#include <esp_heap_caps.h>

// 20×20 grid. CELL sized so the canvas fits the smaller display dimension —
// the canvas is square and centered, so on portrait or letterboxed panels
// it leaves vertical margin rather than cropping.
#define GRID         20
static int  cell      = 24;        // recomputed in splash_init()
static int  canvas_w  = GRID * 24;
static int  canvas_h  = GRID * 24;

// Background fallback when palette is missing
#define COL_EMPTY    0x0000  // true black (matches THEME_BG)

static lv_obj_t *splash_container = NULL;
static lv_obj_t *canvas = NULL;
static uint16_t *canvas_buf = NULL;        // square RGB565 canvas, PSRAM when available

static uint16_t cur_anim = 0;
static uint32_t frame_started_ms = 0;
static uint32_t last_pick_ms = 0;
static bool active = false;
static uint8_t splash_phase = 0;
static bool canvas_buffer_lent = false;

// Splash pet frame state (reset when pet changes)
static uint32_t s_splash_pet_timer = 0;
static int      s_splash_pet_frame = 0;

// Prepaid balance override (-1 = use rate-based picking)
static int g_prepaid_balance = -1;

// While splash is showing, auto-cycle to the next animation in the current
// rate-driven group every this many ms.
#define SPLASH_ROTATE_INTERVAL_MS 20000

static const char HERMES_SPLASH_FRAME[] =
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

static uint16_t rgb565(uint32_t hex) {
    uint8_t r = (uint8_t)((hex >> 16) & 0xff);
    uint8_t g = (uint8_t)((hex >> 8) & 0xff);
    uint8_t b = (uint8_t)(hex & 0xff);
    return (uint16_t)(((r & 0xf8) << 8) | ((g & 0xfc) << 3) | (b >> 3));
}

static void put_square(int x, int y, int size, uint16_t color) {
    if (!canvas_buf) return;
    for (int yy = 0; yy < size; ++yy) {
        int py = y + yy;
        if (py < 0 || py >= canvas_h) continue;
        for (int xx = 0; xx < size; ++xx) {
            int px = x + xx;
            if (px < 0 || px >= canvas_w) continue;
            canvas_buf[py * canvas_w + px] = color;
        }
    }
}

static void render_hermes_splash(void) {
    if (!canvas_buf) return;
    const uint16_t bg = rgb565(0x000000);
    const uint16_t body = rgb565(0xece6db);
    const uint16_t shade = rgb565(0xdedad0);
    const uint16_t blue = rgb565(0x5a7aff);
    const uint16_t yellow = rgb565(0xffd53d);

    for (int i = 0; i < canvas_w * canvas_h; ++i) canvas_buf[i] = bg;

    const int px = (canvas_w >= 180) ? 7 : 6;
    const int art_w = 20 * px;
    const int ox = (canvas_w - art_w) / 2;
    // A visible but gentle 4 px breathing/bob cycle. The old 1 px two-state
    // shift was effectively invisible on the CYD and looked like a frozen UI.
    static const int8_t BOB_24[24] = {
         0,  0, -1, -1, -2, -3, -3, -4, -4, -3, -3, -2,
        -1,  0,  0,  1,  1,  2,  2,  1,  1,  0,  0,  0,
    };
    const int oy = (canvas_h - art_w) / 2 + BOB_24[splash_phase % 24];

    if (pet_buffer_ready()) {
        // ══ Animated Petdex pet ══
        const uint8_t* frame = pet_buffer_frame(s_splash_pet_frame);
        if (frame) {
            for (int y = 0; y < 20; ++y) {
                for (int x = 0; x < 20; ++x) {
                    uint8_t idx = frame[y * 20 + x];
                    // All indices are opaque
                    put_square(ox + x * px, oy + y * px, px,
                        pet_buffer_palette()[idx]);
                }
            }
        }
    } else {
        // ══ Fallback: Hermes face (existing code) ══
        for (int y = 0; y < 20; ++y) {
            for (int x = 0; x < 20; ++x) {
                char code = HERMES_SPLASH_FRAME[y * 20 + x];
                if (code == '0') continue;
                put_square(ox + x * px, oy + y * px, px,
                    code == '2' ? shade : body);
            }
        }
    }

    // ── Particles (unchanged) ──
    if ((cur_anim & 1) == 0) {
        const int t = splash_phase % 48;
        for (int i = 0; i < 4; ++i) {
            const int ph = (t + i * 12) % 48;
            put_square(ox + art_w - 12 + i * 5, oy + 12 + ph / 2, ph < 28 ? 3 : 2, yellow);
        }
    } else {
        const int orbit[8][2] = {{70, 6}, {110, 20}, {134, 68}, {112, 118}, {68, 134}, {24, 112}, {8, 68}, {24, 22}};
        const int a = (splash_phase / 6) % 8;
        const int b = (a + 4) % 8;
        put_square((canvas_w - 140) / 2 + orbit[a][0], (canvas_h - 140) / 2 + orbit[a][1], 5, blue);
        put_square((canvas_w - 140) / 2 + orbit[b][0], (canvas_h - 140) / 2 + orbit[b][1], 3, blue);
    }

    if (canvas) lv_obj_invalidate(canvas);
}

// ---- Mini creature: a small animated creature for embedding in other screens
//      (e.g. the idle "sleeping" indicator). Self-contained — its own canvas and
//      buffer, independent of the full-screen splash above. ----
static lv_obj_t  *mini_canvas = NULL;
static uint16_t  *mini_buf = NULL;
static int        mini_cell = 0;
static int        mini_w = 0;
static const splash_anim_def_t *mini_anim = NULL;
static uint16_t   mini_frame = 0;
static uint32_t   mini_started = 0;

static void mini_render(void) {
    if (!mini_buf || !mini_anim) return;
    const uint8_t *cells = mini_anim->frames[mini_frame];
    const uint16_t *pal = mini_anim->palette;
    for (int gy = 0; gy < GRID; gy++) {
        for (int gx = 0; gx < GRID; gx++) {
            uint8_t code = cells[gy * GRID + gx];
            uint16_t color = (pal && code < SPLASH_PALETTE_SIZE) ? pal[code] : COL_EMPTY;
            for (int dy = 0; dy < mini_cell; dy++) {
                uint16_t *dst = &mini_buf[(gy * mini_cell + dy) * mini_w + gx * mini_cell];
                for (int dx = 0; dx < mini_cell; dx++) dst[dx] = color;
            }
        }
    }
    if (mini_canvas) lv_obj_invalidate(mini_canvas);
}

lv_obj_t* splash_mini_create(lv_obj_t *parent, const char *anim_name, int px) {
    mini_anim = NULL;
    for (int i = 0; i < SPLASH_ANIM_COUNT; i++) {
        if (strcmp(splash_anims[i].name, anim_name) == 0) { mini_anim = &splash_anims[i]; break; }
    }
    if (!mini_anim) return NULL;
    mini_cell = px / GRID;
    if (mini_cell < 1) mini_cell = 1;
    mini_w = GRID * mini_cell;
#ifdef BOARD_HAS_PSRAM
    const uint32_t caps = MALLOC_CAP_SPIRAM;
#else
    const uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
#endif
    mini_buf = (uint16_t*)heap_caps_malloc(mini_w * mini_w * 2, caps);
    if (!mini_buf) return NULL;
    mini_canvas = lv_canvas_create(parent);
    lv_canvas_set_buffer(mini_canvas, mini_buf, mini_w, mini_w, LV_COLOR_FORMAT_RGB565);
    mini_frame = 0;
    mini_started = millis();
    mini_render();
    return mini_canvas;
}

void splash_mini_tick(void) {
    if (!mini_buf || !mini_anim || mini_anim->frame_count == 0) return;
    if (millis() - mini_started < mini_anim->holds[mini_frame]) return;
    mini_started = millis();
    mini_frame = (mini_frame + 1) % mini_anim->frame_count;
    mini_render();
}

void splash_init(lv_obj_t *parent) {
    const BoardCaps& c = board_caps();
    int min_dim = (c.width < c.height) ? c.width : c.height;
    cell     = min_dim / GRID;       // fits within the smaller display dimension
    if (cell < 4) cell = 4;
    if (c.width > c.height && c.height <= 260) cell = 7;

#ifdef BOARD_HAS_PSRAM
    const uint32_t canvas_caps = MALLOC_CAP_SPIRAM;
#else
    // Without PSRAM the full 480×480 RGB565 canvas (460 KB) won't fit. Cap
    // the canvas so the buffer stays under ~80 KB, leaving the rest of
    // internal SRAM free for LVGL, NimBLE, and the audio/PMU stacks. The
    // canvas is centered, so the cost is extra black border around the
    // pixel art — not cropping.
    const uint32_t canvas_caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    const int MAX_CELL_NO_PSRAM = 10;  // 10*20=200; 200*200*2=78 KB
    if (cell > MAX_CELL_NO_PSRAM) cell = MAX_CELL_NO_PSRAM;
#endif

    canvas_w = GRID * cell;
    canvas_h = GRID * cell;

    canvas_buf = (uint16_t*)heap_caps_malloc(canvas_w * canvas_h * 2, canvas_caps);
    if (!canvas_buf) {
        Serial.println("splash: failed to alloc canvas buffer");
        return;
    }

    splash_container = lv_obj_create(parent);
    lv_obj_set_size(splash_container, c.width, c.height);
    lv_obj_set_pos(splash_container, 0, 0);
    lv_obj_set_style_bg_color(splash_container, THEME_BG, 0);
    lv_obj_set_style_bg_opa(splash_container, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(splash_container, 0, 0);
    lv_obj_set_style_pad_all(splash_container, 0, 0);
    lv_obj_clear_flag(splash_container, LV_OBJ_FLAG_SCROLLABLE);

    canvas = lv_canvas_create(splash_container);
    lv_canvas_set_buffer(canvas, canvas_buf, canvas_w, canvas_h, LV_COLOR_FORMAT_RGB565);
    lv_obj_align(canvas, LV_ALIGN_CENTER, 0, 0);

    render_hermes_splash();
    frame_started_ms = millis();

    lv_obj_add_flag(splash_container, LV_OBJ_FLAG_HIDDEN);
}

void splash_tick(void) {
    if (!active) return;

    const uint32_t now = millis();

    if (pet_buffer_ready()) {
        uint16_t frame_count = pet_buffer_frame_count();
        if (frame_count < 1) frame_count = 1;
        uint32_t hold_ms = pet_buffer_hold_ms();
        // Protect the render loop from malformed or extreme host timing.
        if (hold_ms < 50) hold_ms = 50;
        if (hold_ms > 2000) hold_ms = 2000;
        if (s_splash_pet_frame >= frame_count) s_splash_pet_frame = 0;

        bool redraw = false;
        if (now - s_splash_pet_timer >= hold_ms) {
            s_splash_pet_timer = now;
            s_splash_pet_frame = (s_splash_pet_frame + 1) % frame_count;
            redraw = true;
        }
        // Keep the subtle background particles moving independently.
        if (now - frame_started_ms >= 130) {
            frame_started_ms = now;
            splash_phase++;
            redraw = true;
        }
        if (redraw) render_hermes_splash();
        return;
    }

    // Auto-rotate to the next animation in the current group.
    // Skip if a user-selected pet is loaded (petdex override).
    if (now - last_pick_ms >= SPLASH_ROTATE_INTERVAL_MS) {
        splash_pick_for_current_rate();
    }

    if (now - frame_started_ms >= 130) {
        frame_started_ms = now;
        splash_phase++;
        render_hermes_splash();
    }
}

bool splash_release_buffer_for_network(void) {
#ifdef BOARD_HAS_PSRAM
    return false;
#else
    if (!canvas || !canvas_buf || canvas_buffer_lent) return false;
    lv_obj_add_flag(canvas, LV_OBJ_FLAG_HIDDEN);
    heap_caps_free(canvas_buf);
    canvas_buf = NULL;
    canvas_buffer_lent = true;
    return true;
#endif
}

bool splash_restore_buffer_after_network(void) {
#ifdef BOARD_HAS_PSRAM
    return true;
#else
    if (!canvas_buffer_lent) return true;
    canvas_buf = (uint16_t*)heap_caps_malloc(
        canvas_w * canvas_h * 2, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!canvas_buf) {
        Serial.println("splash: failed to restore canvas after network request");
        return false;
    }
    lv_canvas_set_buffer(canvas, canvas_buf, canvas_w, canvas_h, LV_COLOR_FORMAT_RGB565);
    render_hermes_splash();
    lv_obj_clear_flag(canvas, LV_OBJ_FLAG_HIDDEN);
    canvas_buffer_lent = false;
    return true;
#endif
}

void splash_next(void) {
    cur_anim = (cur_anim + 1) % 4;
    frame_started_ms = millis();
    last_pick_ms = frame_started_ms;
    render_hermes_splash();
    Serial.printf("splash: hermes mode %u\n", (unsigned)cur_anim);
}

void splash_pick_for_current_rate(void) {
    int g = usage_rate_group();
    if (g < 0) g = 0;
    if (g > 3) g = 3;
    cur_anim = (uint16_t)g;
    frame_started_ms = millis();
    last_pick_ms = frame_started_ms;
    render_hermes_splash();
}

void splash_pick_for_prepaid(int balance_pct) {
    // Map remaining balance % → Hermes animation (0=Idle, 3=Heavy)
    uint16_t anim;
    if (balance_pct >= 75)      anim = 0;  // plenty → rest
    else if (balance_pct >= 50) anim = 1;  // ok → normal
    else if (balance_pct >= 25) anim = 2;  // low → active
    else                        anim = 3;  // critical → heavy
    cur_anim = anim;
    frame_started_ms = millis();
    last_pick_ms = frame_started_ms;
    render_hermes_splash();
}

void splash_set_prepaid_balance(int balance_pct) {
    g_prepaid_balance = balance_pct;
}

bool splash_is_active(void) { return active; }

void splash_show(void) {
    if (g_prepaid_balance >= 0) {
        splash_pick_for_prepaid(g_prepaid_balance);
    } else if (pet_buffer_ready()) {
        // Keep the pet visible — don't select Hermes animation
        render_hermes_splash();
    } else {
        splash_pick_for_current_rate();
    }
    if (splash_container) lv_obj_clear_flag(splash_container, LV_OBJ_FLAG_HIDDEN);
    active = true;
}

void splash_hide(void) {
    if (splash_container) lv_obj_add_flag(splash_container, LV_OBJ_FLAG_HIDDEN);
    active = false;
}

lv_obj_t* splash_get_root(void) {
    return splash_container;
}
void splash_set_hint(const char* text) {
    (void)text;
}

void splash_notify_pet_changed(void) {
    s_splash_pet_timer = millis();
    s_splash_pet_frame = 0;
}

void splash_show_hint(bool show) {
    (void)show;
}

