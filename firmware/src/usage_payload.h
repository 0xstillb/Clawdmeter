#pragma once

#include <stddef.h>

#include "data.h"

bool usage_parse_json(const char* json, UsageData* out);
bool usage_extract_brightness_pct(const char* json, uint8_t* out_pct);
void usage_panel_display_subtext(const UsagePanelData* panel, char* buf, size_t len);
