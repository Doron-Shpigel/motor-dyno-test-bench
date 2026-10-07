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
    dac.output(1000); dac.activate(); dac.update_to_device(); dac.update_from_device();
    dac.deactivate(1); dac.update_from_device();
    dac.output(0); dac.activate(); dac.update_to_device(); dac.update_from_device();
    dac.eeprom(2500); dac.activate(); dac.update_to_device(); dac.update_from_device();
    dac.output(4000); dac.activate(); dac.update_to_device(); 
    printf("State register: 0x%02X\n", dac.value(MCP4725::Prop::state));
    dac.update_from_device();
    printf("Output: %d, EEPROM: %d, Mode: %d\n", dac.value(MCP4725::Prop::output_voltage), dac.value(MCP4725::Prop::eeprom_voltage), dac.value(MCP4725::Prop::mode));
    return 0;
}
