#pragma once
#include <stdint.h>
#include <lvgl.h>

// Initialize splash module. Creates the centered canvas widget inside `parent`
// and allocates a square RGB565 buffer sized for the active board.
void splash_init(lv_obj_t *parent);

// Advance the Hermes splash animation. Call from main loop.
void splash_tick(void);

// Cycle to the next Hermes splash mode.
void splash_next(void);

// Show/hide the splash container.
void splash_show(void);
void splash_hide(void);

// Pick the Hermes splash mode that matches the current usage-rate group.
void splash_pick_for_current_rate(void);

// Pick the Hermes splash mode based on remaining prepaid balance (%).
//   balance_pct 0-100: 0=empty, 100=fully topped up.
void splash_pick_for_prepaid(int balance_pct);

// Set prepaid balance for auto-picking on next splash_show().
// Pass -1 to revert to rate-based picking.
void splash_set_prepaid_balance(int balance_pct);

// True when splash is currently rendering (used to gate re-picks).
bool splash_is_active(void);

// Root container (so ui.cpp can attach a click event).
//
// Hint hooks are kept as no-ops for compatibility with main.cpp's pairing UX.
void splash_set_hint(const char* text);
void splash_show_hint(bool show);
lv_obj_t* splash_get_root(void);

// Mini animated creature for embedding elsewhere (e.g. the idle screen).
// Renders the named claudepix animation (e.g. "expression sleep") at ~px×px
// inside `parent`; returns the canvas object (position it with lv_obj_align) or
// NULL if the animation isn't found / allocation fails. Drive it with
// splash_mini_tick(). One mini creature at a time.
lv_obj_t* splash_mini_create(lv_obj_t *parent, const char *anim_name, int px);
void splash_mini_tick(void);
