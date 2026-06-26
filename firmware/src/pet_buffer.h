#pragma once
#include <stdint.h>
#include <stddef.h>

#define PET_GRID 20
#define PET_CELLS 400 // 20 × 20
#define PET_PAL_MAX 16
#define PET_MAX_FRAMES 48
#define PET_MAX_FRAMES_STORED 1    // Store only 1 frame (matches what daemon sends)
#define PET_BUF_BYTES (PET_MAX_FRAMES_STORED * PET_CELLS) // 400

// BLE payload header: hold_ms(2) + frame_count(2) + palette(32)
#define PET_BLE_HEADER    36

// ── Lifecycle ──
bool   pet_buffer_alloc(void);          // malloc(PET_BUF_BYTES), no PSRAM
void   pet_buffer_free(void);

// ── BLE callback calls this (NimBLE task context) ──
//   payload format: [hold_ms:u16][frame_count:u16][palette:10×u16][N×400 bytes]
//   g_pet_loaded = true only AFTER full memcpy.
bool   pet_buffer_load(const uint8_t* data, size_t len);

// ── Main loop reads (tick-safe: g_pet_loaded toggled atomically after write) ──
bool     pet_buffer_ready(void);         // data loaded + alloc succeeded
void     pet_buffer_clear(void);         // daemon -> stop pet -> clear pet
void     pet_buffer_tick(void);          // apply staged back-buffer from main loop
uint16_t pet_buffer_hold_ms(void);
uint16_t pet_buffer_frame_count(void);
const uint16_t* pet_buffer_palette(void); // [PET_PAL_MAX] RGB565
const uint8_t*  pet_buffer_frame(int i);  // 400 bytes or NULL
