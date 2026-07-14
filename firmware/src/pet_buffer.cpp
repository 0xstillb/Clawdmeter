#include "pet_buffer.h"
#include <stdlib.h>
#include <string.h>
#include <Arduino.h>  // for Serial

static uint8_t*  g_frames  = NULL;
static uint8_t*  g_back_buffer = NULL;  // staging area written by BLE callback
static uint16_t  g_hold_ms = 200;
static uint16_t  g_nframes = 0;
static uint16_t  g_pal[PET_PAL_MAX] = {0};
static bool      g_ready   = false;
static volatile bool g_back_buffer_fresh = false;

bool pet_buffer_alloc(void) {
    g_frames = (uint8_t*)malloc(PET_BUF_BYTES);
    g_back_buffer = (uint8_t*)malloc(PET_BUF_BYTES);
    if (!g_frames || !g_back_buffer) {
        Serial.println("pet_buffer: malloc failed (no PSRAM needed, just OOM)");
        free(g_frames); g_frames = NULL;
        free(g_back_buffer); g_back_buffer = NULL;
        return false;
    }
    memset(g_frames, 0, PET_BUF_BYTES);
    memset(g_back_buffer, 0, PET_BUF_BYTES);
    Serial.printf("pet_buffer: allocated %u bytes x2 (front+back) in DRAM\n", PET_BUF_BYTES * 2);
    return true;
}

void pet_buffer_free(void) {
    free(g_frames);
    free(g_back_buffer);
    g_frames = NULL;
    g_back_buffer = NULL;
    g_ready = false;
}

void pet_buffer_clear(void) {
    g_ready = false;
    g_back_buffer_fresh = false;
    if (g_frames) memset(g_frames, 0, PET_BUF_BYTES);
    if (g_back_buffer) memset(g_back_buffer, 0, PET_BUF_BYTES);
}

bool pet_buffer_load(const uint8_t* data, size_t len) {
    if (!g_frames || !g_back_buffer) return false;

    // Every update carries one complete frame. Reject truncated long writes
    // before reading the palette or exposing stale pixels to the renderer.
    if (len < PET_BLE_HEADER + PET_CELLS) return false;

    // Minimal parsing in NimBLE task context; the heavy memcpy goes to the
    // back buffer and the main loop applies it via pet_buffer_tick().
    g_hold_ms = data[0] | (data[1] << 8);
    g_nframes = data[2] | (data[3] << 8);
    if (g_nframes > PET_MAX_FRAMES) g_nframes = PET_MAX_FRAMES;
    if (g_nframes > PET_MAX_FRAMES_STORED) g_nframes = PET_MAX_FRAMES_STORED;
    if (g_nframes < 1) g_nframes = 1;

    memcpy(g_pal, data + 4, PET_PAL_MAX * 2);

    size_t frame_bytes = g_nframes * PET_CELLS;
    size_t available = (len > PET_BLE_HEADER) ? (len - PET_BLE_HEADER) : 0;
    if (frame_bytes > available) frame_bytes = available;
    if (frame_bytes > 0) {
        memcpy(g_back_buffer, data + PET_BLE_HEADER, frame_bytes);
    }

    g_back_buffer_fresh = true;
    return true;
}

// Apply staged pet data from the main loop context (not NimBLE callback).
// This prevents Task Watchdog triggers when heavy copies run on CPU0.
void pet_buffer_tick(void) {
    if (!g_back_buffer_fresh) return;
    g_back_buffer_fresh = false;

    memcpy(g_frames, g_back_buffer, PET_BUF_BYTES);

    if (!g_ready) {
        g_ready = true;
    }
    Serial.printf("pet_buffer: applied %u frames\n", g_nframes);
}

bool pet_buffer_ready(void)        { return g_ready && g_frames; }
uint16_t pet_buffer_hold_ms(void)  { return g_hold_ms; }
uint16_t pet_buffer_frame_count(void) { return g_nframes; }
const uint16_t* pet_buffer_palette(void) { return g_pal; }
const uint8_t* pet_buffer_frame(int i) {
    if (!g_ready || i < 0 || i >= (int)g_nframes) return NULL;
    return g_frames + i * PET_CELLS;
}
