#include "pet_buffer.h"
#include <stdlib.h>
#include <string.h>
#include <Arduino.h>  // for Serial

static uint8_t*  g_frames  = NULL;
static uint16_t  g_hold_ms = 200;
static uint16_t  g_nframes = 0;
static uint16_t  g_pal[PET_PAL_MAX] = {0};
static bool      g_ready   = false;

bool pet_buffer_alloc(void) {
    g_frames = (uint8_t*)malloc(PET_BUF_BYTES);
    if (!g_frames) {
        Serial.println("pet_buffer: malloc failed (no PSRAM needed, just OOM)");
        return false;
    }
    memset(g_frames, 0, PET_BUF_BYTES);
    g_ready = false;
    Serial.printf("pet_buffer: allocated %u bytes in DRAM\n", PET_BUF_BYTES);
    return true;
}

void pet_buffer_free(void) {
    free(g_frames);
    g_frames = NULL;
    g_ready = false;
}

bool pet_buffer_load(const uint8_t* data, size_t len) {
    if (!g_frames) return false;

    // Mark NOT ready while we write
    g_ready = false;

    if (len < 4) return false;  // hold_ms + frame_count minimum

    g_hold_ms = data[0] | (data[1] << 8);
    g_nframes = data[2] | (data[3] << 8);
    if (g_nframes > PET_MAX_FRAMES) g_nframes = PET_MAX_FRAMES;
    if (g_nframes < 1) g_nframes = 1;  // prevent divide-by-zero in modulo ops

    // Palette: next 20 bytes
    memcpy(g_pal, data + 4, PET_PAL_MAX * 2);

    // Frames: N × 400 bytes
    size_t frame_bytes = g_nframes * PET_CELLS;
    size_t available = (len > PET_BLE_HEADER) ? (len - PET_BLE_HEADER) : 0;
    if (frame_bytes > available) frame_bytes = available;
    if (frame_bytes > 0) {
        memcpy(g_frames, data + PET_BLE_HEADER, frame_bytes);
    }

    // Barrier: all writes visible before the flag
    g_ready = true;
    Serial.printf("pet_buffer: loaded %u frames (%u bytes)\n", g_nframes, frame_bytes);
    return true;
}

bool pet_buffer_ready(void)        { return g_ready && g_frames; }
uint16_t pet_buffer_hold_ms(void)  { return g_hold_ms; }
uint16_t pet_buffer_frame_count(void) { return g_nframes; }
const uint16_t* pet_buffer_palette(void) { return g_pal; }
const uint8_t* pet_buffer_frame(int i) {
    if (!g_ready || i < 0 || i >= (int)g_nframes) return NULL;
    return g_frames + i * PET_CELLS;
}
