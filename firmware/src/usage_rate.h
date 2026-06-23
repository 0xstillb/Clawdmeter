#pragma once

// Tracks short-term rate of change in the top-bar percentage (%/min) so the UI
// can react to *how heavily* the active provider is being used right now, not
// just the current bucket level. Returns one of 4 group indices for the splash
// to pick animations from.

// Feed in the latest top-bar percentage every time fresh BLE data arrives.
void usage_rate_sample(float top_pct);

// 0 = idle, 1 = normal, 2 = active, 3 = heavy.
// Defaults to 0 when the buffer doesn't have enough samples yet.
int usage_rate_group(void);
