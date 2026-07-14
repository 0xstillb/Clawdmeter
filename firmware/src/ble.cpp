#include "ble.h"
#include "pet_buffer.h"
#include "ui.h"
#include "wifi_fallback.h"
#include <Arduino.h>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>

#define DEVICE_NAME "Clawdmeter"

// Custom GATT UUIDs for data channel
#define SERVICE_UUID        "4c41555a-4465-7669-6365-000000000001"
#define RX_CHAR_UUID        "4c41555a-4465-7669-6365-000000000002"  // host writes here
#define TX_CHAR_UUID        "4c41555a-4465-7669-6365-000000000003"  // device ack/nack notifies
#define REQ_CHAR_UUID       "4c41555a-4465-7669-6365-000000000004"  // device-initiated refresh request

#define BLE_BUF_SIZE 512

// HID keyboard report descriptor (standard 6-KRO boot-protocol-compatible).
// Includes the LED output report (Num/Caps/Scroll Lock indicators) — without
// it macOS's Keyboard Setup Assistant flags the device as "unidentifiable"
// because the descriptor doesn't look like a complete keyboard.
static const uint8_t HID_REPORT_MAP[] = {
    0x05, 0x01,  // Usage Page (Generic Desktop)
    0x09, 0x06,  // Usage (Keyboard)
    0xA1, 0x01,  // Collection (Application)
    0x85, 0x01,  //   Report ID (1)
    0x05, 0x07,  //   Usage Page (Key Codes)
    0x19, 0xE0,  //   Usage Minimum (224) - Left Control
    0x29, 0xE7,  //   Usage Maximum (231) - Right GUI
    0x15, 0x00,  //   Logical Minimum (0)
    0x25, 0x01,  //   Logical Maximum (1)
    0x75, 0x01,  //   Report Size (1)
    0x95, 0x08,  //   Report Count (8)
    0x81, 0x02,  //   Input (Data, Variable, Absolute) - Modifier byte
    0x95, 0x01,  //   Report Count (1)
    0x75, 0x08,  //   Report Size (8)
    0x81, 0x01,  //   Input (Constant) - Reserved byte
    // LED output report — required for macOS to treat this as a full keyboard.
    0x95, 0x05,  //   Report Count (5)
    0x75, 0x01,  //   Report Size (1)
    0x05, 0x08,  //   Usage Page (LEDs)
    0x19, 0x01,  //   Usage Minimum (Num Lock)
    0x29, 0x05,  //   Usage Maximum (Kana)
    0x91, 0x02,  //   Output (Data, Variable, Absolute) - LED report
    0x95, 0x01,  //   Report Count (1)
    0x75, 0x03,  //   Report Size (3)
    0x91, 0x01,  //   Output (Constant) - LED report padding
    0x95, 0x06,  //   Report Count (6)
    0x75, 0x08,  //   Report Size (8)
    0x15, 0x00,  //   Logical Minimum (0)
    0x25, 0x65,  //   Logical Maximum (101)
    0x05, 0x07,  //   Usage Page (Key Codes)
    0x19, 0x00,  //   Usage Minimum (0)
    0x29, 0x65,  //   Usage Maximum (101)
    0x81, 0x00,  //   Input (Data, Array) - Key array (6 keys)
    0xC0,        // End Collection
};

static NimBLEServer* server = nullptr;
static NimBLEHIDDevice* hid_dev = nullptr;
static NimBLECharacteristic* input_kbd = nullptr;
static NimBLECharacteristic* tx_char = nullptr;
static NimBLECharacteristic* rx_char = nullptr;
static NimBLECharacteristic* req_char = nullptr;
static NimBLECharacteristic* pet_anim_char = nullptr;

static ble_state_t state = BLE_STATE_INIT;
static bool need_advertise = false;
static char rx_buf[BLE_BUF_SIZE];
static char rx_read_buf[BLE_BUF_SIZE];
static volatile bool data_ready = false;
static portMUX_TYPE rx_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile bool has_received_data = false;
// WinRT may cancel a GATT connection when a peripheral sends a notification
// from inside the client's CCCD subscription write.  Queue initial notices
// and send them from ble_tick() after that ATT operation has completed.
static volatile bool pending_refresh_request = false;
static volatile bool pending_screen_announce = false;
static volatile bool pending_wifi_configured = false;
static volatile bool pending_wifi_runtime_announce = false;
static volatile bool pending_wifi_snapshot_restore = false;
static volatile bool tx_subscribed = false;
static volatile uint32_t control_notify_after_ms = 0;
static volatile uint32_t wifi_snapshot_restore_after_ms = 0;
static bool radio_paused_for_wifi = false;
static char mac_str[18];

static void set_wifi_runtime_snapshot() {
    if (!tx_char) return;
    char buf[48];
    snprintf(buf, sizeof(buf), "{\"wifi_state\":\"%s\"}",
             wifi_fallback_state_name(wifi_fallback_get_state()));
    tx_char->setValue(buf);
}

static void schedule_wifi_snapshot_restore() {
    pending_wifi_snapshot_restore = true;
    wifi_snapshot_restore_after_ms = millis() + 200;
    control_notify_after_ms = millis() + 150;
}

static void start_advertising() {
    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->reset();
    // Primary advertising packet (≤31 bytes):
    //   flags (3) + appearance (4) + HID service 0x1812 (4) + name "Clawdmeter" (12)
    //   = 23 bytes. macOS Bluetooth Settings only surfaces BLE-only devices
    //   that explicitly advertise the standard HID service UUID (0x1812) —
    //   without it the device is recognized internally but hidden from the
    //   GUI nearby-devices list.
    adv->setAppearance(HID_KEYBOARD);
    adv->addServiceUUID(NimBLEUUID((uint16_t)0x1812));  // BLE HID Service
    adv->setName(DEVICE_NAME);
    // Scan response carries the 128-bit custom data-service UUID for active
    // scanners (the host daemon scans actively).
    NimBLEAdvertisementData scanResp;
    scanResp.setCompleteServices(NimBLEUUID(SERVICE_UUID));
    adv->setScanResponseData(scanResp);
    adv->enableScanResponse(true);
    bool ok = adv->start();
    // Only reflect ADVERTISING in the UI state when no client is connected.
    // With MAX_CONNECTIONS=2, onConnect re-advertises to fill the second slot;
    // without this guard the UI would flip CONNECTED → ADVERTISING on every
    // first connect and never come back until a second client arrived.
    if (!server || server->getConnectedCount() == 0) {
        state = BLE_STATE_ADVERTISING;
    }
    Serial.printf("BLE: advertising start=%s (connected=%u)\n",
        ok ? "OK" : "FAILED",
        server ? (unsigned)server->getConnectedCount() : 0);
}

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* s, NimBLEConnInfo& info) override {
        state = BLE_STATE_CONNECTED;
        tx_subscribed = false;
        Serial.printf("BLE: connected from %s (active=%u)\n",
            info.getAddress().toString().c_str(),
            (unsigned)s->getConnectedCount());
        // Announce the current screen once the central has subscribed to TX.
        // Notifying directly from onConnect can race the Windows GATT setup.
        pending_screen_announce = true;
        pending_wifi_configured = wifi_fallback_is_configured();
        pending_wifi_runtime_announce = true;
        // Keep advertising while a connection slot is still free so a second
        // central (e.g. the host daemon alongside an OS-held HID link) can
        // discover and connect. NimBLE auto-stops advertising on each accept.
        if (s->getConnectedCount() < CONFIG_BT_NIMBLE_MAX_CONNECTIONS) {
            need_advertise = true;
        }
    }

    void onDisconnect(NimBLEServer* s, NimBLEConnInfo& info, int reason) override {
        // Only flip the UI state to DISCONNECTED when the last client leaves.
        if (s->getConnectedCount() == 0) state = BLE_STATE_DISCONNECTED;
        need_advertise = true;
        tx_subscribed = false;
        Serial.printf("BLE: disconnected (reason=%d, remaining=%u)\n",
            reason, (unsigned)s->getConnectedCount());
    }

};

class RxCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* chr, NimBLEConnInfo& info) override {
        std::string val = chr->getValue();
        size_t len = std::min(val.length(), (size_t)(BLE_BUF_SIZE - 1));
        portENTER_CRITICAL(&rx_mux);
        memcpy(rx_buf, val.c_str(), len);
        rx_buf[len] = '\0';
        data_ready = true;
        portEXIT_CRITICAL(&rx_mux);
        has_received_data = true;
    }
};

class PetAnimCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* chr, NimBLEConnInfo& info) override {
        std::string val = chr->getValue();
        if (val.empty()) {
            pet_buffer_clear();
            Serial.println("BLE: pet cleared (empty payload)");
        } else {
            pet_buffer_load((const uint8_t*)val.data(), val.length());
            // Apply immediately via tick so the new frame shows up next render
        }
        ui_notify_pet_changed();
    }
};

// When the daemon enables notifications on the refresh char, ask for data
// if we have none yet. Firing on subscribe (not on connect) ensures the
// notification isn't dropped before the daemon's CCCD write completes.
class ReqCallbacks : public NimBLECharacteristicCallbacks {
    void onSubscribe(NimBLECharacteristic* chr, NimBLEConnInfo& info, uint16_t subValue) override {
        Serial.printf("BLE: req_char onSubscribe subValue=%u has_data=%d\n", subValue, has_received_data ? 1 : 0);
        if (subValue != 0 && !has_received_data) {
            pending_refresh_request = true;
        }
    }
};

class TxCallbacks : public NimBLECharacteristicCallbacks {
    void onSubscribe(NimBLECharacteristic*, NimBLEConnInfo&, uint16_t subValue) override {
        tx_subscribed = subValue != 0;
        if (tx_subscribed) {
            pending_screen_announce = true;
            pending_wifi_runtime_announce = true;
            // Let the WinRT CCCD write finish before the first notification.
            // Subsequent control notifications are paced in ble_tick().
            control_notify_after_ms = millis() + 250;
        }
    }
};

void ble_init(void) {
    radio_paused_for_wifi = false;
    NimBLEDevice::init(DEVICE_NAME);
    NimBLEDevice::setSecurityAuth(true, false, true);  // bonding, no MITM, SC

    // Format MAC address
    NimBLEAddress addr = NimBLEDevice::getAddress();
    snprintf(mac_str, sizeof(mac_str), "%s", addr.toString().c_str());
    for (int i = 0; mac_str[i]; i++) {
        if (mac_str[i] >= 'a' && mac_str[i] <= 'f') mac_str[i] -= 32;
    }

    server = NimBLEDevice::createServer();
    static ServerCallbacks serverCb;
    server->setCallbacks(&serverCb, false);

    // --- Custom data service ---
    NimBLEService* svc = server->createService(SERVICE_UUID);

    rx_char = svc->createCharacteristic(
        RX_CHAR_UUID,
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR
    );
    static RxCallbacks rxCb;
    rx_char->setCallbacks(&rxCb);

    tx_char = svc->createCharacteristic(
        TX_CHAR_UUID,
        NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY
    );
    static TxCallbacks txCb;
    tx_char->setCallbacks(&txCb);
    set_wifi_runtime_snapshot();

    req_char = svc->createCharacteristic(
        REQ_CHAR_UUID,
        NIMBLE_PROPERTY::NOTIFY
    );
    static ReqCallbacks reqCb;
    req_char->setCallbacks(&reqCb);

    // ── Pet animation ──
    pet_anim_char = svc->createCharacteristic(
        PET_ANIM_CHAR_UUID,
        NIMBLE_PROPERTY::WRITE
    );
    static PetAnimCallbacks petAnimCb;
    pet_anim_char->setCallbacks(&petAnimCb);

    svc->start();

    // --- HID keyboard service ---
    hid_dev = new NimBLEHIDDevice(server);
    hid_dev->setReportMap((uint8_t*)HID_REPORT_MAP, sizeof(HID_REPORT_MAP));
    hid_dev->setManufacturer("Anthropic");
    hid_dev->setPnp(0x01, 0x02E5, 0x0001, 0x0100);
    hid_dev->setHidInfo(33, 0x02);
    hid_dev->setBatteryLevel(100);
    input_kbd = hid_dev->getInputReport(1);

    server->start();
    start_advertising();

    Serial.printf("BLE: init complete, MAC=%s\n", mac_str);
}

void ble_tick(void) {
    if (need_advertise) {
        need_advertise = false;
        start_advertising();
    }
    if (state == BLE_STATE_CONNECTED && pending_refresh_request) {
        pending_refresh_request = false;
        ble_request_refresh();
    }
    if (state == BLE_STATE_CONNECTED && tx_subscribed
        && (int32_t)(millis() - control_notify_after_ms) >= 0) {
        if (pending_screen_announce) {
            pending_screen_announce = false;
            ble_send_screen(ui_get_current_screen() == SCREEN_SPLASH ? "splash" : "usage");
            return;
        }
        if (pending_wifi_configured) {
            pending_wifi_configured = false;
            ble_send_wifi_status("configured");
            return;
        }
        if (pending_wifi_runtime_announce) {
            pending_wifi_runtime_announce = false;
            pending_wifi_snapshot_restore = false;
            set_wifi_runtime_snapshot();
            tx_char->notify();
            control_notify_after_ms = millis() + 150;
            return;
        }
    }
    if (pending_wifi_snapshot_restore
        && (int32_t)(millis() - wifi_snapshot_restore_after_ms) >= 0) {
        pending_wifi_snapshot_restore = false;
        set_wifi_runtime_snapshot();
    }
}

ble_state_t ble_get_state(void) {
    return state;
}

const char* ble_get_device_name(void) {
    return DEVICE_NAME;
}

const char* ble_get_mac_address(void) {
    return mac_str;
}

void ble_clear_bonds(void) {
    NimBLEDevice::deleteAllBonds();
    Serial.println("BLE: bonds cleared");
    if (state == BLE_STATE_CONNECTED) {
        server->disconnect(server->getPeerInfo(0).getConnHandle());
    }
    need_advertise = true;
}

bool ble_has_bonds(void) {
    return NimBLEDevice::getNumBonds() > 0;
}

bool ble_has_data(void) {
    portENTER_CRITICAL(&rx_mux);
    const bool ready = data_ready;
    portEXIT_CRITICAL(&rx_mux);
    return ready;
}

const char* ble_get_data(void) {
    portENTER_CRITICAL(&rx_mux);
    if (!data_ready) {
        portEXIT_CRITICAL(&rx_mux);
        return nullptr;
    }
    memcpy(rx_read_buf, rx_buf, sizeof(rx_read_buf));
    data_ready = false;
    portEXIT_CRITICAL(&rx_mux);
    rx_read_buf[BLE_BUF_SIZE - 1] = '\0';
    return rx_read_buf;
}

void ble_send_ack(void) {
    if (state == BLE_STATE_CONNECTED && tx_char) {
        tx_char->setValue("{\"ack\":true}");
        tx_char->notify();
        schedule_wifi_snapshot_restore();
    }
}

void ble_send_nack(void) {
    if (state == BLE_STATE_CONNECTED && tx_char) {
        tx_char->setValue("{\"err\":true}");
        tx_char->notify();
        schedule_wifi_snapshot_restore();
    }
}

void ble_send_wifi_config_result(void) {
    ble_send_wifi_status("updated");
}

void ble_send_wifi_status(const char* status) {
    if (!status) return;
    if (state == BLE_STATE_CONNECTED && tx_char) {
        char buf[40];
        snprintf(buf, sizeof(buf), "{\"wifi\":\"%s\"}", status);
        tx_char->setValue(buf);
        tx_char->notify();
        schedule_wifi_snapshot_restore();
    }
}

void ble_publish_wifi_runtime_state(const char* status) {
    if (!status || !tx_char) return;
    set_wifi_runtime_snapshot();
    pending_wifi_snapshot_restore = false;
    if (state == BLE_STATE_CONNECTED && tx_subscribed) {
        pending_wifi_runtime_announce = true;
    }
}

bool ble_pause_for_wifi_request(void) {
    if (radio_paused_for_wifi || !NimBLEDevice::isInitialized()) return true;
    tx_subscribed = false;
    need_advertise = false;
    pending_refresh_request = false;
    pending_screen_announce = false;
    pending_wifi_configured = false;
    pending_wifi_runtime_announce = false;
    pending_wifi_snapshot_restore = false;
    // The server owns the HID services, while this small wrapper is allocated
    // separately. Drop it before deleting/rebuilding the complete GATT tree so
    // repeated Wi-Fi polls do not leak one wrapper per cycle.
    delete hid_dev;
    hid_dev = nullptr;
    if (!NimBLEDevice::deinit(true)) {
        Serial.println("BLE: pause for Wi-Fi request failed");
        return false;
    }
    server = nullptr;
    input_kbd = nullptr;
    tx_char = nullptr;
    rx_char = nullptr;
    req_char = nullptr;
    pet_anim_char = nullptr;
    radio_paused_for_wifi = true;
    state = BLE_STATE_DISCONNECTED;
    Serial.println("BLE: paused for Wi-Fi HTTPS request");
    return true;
}

bool ble_resume_after_wifi_request(void) {
    if (!radio_paused_for_wifi) return true;
    radio_paused_for_wifi = false;
    ble_init();
    if (!NimBLEDevice::isInitialized() || !server) {
        Serial.println("BLE: resume after Wi-Fi request failed");
        return false;
    }
    Serial.println("BLE: resumed after Wi-Fi HTTPS request");
    return true;
}

void ble_request_refresh(void) {
    if (state == BLE_STATE_CONNECTED && req_char) {
        uint8_t v = 0x01;
        req_char->setValue(&v, 1);
        req_char->notify();
        Serial.println("BLE: refresh requested");
    }
}

void ble_send_screen(const char* screen_name) {
    if (state != BLE_STATE_CONNECTED || !tx_char) return;
    char buf[32];
    snprintf(buf, sizeof(buf), "{\"sc\":\"%s\"}", screen_name);
    tx_char->setValue(buf);
    tx_char->notify();
    schedule_wifi_snapshot_restore();
    Serial.printf("BLE: screen -> %s\n", screen_name);
}

void ble_keyboard_press(uint8_t key, uint8_t modifier) {
    if (state != BLE_STATE_CONNECTED || !input_kbd) return;
    // HID report: [modifier, reserved, key1, key2, key3, key4, key5, key6]
    uint8_t report[8] = {modifier, 0, key, 0, 0, 0, 0, 0};
    input_kbd->setValue(report, sizeof(report));
    input_kbd->notify();
}

void ble_keyboard_release(void) {
    if (state != BLE_STATE_CONNECTED || !input_kbd) return;
    uint8_t report[8] = {0};
    input_kbd->setValue(report, sizeof(report));
    input_kbd->notify();
}
