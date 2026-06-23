#pragma once

#include <stddef.h>

#include "data.h"

bool usage_parse_json(const char* json, UsageData* out);
void usage_panel_display_subtext(const UsagePanelData* panel, char* buf, size_t len);
