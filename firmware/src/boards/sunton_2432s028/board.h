#pragma once

// Sunton / Cheap Yellow Display 2.8\" family (ESP32-2432S028R).
// This port targets the 240x320 TFT variants and keeps the shared firmware's
// BLE + HID behavior intact on the original ESP32-D0WDQ6 hardware.

#define BOARD_NAME           "Sunton ESP32-2432S028"

// ---- Display geometry ----
// The 2432S028 panel is physically rotatable, so carry both portrait and
// landscape build targets behind one board folder.
#ifdef BOARD_LCD_LANDSCAPE
#define LCD_WIDTH            320
#define LCD_HEIGHT           240
#define LCD_ROTATION         1
#else
#define LCD_WIDTH            240
#define LCD_HEIGHT           320
#define LCD_ROTATION         0
#endif

// ---- SPI TFT display ----
#define LCD_DC               2
#define LCD_CS               15
#define LCD_SCLK             14
#define LCD_MOSI             13
#define LCD_MISO             12
#define LCD_RESET            -1
#define LCD_BL               21

// ---- Resistive touch (XPT2046 on a dedicated SPI bus) ----
// Touch is stubbed for now until hardware calibration is captured on-device.
#define TP_CS                33
#define TP_IRQ               36
#define TP_SCLK              25
#define TP_MISO              39
#define TP_MOSI              32

// ---- Shared peripherals ----
#define TF_CS                5
#define RGB_LED_R            4
#define RGB_LED_G            16
#define RGB_LED_B            17
#define CDS_GPIO             34
#define SPEAKER_GPIO         26

// ---- Buttons ----
#define BTN_BACK_GPIO        0     // BOOT — primary HID Space; also reused for hold-to-pair

// ---- Capability flags ----
#define BOARD_HAS_SECONDARY_BUTTON 0
#define BOARD_HAS_ROTATION         0
#define BOARD_HAS_IMU              0
#define BOARD_HAS_BATTERY          0
#define BOARD_HAS_IO_EXPANDER      0
