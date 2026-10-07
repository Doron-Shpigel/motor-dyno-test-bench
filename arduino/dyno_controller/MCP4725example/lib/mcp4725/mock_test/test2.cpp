#include <stdio.h>
#include "Wire.h"
#include "Arduino.h"
#include "../MCP4725_lib.h"
TwoWire Wire;
void delay(int ms) {}
void pinMode(uint8_t pin, uint8_t mode) {}
void digitalWrite(uint8_t pin, uint8_t val) {}

int main() {
    MCP4725 dac;
    Wire.hw_eeprom = 0xFFF;
    Wire.hw_dac = 0xFFF;
    
    dac.default_setup();
    dac.eeprom(2500);
    dac.activate();
    dac.output(4000);
    dac.activate();
    printf("corrupted mask bit: %d\n", (dac.value(MCP4725::Prop::state) & 0b01000000) != 0);
    
    dac.update_from_device();
    printf("EEPROM: %d\n", dac.value(MCP4725::Prop::eeprom_voltage));

    return 0;
}
