#pragma once

#include <stddef.h>
#include <stdint.h>

enum UsageProvider : uint8_t {
    USAGE_PROVIDER_CLAUDE = 0,
    USAGE_PROVIDER_CODEX,
    USAGE_PROVIDER_OPENROUTER,
    USAGE_PROVIDER_ZEN,
    USAGE_PROVIDER_GO,
    USAGE_PROVIDER_DEEPSEEK,
    USAGE_PROVIDER_MINIMAX,
    USAGE_PROVIDER_UNKNOWN,
};

struct UsagePanelData {
    char label[16];
    float pct;
    int reset_mins;
    char subtext[40];
    char kind[20];
    bool has_reset;
    bool valid;
};

struct UsageData {
    UsageProvider provider;
    char mode[20];
    UsagePanelData top;
    UsagePanelData bottom;
    char status[24];
    bool ok;
    bool valid;
};
