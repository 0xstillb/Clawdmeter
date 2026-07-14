#include "usage_payload.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void copy_text(char* dest, size_t len, const char* src) {
    if (!dest || len == 0) return;
    if (!src) {
        dest[0] = '\0';
        return;
    }

    size_t i = 0;
    while (i + 1 < len && src[i]) {
        dest[i] = src[i];
        ++i;
    }
    dest[i] = '\0';
}

static const char* skip_ws(const char* p) {
    while (p && *p && isspace((unsigned char)*p)) ++p;
    return p;
}

static const char* skip_ws_bound(const char* p, const char* end) {
    while (p && p < end && isspace((unsigned char)*p)) ++p;
    return p;
}

static void init_panel(UsagePanelData* panel) {
    if (!panel) return;
    panel->label[0] = '\0';
    panel->pct = 0.0f;
    panel->reset_mins = -1;
    panel->subtext[0] = '\0';
    panel->kind[0] = '\0';
    panel->has_reset = false;
    panel->valid = false;
}

static void init_usage(UsageData* out) {
    if (!out) return;
    out->provider = USAGE_PROVIDER_UNKNOWN;
    out->mode[0] = '\0';
    copy_text(out->plan_type, sizeof(out->plan_type), "subscription");
    init_panel(&out->top);
    init_panel(&out->bottom);
    copy_text(out->status, sizeof(out->status), "unknown");
    out->ok = false;
    out->valid = false;
    out->budget = 20.0f;
}

static bool find_key_in_span(const char* begin, const char* end, const char* key, const char** value_out) {
    if (!begin || !end || !key || !value_out || begin >= end) return false;

    const size_t key_len = strlen(key);
    for (const char* p = begin; p < end; ++p) {
        if (*p != '"') continue;

        const char* key_start = p + 1;
        if (key_start + key_len + 1 >= end) continue;
        if (memcmp(key_start, key, key_len) != 0) continue;
        if (key_start[key_len] != '"') continue;

        const char* after_key = skip_ws_bound(key_start + key_len + 1, end);
        if (!after_key || after_key >= end || *after_key != ':') continue;

        *value_out = skip_ws_bound(after_key + 1, end);
        return *value_out && *value_out < end;
    }

    return false;
}

static bool parse_string_value(const char* value, char* dest, size_t len) {
    if (!value || !dest || len == 0) return false;
    value = skip_ws(value);
    if (!value || *value != '"') return false;

    size_t i = 0;
    bool escaped = false;
    for (const char* p = value + 1; *p; ++p) {
        const char ch = *p;
        if (escaped) {
            char out = ch;
            switch (ch) {
                case 'n': out = '\n'; break;
                case 'r': out = '\r'; break;
                case 't': out = '\t'; break;
                case '\\': out = '\\'; break;
                case '"': out = '"'; break;
                default: break;
            }
            if (i + 1 < len) dest[i++] = out;
            escaped = false;
            continue;
        }
        if (ch == '\\') {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            dest[i] = '\0';
            return true;
        }
        if (i + 1 < len) dest[i++] = ch;
    }

    dest[0] = '\0';
    return false;
}

static bool parse_double_value(const char* value, double* out) {
    if (!value || !out) return false;
    value = skip_ws(value);
    if (!value || !*value) return false;

    char* end_ptr = nullptr;
    const double parsed = strtod(value, &end_ptr);
    if (end_ptr == value) return false;
    *out = parsed;
    return true;
}

static bool parse_int_value(const char* value, int* out) {
    double parsed = 0.0;
    if (!parse_double_value(value, &parsed)) return false;
    *out = (int)parsed;
    return true;
}

static bool parse_bool_value(const char* value, bool* out) {
    if (!value || !out) return false;
    value = skip_ws(value);
    if (!value) return false;
    if (strncmp(value, "true", 4) == 0) {
        *out = true;
        return true;
    }
    if (strncmp(value, "false", 5) == 0) {
        *out = false;
        return true;
    }
    return false;
}

static bool extract_object_span(const char* begin, const char* end, const char* key,
                                const char** obj_begin, const char** obj_end) {
    const char* value = nullptr;
    if (!find_key_in_span(begin, end, key, &value)) return false;
    value = skip_ws_bound(value, end);
    if (!value || value >= end || *value != '{') return false;

    int depth = 0;
    bool in_string = false;
    bool escaped = false;
    for (const char* p = value; p < end && *p; ++p) {
        const char ch = *p;
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }

        if (ch == '"') {
            in_string = true;
            continue;
        }
        if (ch == '{') {
            ++depth;
        } else if (ch == '}') {
            --depth;
            if (depth == 0) {
                *obj_begin = value;
                *obj_end = p + 1;
                return true;
            }
        }
    }

    return false;
}

static UsageProvider provider_from_text(const char* provider) {
    if (!provider || !*provider) return USAGE_PROVIDER_UNKNOWN;
    if (strcmp(provider, "claude") == 0) return USAGE_PROVIDER_CLAUDE;
    if (strcmp(provider, "codex") == 0) return USAGE_PROVIDER_CODEX;
    if (strcmp(provider, "openrouter") == 0) return USAGE_PROVIDER_OPENROUTER;
    if (strcmp(provider, "zen") == 0) return USAGE_PROVIDER_ZEN;
    if (strcmp(provider, "go") == 0) return USAGE_PROVIDER_GO;
    if (strcmp(provider, "deepseek") == 0) return USAGE_PROVIDER_DEEPSEEK;
    if (strcmp(provider, "minimax") == 0) return USAGE_PROVIDER_MINIMAX;
    return USAGE_PROVIDER_UNKNOWN;
}

static bool parse_string_field(const char* begin, const char* end, const char* key,
                               char* dest, size_t len) {
    const char* value = nullptr;
    if (!find_key_in_span(begin, end, key, &value)) return false;
    return parse_string_value(value, dest, len);
}

static bool parse_int_field(const char* begin, const char* end, const char* key, int* out) {
    const char* value = nullptr;
    if (!find_key_in_span(begin, end, key, &value)) return false;
    return parse_int_value(value, out);
}

static bool parse_float_field(const char* begin, const char* end, const char* key, float* out) {
    const char* value = nullptr;
    double parsed = 0.0;
    if (!find_key_in_span(begin, end, key, &value)) return false;
    if (!parse_double_value(value, &parsed)) return false;
    *out = (float)parsed;
    return true;
}

static bool parse_bool_field(const char* begin, const char* end, const char* key, bool* out) {
    const char* value = nullptr;
    if (!find_key_in_span(begin, end, key, &value)) return false;
    return parse_bool_value(value, out);
}

static bool parse_panel(const char* begin, const char* end, UsagePanelData* panel) {
    init_panel(panel);

    const bool has_label = parse_string_field(begin, end, "label", panel->label, sizeof(panel->label));
    const bool has_pct = parse_float_field(begin, end, "pct", &panel->pct);
    const bool has_reset_mins = parse_int_field(begin, end, "reset_mins", &panel->reset_mins);
    const bool has_subtext = parse_string_field(begin, end, "subtext", panel->subtext, sizeof(panel->subtext));
    parse_string_field(begin, end, "kind", panel->kind, sizeof(panel->kind));

    bool explicit_has_reset = false;
    if (parse_bool_field(begin, end, "has_reset", &explicit_has_reset)) {
        panel->has_reset = explicit_has_reset;
    } else {
        panel->has_reset = has_reset_mins;
    }

    if (!panel->has_reset && !has_subtext) return false;

    panel->valid = has_label && has_pct;
    return panel->valid;
}

static bool parse_provider_payload(const char* json, UsageData* out) {
    const char* end = json + strlen(json);
    const char* top_begin = nullptr;
    const char* top_end = nullptr;
    const char* bottom_begin = nullptr;
    const char* bottom_end = nullptr;
    if (!extract_object_span(json, end, "top", &top_begin, &top_end)) return false;
    if (!extract_object_span(json, end, "bottom", &bottom_begin, &bottom_end)) return false;

    char provider_text[20] = {0};
    parse_string_field(json, end, "p", provider_text, sizeof(provider_text));
    out->provider = provider_from_text(provider_text);
    parse_string_field(json, end, "plan_type", out->plan_type, sizeof(out->plan_type));
    parse_string_field(json, end, "mode", out->mode, sizeof(out->mode));
    parse_string_field(json, end, "st", out->status, sizeof(out->status));
    parse_bool_field(json, end, "ok", &out->ok);
    parse_float_field(json, end, "budget", &out->budget);

    if (!parse_panel(top_begin, top_end, &out->top)) return false;
    if (!parse_panel(bottom_begin, bottom_end, &out->bottom)) return false;

    out->valid = true;
    return true;
}

static bool parse_legacy_payload(const char* json, UsageData* out) {
    const char* end = json + strlen(json);
    float s = 0.0f;
    float w = 0.0f;
    int sr = -1;
    int wr = -1;

    if (!parse_float_field(json, end, "s", &s)) return false;
    if (!parse_int_field(json, end, "sr", &sr)) return false;
    if (!parse_float_field(json, end, "w", &w)) return false;
    if (!parse_int_field(json, end, "wr", &wr)) return false;

    char provider_text[20] = {0};
    if (parse_string_field(json, end, "p", provider_text, sizeof(provider_text))) {
        out->provider = provider_from_text(provider_text);
    } else {
        out->provider = USAGE_PROVIDER_CLAUDE;
    }
    if (out->provider == USAGE_PROVIDER_UNKNOWN) {
        out->provider = USAGE_PROVIDER_CLAUDE;
    }
    copy_text(out->mode, sizeof(out->mode), "legacy_flat");
    parse_string_field(json, end, "st", out->status, sizeof(out->status));
    parse_bool_field(json, end, "ok", &out->ok);

    copy_text(out->top.label, sizeof(out->top.label), "Current");
    out->top.pct = s;
    out->top.reset_mins = sr;
    copy_text(out->top.kind, sizeof(out->top.kind), "window_short");
    out->top.has_reset = true;
    out->top.valid = true;

    copy_text(out->bottom.label, sizeof(out->bottom.label), "Weekly");
    out->bottom.pct = w;
    out->bottom.reset_mins = wr;
    copy_text(out->bottom.kind, sizeof(out->bottom.kind), "window_long");
    out->bottom.has_reset = true;
    out->bottom.valid = true;

    out->valid = true;
    return true;
}

bool usage_parse_json(const char* json, UsageData* out) {
    if (!json || !out) return false;

    init_usage(out);
    if (parse_provider_payload(json, out)) return true;

    init_usage(out);
    if (parse_legacy_payload(json, out)) return true;

    init_usage(out);
    return false;
}

bool usage_extract_brightness_pct(const char* json, uint8_t* out_pct) {
    if (!json || !out_pct) return false;

    int pct = 0;
    const char* end = json + strlen(json);
    if (!parse_int_field(json, end, "brightness", &pct)) return false;
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;
    *out_pct = (uint8_t)pct;
    return true;
}

void usage_panel_display_subtext(const UsagePanelData* panel, char* buf, size_t len) {
    if (!buf || len == 0) return;
    buf[0] = '\0';

    if (!panel || !panel->valid) {
        copy_text(buf, len, "---");
        return;
    }

    if (!panel->has_reset) {
        if (panel->subtext[0]) copy_text(buf, len, panel->subtext);
        else                   copy_text(buf, len, "---");
        return;
    }

    const int mins = panel->reset_mins;
    if (mins < 0) {
        copy_text(buf, len, "---");
    } else if (mins < 60) {
        snprintf(buf, len, "Resets in %dm", mins);
    } else if (mins < 1440) {
        snprintf(buf, len, "Resets in %dh %dm", mins / 60, mins % 60);
    } else {
        snprintf(buf, len, "Resets in %dd %dh", mins / 1440, (mins % 1440) / 60);
    }
}
