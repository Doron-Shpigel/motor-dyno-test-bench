#include "MCP4725_lib.h"

uint8_t MCP4725::value(Prop::type8 key) const
{
    switch (key)
    {
    case Prop::state:
        return states.state;
    case Prop::address:
        return states.address;
    case Prop::mode:
        return states.mode;
    default:
        return 0;
    }
}

uint16_t MCP4725::value(Prop::type16 key) const
{
    switch (key)
    {
    case Prop::reference_voltage:
        return states.reference_voltage;
    case Prop::eeprom_voltage:
        return states.eeprom_voltage;
    case Prop::output_voltage:
        return states.output_voltage;
    default:
        return 0;
    }
}


uint8_t MCP4725::default_setup(){};                                                                      // default address, default reference voltage, set eeprom to 0V, power down mode 1k
uint8_t MCP4725::address(uint8_t address_a0, uint8_t address_a1 = 0x00, uint8_t address_a2 = 0x00){
    return 0x00;
}; // change instance address
uint16_t MCP4725::reference_voltage(uint16_t reference_voltage){
    return 0x0000;
};// change the reference_voltage for the DAC calculation
uint16_t MCP4725::eeprom(uint16_t voltage){
    return 0x0000;
};// set the eeprom and output voltage
uint16_t MCP4725::output(uint16_t voltage){// set output voltage
    return 0x0000;
}
uint8_t MCP4725::mode(uint8_t mode){// set power mode
    return 0x00;
}




// void MCP4725::updateOutputVoltage(uint16_t newVoltage)
// {
//     states.output_voltage = newVoltage;
// }