#include "wifi_fallback.h"
#include "ble.h"
#include "splash.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <esp_crt_bundle.h>
#include <esp_event.h>
#include <esp_http_client.h>
#include <esp_heap_caps.h>
#include <esp_netif.h>
#include <esp_wifi.h>
#include <esp_wifi_default.h>
#include <time.h>

#include <stdio.h>
#include <string.h>

namespace {

constexpr uint32_t BLE_GRACE_MS = 90UL * 1000UL;
constexpr uint32_t POLL_INTERVAL_MS = 60UL * 1000UL;
constexpr uint32_t CONNECT_RETRY_MS = 20UL * 1000UL;
constexpr int HTTP_TIMEOUT_MS = 12000;
// MiniMax can return several quota lanes in one response. This buffer is
// allocated only during the request, so it does not consume permanent DRAM.
constexpr size_t RESPONSE_CAPACITY = 4096;

constexpr const char* PREFS_NAMESPACE = "clawd_wifi";
constexpr const char* KEY_SSID = "ssid";
constexpr const char* KEY_PASSWORD = "password";
constexpr const char* KEY_PROVIDER = "provider";
constexpr const char* KEY_API_KEY = "api_key";

enum class ApiProvider : uint8_t { NONE, DEEPSEEK, OPENROUTER, MINIMAX };

struct Settings {
    String ssid;
    String password;
    String api_key;
    ApiProvider provider = ApiProvider::NONE;
};

struct HttpResponse {
    char body[RESPONSE_CAPACITY + 1] = {};
    size_t length = 0;
    bool truncated = false;
};

Settings settings;
bool wifi_started = false;
bool wifi_initialized = false;
bool ntp_requested = false;
bool wifi_connection_announced = false;
bool wifi_driver_owned = false;
bool wifi_netif_owned = false;
esp_netif_t* wifi_netif = nullptr;
uint32_t last_ble_data_ms = 0;
uint32_t last_poll_ms = 0;
uint32_t last_connect_attempt_ms = 0;
wifi_fallback_state_t runtime_state = WIFI_FALLBACK_NOT_CONFIGURED;

const char* runtime_state_name(wifi_fallback_state_t state) {
    switch (state) {
        case WIFI_FALLBACK_STANDBY: return "standby";
        case WIFI_FALLBACK_CONNECTING: return "connecting";
        case WIFI_FALLBACK_CONNECTED: return "connected";
        case WIFI_FALLBACK_ERROR: return "error";
        default: return "not_configured";
    }
}

void set_runtime_state(wifi_fallback_state_t next) {
    if (runtime_state == next) return;
    runtime_state = next;
    ble_publish_wifi_runtime_state(runtime_state_name(next));
    Serial.printf("Wi-Fi fallback state: %s\n", runtime_state_name(next));
}

const char* provider_name(ApiProvider provider) {
    switch (provider) {
        case ApiProvider::DEEPSEEK: return "deepseek";
        case ApiProvider::OPENROUTER: return "openrouter";
        case ApiProvider::MINIMAX: return "minimax";
        default: return "none";
    }
}

ApiProvider provider_from_name(const char* name) {
    if (!name) return ApiProvider::NONE;
    if (strcmp(name, "deepseek") == 0) return ApiProvider::DEEPSEEK;
    if (strcmp(name, "openrouter") == 0) return ApiProvider::OPENROUTER;
    if (strcmp(name, "minimax") == 0) return ApiProvider::MINIMAX;
    return ApiProvider::NONE;
}

bool configured() {
    return !settings.ssid.isEmpty()
        && !settings.api_key.isEmpty()
        && settings.provider != ApiProvider::NONE;
}

void clear_panel(UsagePanelData* panel) {
    memset(panel, 0, sizeof(*panel));
    panel->reset_mins = -1;
}

void copy_text(char* dest, size_t size, const char* source) {
    if (!dest || size == 0) return;
    snprintf(dest, size, "%s", source ? source : "");
}

void set_panel(UsagePanelData* panel, const char* label, float pct,
               int reset_mins, bool has_reset, const char* kind,
               const char* subtext) {
    clear_panel(panel);
    copy_text(panel->label, sizeof(panel->label), label);
    panel->pct = pct;
    panel->reset_mins = reset_mins;
    panel->has_reset = has_reset;
    panel->valid = true;
    copy_text(panel->kind, sizeof(panel->kind), kind);
    copy_text(panel->subtext, sizeof(panel->subtext), subtext);
}

void init_usage(UsageData* out, UsageProvider provider, const char* mode,
                const char* plan_type, const char* status, bool ok) {
    memset(out, 0, sizeof(*out));
    out->provider = provider;
    copy_text(out->mode, sizeof(out->mode), mode);
    copy_text(out->plan_type, sizeof(out->plan_type), plan_type);
    copy_text(out->status, sizeof(out->status), status);
    out->ok = ok;
    out->valid = true;
    out->budget = 20.0f;
}

float number_or(JsonVariantConst value, float fallback = 0.0f) {
    if (value.is<float>() || value.is<double>() || value.is<int>() || value.is<long>()) {
        return value.as<float>();
    }
    if (value.is<const char*>()) return String(value.as<const char*>()).toFloat();
    return fallback;
}

int percent(float value) {
    if (value < 0) return 0;
    if (value > 100) return 100;
    return (int)(value + 0.5f);
}

int minutes_until_midnight() {
    time_t now = time(nullptr);
    struct tm local = {};
    localtime_r(&now, &local);
    const int elapsed = local.tm_hour * 60 + local.tm_min;
    return 24 * 60 - elapsed;
}

int minutes_from_epoch_or_seconds(JsonVariantConst epoch, JsonVariantConst seconds) {
    const float epoch_value = number_or(epoch, 0.0f);
    if (epoch_value > 0) {
        time_t target = (time_t)(epoch_value > 10000000000.0f ? epoch_value / 1000.0f : epoch_value);
        time_t now = time(nullptr);
        if (target > now) return (int)((target - now + 30) / 60);
    }
    float duration = number_or(seconds, 0.0f);
    if (duration > 864000.0f) duration /= 1000.0f;
    return duration > 0 ? (int)((duration + 30) / 60) : 0;
}

esp_err_t http_event(esp_http_client_event_t* event) {
    if (event->event_id != HTTP_EVENT_ON_DATA || !event->data || event->data_len <= 0) return ESP_OK;
    HttpResponse* response = static_cast<HttpResponse*>(event->user_data);
    if (!response) return ESP_FAIL;
    const size_t available = RESPONSE_CAPACITY - response->length;
    const size_t received = (size_t)event->data_len;
    const size_t copy_len = received < available ? received : available;
    if (copy_len) {
        memcpy(response->body + response->length, event->data, copy_len);
        response->length += copy_len;
        response->body[response->length] = '\0';
    }
    if (copy_len != received) response->truncated = true;
    return ESP_OK;
}

bool get_json(const char* url, const char* api_key, HttpResponse* response, int* status_out) {
    if (!url || !api_key || !response || !status_out) return false;
    esp_http_client_config_t config = {};
    config.url = url;
    config.method = HTTP_METHOD_GET;
    config.timeout_ms = HTTP_TIMEOUT_MS;
    config.event_handler = http_event;
    config.user_data = response;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    config.keep_alive_enable = false;

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return false;
    char authorization[256] = {};
    snprintf(authorization, sizeof(authorization), "Bearer %s", api_key);
    esp_http_client_set_header(client, "Authorization", authorization);
    esp_http_client_set_header(client, "Accept", "application/json");
    esp_http_client_set_header(client, "User-Agent", "clawdmeter/1.0");
    if (settings.provider == ApiProvider::MINIMAX) {
        esp_http_client_set_header(client, "MM-API-Source", "Clawdmeter");
    }

    const esp_err_t result = esp_http_client_perform(client);
    *status_out = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    return result == ESP_OK && !response->truncated;
}

bool parse_deepseek(const char* json, UsageData* out) {
    JsonDocument doc;
    if (deserializeJson(doc, json)) return false;
    JsonArrayConst entries = doc["balance_infos"].as<JsonArrayConst>();
    if (entries.isNull() || entries.size() == 0) return false;
    JsonObjectConst entry = entries[0].as<JsonObjectConst>();
    for (JsonVariantConst candidate : entries) {
        JsonObjectConst item = candidate.as<JsonObjectConst>();
        const char* currency = item["currency"] | "";
        if (strcmp(currency, "USD") == 0) { entry = item; break; }
    }
    const float balance = number_or(entry["total_balance"]);
    const char* currency = entry["currency"] | "CNY";
    const bool available = doc["is_available"] | true;
    const uint32_t today = (uint32_t)(time(nullptr) / 86400);
    Preferences prefs;
    prefs.begin(PREFS_NAMESPACE, false);
    const uint32_t saved_day = prefs.getULong("ds_day", 0);
    float baseline = saved_day == today ? prefs.getFloat("ds_base", balance) : balance;
    if (baseline < balance) baseline = balance;  // a top-up starts a new high-water mark
    prefs.putULong("ds_day", today);
    prefs.putFloat("ds_base", baseline);
    prefs.end();
    const float used = baseline > balance ? baseline - balance : 0.0f;
    char used_text[40] = {};
    snprintf(used_text, sizeof(used_text), "%s %.2f", currency, used);
    char balance_text[40] = {};
    snprintf(balance_text, sizeof(balance_text), "%s %.2f", currency, balance);
    init_usage(out, USAGE_PROVIDER_DEEPSEEK, "prepaid", "prepaid",
               available && balance > 0 ? "allowed" : "limited", available);
    set_panel(&out->top, "Used", used, minutes_until_midnight(), true,
              "budget_daily", used_text);
    set_panel(&out->bottom, "Remaining", balance, 0, false,
              "wallet_depletion", balance > 0 ? balance_text : "Add credits");
    out->budget = baseline > 0 ? baseline : 20.0f;
    return true;
}

bool parse_openrouter(const char* json, UsageData* out) {
    JsonDocument doc;
    if (deserializeJson(doc, json)) return false;
    JsonObjectConst data = doc["data"].as<JsonObjectConst>();
    if (data.isNull()) return false;
    const float used = number_or(data["usage"]);
    const float limit = number_or(data["limit"]);
    if (limit <= 0) return false;
    const float remaining = limit > used ? limit - used : 0.0f;
    const int remaining_pct = percent(remaining / limit * 100.0f);
    const char* status = remaining_pct <= 10 ? "limited" : remaining_pct <= 25 ? "warning" : "allowed";
    char used_text[40] = {};
    snprintf(used_text, sizeof(used_text), "%.2f credits", used);
    char remaining_text[40] = {};
    snprintf(remaining_text, sizeof(remaining_text), "%.2f credits", remaining);
    init_usage(out, USAGE_PROVIDER_OPENROUTER, "prepaid", "prepaid", status, true);
    set_panel(&out->top, "Used", used, minutes_until_midnight(), true,
              "budget_daily", used_text);
    set_panel(&out->bottom, "CR", remaining, 0, false,
              "wallet_depletion", remaining_text);
    out->budget = limit;
    return true;
}

JsonVariantConst first_value(JsonObjectConst obj, const char* first, const char* second) {
    JsonVariantConst value = obj[first];
    return value.isNull() ? obj[second] : value;
}

bool remaining_percent(JsonObjectConst item, const char* total_key, const char* total_alias,
                       const char* remaining_key, const char* remaining_alias,
                       const char* percent_key, const char* percent_alias, int* out_pct) {
    const JsonVariantConst total_value = first_value(item, total_key, total_alias);
    const JsonVariantConst remaining_value = first_value(item, remaining_key, remaining_alias);
    const float total = number_or(total_value, 0.0f);
    if (!total_value.isNull() && total > 0 && !remaining_value.isNull()) {
        *out_pct = percent(number_or(remaining_value) / total * 100.0f);
        return true;
    }
    const JsonVariantConst explicit_percent = first_value(item, percent_key, percent_alias);
    if (explicit_percent.isNull()) return false;
    *out_pct = percent(number_or(explicit_percent));
    return true;
}

bool parse_minimax(const char* json, UsageData* out) {
    JsonDocument doc;
    if (deserializeJson(doc, json)) return false;
    JsonObjectConst root = doc["data"].as<JsonObjectConst>();
    if (root.isNull()) root = doc.as<JsonObjectConst>();
    JsonArrayConst models = root["model_remains"].as<JsonArrayConst>();
    if (models.isNull() || models.size() == 0) return false;

    JsonObjectConst selected;
    int best_score = -1;
    for (JsonVariantConst candidate : models) {
        JsonObjectConst item = candidate.as<JsonObjectConst>();
        String name = String(first_value(item, "model_name", "modelName") | "");
        name.toLowerCase();
        if (name.indexOf("image") >= 0 || name.indexOf("video") >= 0 || name.indexOf("audio") >= 0) continue;
        int score = 0;
        if (name.startsWith("minimax-m")) score += 100;
        if (name.indexOf("text") >= 0 || name.indexOf("chat") >= 0 || name.indexOf("coding") >= 0) score += 20;
        if (number_or(first_value(item, "current_interval_total_count", "currentIntervalTotalCount")) > 0) score += 1000;
        if (score > best_score) { selected = item; best_score = score; }
    }
    if (selected.isNull()) selected = models[0].as<JsonObjectConst>();

    int rolling_pct = 0;
    int weekly_pct = 0;
    if (!remaining_percent(selected, "current_interval_total_count", "currentIntervalTotalCount",
                           "current_interval_usage_count", "currentIntervalUsageCount",
                           "current_interval_remaining_percent", "currentIntervalRemainingPercent", &rolling_pct)) {
        return false;
    }
    if (!remaining_percent(selected, "current_weekly_total_count", "currentWeeklyTotalCount",
                           "current_weekly_usage_count", "currentWeeklyUsageCount",
                           "current_weekly_remaining_percent", "currentWeeklyRemainingPercent", &weekly_pct)) {
        weekly_pct = rolling_pct;
    }
    const char* status = rolling_pct <= 10 || weekly_pct <= 10 ? "limited"
        : rolling_pct <= 25 || weekly_pct <= 25 ? "warning" : "allowed";
    const int rolling_reset = minutes_from_epoch_or_seconds(
        first_value(selected, "current_interval_end_time", "currentIntervalEndTime"),
        first_value(selected, "current_interval_remains_time", "currentIntervalRemainsTime"));
    const int weekly_reset = minutes_from_epoch_or_seconds(
        first_value(selected, "current_weekly_end_time", "currentWeeklyEndTime"),
        first_value(selected, "current_weekly_remains_time", "currentWeeklyRemainsTime"));
    init_usage(out, USAGE_PROVIDER_MINIMAX, "window", "subscription", status, true);
    set_panel(&out->top, "Current", rolling_pct, rolling_reset, true, "window_short", "");
    set_panel(&out->bottom, "Weekly", weekly_pct, weekly_reset, true, "window_long", "");
    return true;
}

bool poll_provider(UsageData* out) {
    static const char* minimax_urls[] = {
        "https://api.minimax.io/v1/token_plan/remains",
        "https://www.minimax.io/v1/token_plan/remains",
        "https://api.minimaxi.com/v1/token_plan/remains",
        "https://www.minimaxi.com/v1/token_plan/remains",
    };
    const char* urls[4] = {};
    size_t url_count = 1;
    switch (settings.provider) {
        case ApiProvider::DEEPSEEK:
            urls[0] = "https://api.deepseek.com/user/balance";
            break;
        case ApiProvider::OPENROUTER:
            urls[0] = "https://openrouter.ai/api/v1/auth/key";
            break;
        case ApiProvider::MINIMAX:
            for (size_t i = 0; i < 4; ++i) urls[i] = minimax_urls[i];
            url_count = 4;
            break;
        default:
            return false;
    }

    // The original ESP32 CYD has no PSRAM. Keep the response out of the loop
    // task stack and allocate it only while a fallback request is in flight.
    HttpResponse* response = static_cast<HttpResponse*>(malloc(sizeof(HttpResponse)));
    if (!response) {
        Serial.println("Wi-Fi fallback: insufficient heap for API response");
        return false;
    }
    bool success = false;
    for (size_t i = 0; i < url_count; ++i) {
        memset(response, 0, sizeof(*response));
        int status = 0;
        if (!get_json(urls[i], settings.api_key.c_str(), response, &status)) {
            Serial.printf("Wi-Fi fallback: request failed (%d)\n", status);
            continue;
        }
        if (status == 401 || status == 403) {
            Serial.println("Wi-Fi fallback: API key rejected");
            break;
        }
        if (status != 200) {
            Serial.printf("Wi-Fi fallback: API HTTP %d\n", status);
            continue;
        }
        bool parsed = false;
        if (settings.provider == ApiProvider::DEEPSEEK) parsed = parse_deepseek(response->body, out);
        if (settings.provider == ApiProvider::OPENROUTER) parsed = parse_openrouter(response->body, out);
        if (settings.provider == ApiProvider::MINIMAX) parsed = parse_minimax(response->body, out);
        if (parsed) {
            success = true;
            break;
        }
        Serial.println("Wi-Fi fallback: unexpected API response");
    }
    free(response);
    return success;
}

void load_settings() {
    Preferences prefs;
    // Opening read-only logs an NVS error on a newly flashed board because
    // this namespace does not exist yet. Open writable once so NVS creates it.
    prefs.begin(PREFS_NAMESPACE, false);
    settings.ssid = prefs.isKey(KEY_SSID) ? prefs.getString(KEY_SSID) : "";
    settings.password = prefs.isKey(KEY_PASSWORD) ? prefs.getString(KEY_PASSWORD) : "";
    settings.api_key = prefs.isKey(KEY_API_KEY) ? prefs.getString(KEY_API_KEY) : "";
    const String provider = prefs.isKey(KEY_PROVIDER) ? prefs.getString(KEY_PROVIDER) : "";
    settings.provider = provider_from_name(provider.c_str());
    prefs.end();
}

void stop_wifi() {
    if (wifi_initialized) {
        esp_wifi_disconnect();
        esp_wifi_stop();
        // Arduino owns the process-wide Wi-Fi driver on ESP32. Deinitializing
        // it here after a failed station start leaves its RX buffers unusable
        // and can starve the shared Wi-Fi/BLE radio. Stopping the station is
        // enough while BLE is active; the next fallback attempt starts it.
        wifi_initialized = false;
        wifi_driver_owned = false;
    }
    if (wifi_netif && wifi_netif_owned) {
        esp_netif_destroy_default_wifi(wifi_netif);
    }
    wifi_netif = nullptr;
    wifi_netif_owned = false;
    wifi_started = false;
    ntp_requested = false;
    wifi_connection_announced = false;
}

bool station_is_connected() {
    if (!wifi_started) return false;
    wifi_ap_record_t ap = {};
    return esp_wifi_sta_get_ap_info(&ap) == ESP_OK;
}

bool begin_wifi() {
    // Record every attempt, including failed driver/config setup. Without this
    // a bad saved network retries once per main-loop iteration and disrupts
    // BLE radio time.
    last_connect_attempt_ms = millis();
    if (!wifi_initialized) {
        const esp_err_t netif_result = esp_netif_init();
        if (netif_result != ESP_OK && netif_result != ESP_ERR_INVALID_STATE) return false;
        const esp_err_t event_result = esp_event_loop_create_default();
        if (event_result != ESP_OK && event_result != ESP_ERR_INVALID_STATE) return false;
        // Arduino Core creates this default STA netif before setup(). Creating
        // it again triggers an ESP-IDF assertion and reboot loop on CYD.
        wifi_netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
        if (!wifi_netif) {
            wifi_netif = esp_netif_create_default_wifi_sta();
            wifi_netif_owned = wifi_netif != nullptr;
        }
        if (!wifi_netif) return false;
        wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
        // The PSRAM-less CYD keeps LVGL, its splash canvas, and NimBLE in
        // internal RAM. The IDF defaults reserve eight permanent RX buffers
        // plus large AMPDU windows; that allocation fails while the bonded
        // HID link is still connected. Direct quota polling is low bandwidth,
        // so a small non-AMPDU pool is sufficient and leaves BLE operational.
        init_config.static_rx_buf_num = 2;
        init_config.dynamic_rx_buf_num = 8;
        init_config.dynamic_tx_buf_num = 8;
        init_config.rx_ba_win = 2;
        init_config.ampdu_rx_enable = 0;
        init_config.ampdu_tx_enable = 0;
        Serial.printf("Wi-Fi fallback: init heap free=%u largest=%u\n",
                      (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
                      (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        const esp_err_t init_result = esp_wifi_init(&init_config);
        if (init_result != ESP_OK && init_result != ESP_ERR_INVALID_STATE) {
            Serial.printf("Wi-Fi fallback: driver init failed (%s)\n", esp_err_to_name(init_result));
            return false;
        }
        wifi_driver_owned = init_result == ESP_OK;
        esp_wifi_set_storage(WIFI_STORAGE_RAM);
        if (esp_wifi_set_mode(WIFI_MODE_STA) != ESP_OK) return false;
        wifi_initialized = true;
    }

    wifi_config_t station = {};
    snprintf((char*)station.sta.ssid, sizeof(station.sta.ssid), "%s", settings.ssid.c_str());
    snprintf((char*)station.sta.password, sizeof(station.sta.password), "%s", settings.password.c_str());
    if (esp_wifi_set_config(WIFI_IF_STA, &station) != ESP_OK) return false;
    const esp_err_t start_result = esp_wifi_start();
    if (start_result != ESP_OK && start_result != ESP_ERR_WIFI_CONN) return false;
    if (esp_wifi_connect() != ESP_OK) return false;
    wifi_started = true;
    Serial.printf("Wi-Fi fallback: connecting to %s\n", settings.ssid.c_str());
    return true;
}

bool time_is_valid() {
    return time(nullptr) > 1700000000;
}

void print_help() {
    Serial.println("Wi-Fi commands:");
    Serial.println("  wifi network <ssid> <password>");
    Serial.println("  wifi provider <deepseek|openrouter|minimax> <api-key>");
    Serial.println("  wifi status");
    Serial.println("  wifi now");
    Serial.println("  wifi clear");
    Serial.println("Wi-Fi runs only after BLE data has been absent for 90s.");
}

}  // namespace

void wifi_fallback_init(void) {
    load_settings();
    // Let an available BLE daemon win the first sync after every boot.
    last_ble_data_ms = millis();
    if (configured()) {
        set_runtime_state(WIFI_FALLBACK_STANDBY);
        Serial.printf("Wi-Fi fallback ready (%s); BLE remains preferred\n", provider_name(settings.provider));
    } else {
        set_runtime_state(WIFI_FALLBACK_NOT_CONFIGURED);
        Serial.println("Wi-Fi fallback not configured (type 'wifi help')");
    }
}

bool wifi_fallback_is_configured(void) {
    return configured();
}

wifi_fallback_state_t wifi_fallback_get_state(void) {
    return runtime_state;
}

const char* wifi_fallback_state_name(wifi_fallback_state_t state) {
    return runtime_state_name(state);
}

void wifi_fallback_note_ble_data(void) {
    last_ble_data_ms = millis();
    set_runtime_state(configured() ? WIFI_FALLBACK_STANDBY : WIFI_FALLBACK_NOT_CONFIGURED);
}

bool wifi_fallback_apply_ble_config(const char* json) {
    if (!json) return false;
    JsonDocument doc;
    if (deserializeJson(doc, json)) return false;
    JsonObjectConst wifi = doc["wifi"].as<JsonObjectConst>();
    if (wifi.isNull()) return false;

    const char* operation = wifi["op"] | "";
    if (strcmp(operation, "clear") == 0) {
        Preferences prefs;
        prefs.begin(PREFS_NAMESPACE, false);
        prefs.clear();
        prefs.end();
        settings = Settings{};
        stop_wifi();
        set_runtime_state(WIFI_FALLBACK_NOT_CONFIGURED);
        Serial.println("Wi-Fi fallback configuration cleared from BLE");
        return true;
    }
    if (strcmp(operation, "set") != 0) return false;

    const char* ssid = wifi["ssid"] | "";
    const char* password = wifi["password"] | "";
    const char* provider = wifi["provider"] | "";
    const char* api_key = wifi["api_key"] | "";
    const ApiProvider parsed = provider_from_name(provider);
    if (!ssid[0] || strlen(ssid) > 32 || !password[0] || strlen(password) > 63
        || parsed == ApiProvider::NONE || !api_key[0] || strlen(api_key) > 192) {
        return false;
    }

    Preferences prefs;
    prefs.begin(PREFS_NAMESPACE, false);
    prefs.putString(KEY_SSID, ssid);
    prefs.putString(KEY_PASSWORD, password);
    prefs.putString(KEY_PROVIDER, provider_name(parsed));
    prefs.putString(KEY_API_KEY, api_key);
    prefs.end();
    load_settings();
    stop_wifi();
    set_runtime_state(WIFI_FALLBACK_STANDBY);
    Serial.printf("Wi-Fi fallback configured from BLE: %s on %s\n",
                  provider_name(parsed), settings.ssid.c_str());
    return true;
}

bool wifi_fallback_tick(UsageData* out) {
    if (!out) return false;
    if (!configured()) {
        set_runtime_state(WIFI_FALLBACK_NOT_CONFIGURED);
        return false;
    }
    const uint32_t now = millis();
    if (last_ble_data_ms != 0 && now - last_ble_data_ms < BLE_GRACE_MS) {
        stop_wifi();
        set_runtime_state(WIFI_FALLBACK_STANDBY);
        return false;
    }
    if (!wifi_started) {
        set_runtime_state(WIFI_FALLBACK_CONNECTING);
        if (last_connect_attempt_ms == 0 || now - last_connect_attempt_ms >= CONNECT_RETRY_MS) {
            if (!begin_wifi()) set_runtime_state(WIFI_FALLBACK_ERROR);
        }
        return false;
    }
    if (!station_is_connected()) {
        set_runtime_state(WIFI_FALLBACK_CONNECTING);
        if (now - last_connect_attempt_ms >= CONNECT_RETRY_MS && !begin_wifi()) {
            set_runtime_state(WIFI_FALLBACK_ERROR);
        }
        return false;
    }
    set_runtime_state(WIFI_FALLBACK_CONNECTED);
    if (!wifi_connection_announced) {
        wifi_connection_announced = true;
        Serial.println("Wi-Fi fallback: connected");
    }
    if (!ntp_requested) {
        configTime(0, 0, "time.cloudflare.com", "pool.ntp.org");
        ntp_requested = true;
        Serial.println("Wi-Fi fallback: synchronizing time for TLS");
        return false;
    }
    if (!time_is_valid()) return false;
    if (last_poll_ms != 0 && now - last_poll_ms < POLL_INTERVAL_MS) return false;
    last_poll_ms = now;
    if (!ble_pause_for_wifi_request()) {
        set_runtime_state(WIFI_FALLBACK_ERROR);
        return false;
    }
    const bool splash_buffer_lent = splash_release_buffer_for_network();
    Serial.printf("Wi-Fi fallback: HTTPS heap free=%u largest=%u\n",
                  (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
                  (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    const bool updated = poll_provider(out);
    if (splash_buffer_lent && !splash_restore_buffer_after_network()) {
        Serial.println("Wi-Fi fallback: splash buffer restore deferred");
    }
    const bool ble_resumed = ble_resume_after_wifi_request();
    if (!ble_resumed) Serial.println("Wi-Fi fallback: BLE will retry after restart");
    if (!updated) return false;
    Serial.printf("Wi-Fi fallback: updated %s\n", provider_name(settings.provider));
    return true;
}

bool wifi_fallback_handle_serial_command(char* command) {
    if (!command || strncmp(command, "wifi", 4) != 0
        || (command[4] != '\0' && command[4] != ' ')) return false;

    char* context = nullptr;
    strtok_r(command, " ", &context);  // wifi
    char* action = strtok_r(nullptr, " ", &context);
    if (!action || strcmp(action, "help") == 0) {
        print_help();
        return true;
    }
    if (strcmp(action, "status") == 0) {
        Serial.printf("Wi-Fi fallback: %s, state=%s, provider=%s, network=%s, BLE grace=%s\n",
                      configured() ? "configured" : "not configured",
                      runtime_state_name(runtime_state), provider_name(settings.provider),
                      settings.ssid.isEmpty() ? "none" : settings.ssid.c_str(),
                      (last_ble_data_ms != 0 && millis() - last_ble_data_ms < BLE_GRACE_MS) ? "active" : "expired");
        return true;
    }
    if (strcmp(action, "now") == 0) {
        last_ble_data_ms = 0;
        last_connect_attempt_ms = 0;
        stop_wifi();
        set_runtime_state(configured() ? WIFI_FALLBACK_CONNECTING
                                       : WIFI_FALLBACK_NOT_CONFIGURED);
        Serial.println("Wi-Fi fallback: forcing immediate diagnostic attempt");
        return true;
    }
    if (strcmp(action, "network") == 0) {
        char* ssid = strtok_r(nullptr, " ", &context);
        char* password = strtok_r(nullptr, " ", &context);
        if (!ssid || !password || strlen(ssid) > 32 || strlen(password) > 63) {
            Serial.println("Usage: wifi network <ssid> <password> (SSID <=32, password <=63)");
            return true;
        }
        Preferences prefs;
        prefs.begin(PREFS_NAMESPACE, false);
        prefs.putString(KEY_SSID, ssid);
        prefs.putString(KEY_PASSWORD, password);
        prefs.end();
        load_settings();
        stop_wifi();
        set_runtime_state(configured() ? WIFI_FALLBACK_STANDBY : WIFI_FALLBACK_NOT_CONFIGURED);
        Serial.println("Wi-Fi network saved");
        return true;
    }
    if (strcmp(action, "provider") == 0) {
        char* provider = strtok_r(nullptr, " ", &context);
        char* api_key = strtok_r(nullptr, " ", &context);
        const ApiProvider parsed = provider_from_name(provider);
        if (parsed == ApiProvider::NONE || !api_key || strlen(api_key) > 192) {
            Serial.println("Usage: wifi provider <deepseek|openrouter|minimax> <api-key>");
            return true;
        }
        Preferences prefs;
        prefs.begin(PREFS_NAMESPACE, false);
        prefs.putString(KEY_PROVIDER, provider_name(parsed));
        prefs.putString(KEY_API_KEY, api_key);
        prefs.end();
        load_settings();
        stop_wifi();
        set_runtime_state(configured() ? WIFI_FALLBACK_STANDBY : WIFI_FALLBACK_NOT_CONFIGURED);
        Serial.printf("Wi-Fi API provider saved: %s\n", provider_name(parsed));
        return true;
    }
    if (strcmp(action, "clear") == 0) {
        Preferences prefs;
        prefs.begin(PREFS_NAMESPACE, false);
        prefs.clear();
        prefs.end();
        settings = Settings{};
        stop_wifi();
        set_runtime_state(WIFI_FALLBACK_NOT_CONFIGURED);
        Serial.println("Wi-Fi fallback credentials cleared");
        return true;
    }
    print_help();
    return true;
}
