#include "board.h"
#include <Arduino.h>

// Called once at the very start of setup(), before any HAL device init.
// The CYD family uses plain GPIO/SPI peripherals — no PMU or IO expander.
extern "C" void board_init(void) {
    pinMode(TF_CS, OUTPUT);
    digitalWrite(TF_CS, HIGH);

    pinMode(TP_CS, OUTPUT);
    digitalWrite(TP_CS, HIGH);

    pinMode(LCD_BL, OUTPUT);
    digitalWrite(LCD_BL, HIGH);

    pinMode(BTN_BACK_GPIO, INPUT_PULLUP);
}
