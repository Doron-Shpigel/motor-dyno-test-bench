#include <stdio.h>
#include "../MCP4725_lib.h"
int main() {
    printf("eeprom_read_corrupted_mask: %d\n", MCP4725::eeprom_read_corrupted_mask);
    printf("eeprom_voltage_set_mask: %d\n", MCP4725::eeprom_voltage_set_mask);
    return 0;
}
