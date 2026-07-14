#pragma once

#include <stdbool.h>

#include "data.h"

enum wifi_fallback_state_t {
    WIFI_FALLBACK_NOT_CONFIGURED,
    WIFI_FALLBACK_STANDBY,
    WIFI_FALLBACK_CONNECTING,
    WIFI_FALLBACK_CONNECTED,
    WIFI_FALLBACK_ERROR,
};

// Direct Wi-Fi polling is deliberately limited to API-key providers.  Providers
// which require a browser cookie or workspace ID remain on the host BLE daemon.
void wifi_fallback_init(void);
bool wifi_fallback_is_configured(void);
wifi_fallback_state_t wifi_fallback_get_state(void);
const char* wifi_fallback_state_name(wifi_fallback_state_t state);
void wifi_fallback_note_ble_data(void);

// Applies a tray-sent {"wifi": ...} configuration message. Credentials are
// never printed and are stored in NVS only after all fields validate.
bool wifi_fallback_apply_ble_config(const char* json);

// Call frequently from loop(). Returns true once per successful Wi-Fi poll and
// writes a display-ready usage snapshot to out.
bool wifi_fallback_tick(UsageData* out);

// Handles the "wifi ..." serial commands. The command buffer may be modified.
bool wifi_fallback_handle_serial_command(char* command);
