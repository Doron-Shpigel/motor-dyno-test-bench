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
    
    printf("1. Bootup\n");
    dac.default_setup();
    dac.update_from_device();
    printf("Output: %d, EEPROM: %d, Mode: %d\n", dac.value(MCP4725::Prop::output_voltage), dac.value(MCP4725::Prop::eeprom_voltage), dac.value(MCP4725::Prop::mode));
    
    printf("2. out 1000\n");
    dac.output(1000);
    dac.activate();
    dac.update_to_device();
    dac.update_from_device();
    printf("Output: %d, EEPROM: %d, Mode: %d\n", dac.value(MCP4725::Prop::output_voltage), dac.value(MCP4725::Prop::eeprom_voltage), dac.value(MCP4725::Prop::mode));
    
    printf("3. OFF\n");
    dac.deactivate(1);
    dac.update_from_device();
    printf("Output: %d, EEPROM: %d, Mode: %d\n", dac.value(MCP4725::Prop::output_voltage), dac.value(MCP4725::Prop::eeprom_voltage), dac.value(MCP4725::Prop::mode));
    
    printf("4. ON\n");
    uint16_t eeprom_val = dac.value(MCP4725::Prop::eeprom_voltage);
    dac.output(eeprom_val);
    dac.activate();
    dac.update_to_device();
    dac.update_from_device();
    printf("Output: %d, EEPROM: %d, Mode: %d\n", dac.value(MCP4725::Prop::output_voltage), dac.value(MCP4725::Prop::eeprom_voltage), dac.value(MCP4725::Prop::mode));
    
    printf("5. save 2500\n");
    dac.eeprom(2500);
    dac.activate();
    dac.update_to_device();
    dac.update_from_device();
    printf("Output: %d, EEPROM: %d, Mode: %d\n", dac.value(MCP4725::Prop::output_voltage), dac.value(MCP4725::Prop::eeprom_voltage), dac.value(MCP4725::Prop::mode));
    
    printf("6. out 4000\n");
    dac.output(4000);
    dac.activate();
    dac.update_to_device();
    dac.update_from_device();
    printf("Output: %d, EEPROM: %d, Mode: %d\n", dac.value(MCP4725::Prop::output_voltage), dac.value(MCP4725::Prop::eeprom_voltage), dac.value(MCP4725::Prop::mode));

    return 0;
}
