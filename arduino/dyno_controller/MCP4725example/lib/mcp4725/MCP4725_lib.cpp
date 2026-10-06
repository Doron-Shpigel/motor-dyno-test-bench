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


uint8_t MCP4725::default_setup(){
    if (MCP4725::address(MCP4725::A0, MCP4725::A1, MCP4725::A2)){ // will return 0x01 if the address is invalid, or probing to the device fails
        return 0x01;
    };
    states.state ^= MCP4725::address_set_mask; // clear the address set bit in the state register, indicating that the address has been set successfully
    if (MCP4725::mode(0x01)){ // will return 0x02 if the mode is invalid or,  the device didn't enter power down 1k mode
        return 0x02;
    }; 
    states.state ^= MCP4725::mode_set_mask; // clear the mode set bit in the state register, indicating that the mode has been set successfully
    if (MCP4725::reference_voltage(MCP4725::IdealReferenceVoltage)){// will return 0x03 if the reference voltage is out of range (0-5000 mV)
        return 0x03;
    };
    states.state ^= MCP4725::reference_voltage_set_mask; // clear the reference voltage set bit in the state register, indicating that the reference voltage has been set successfully
    if (MCP4725::eeprom(0x0000)){ // will return 0x04 if the eeprom voltage is out of range (0-4095 mV), or if the eeprom write fails
        return 0x04;
    };
    states.state ^= MCP4725::eeprom_voltage_set_mask; // clear the eeprom voltage set bit in the state register, indicating that the eeprom voltage has been set successfully
    if (MCP4725::output(0x0000)){ // will return 0x05 if the output voltage is out of range (0-4095 mV)
        return 0x05;
    };
    states.state ^= MCP4725::output_voltage_set_mask; // clear the output voltage set bit in the state register, indicating that the output voltage has been set successfully
    return 0x00;
}; 
// default address, default reference voltage, set eeprom to 0V, power down mode 1k
//
//
uint8_t MCP4725::address(uint8_t address_a0=MCP4725::A0, uint8_t address_a1 = MCP4725::A1, uint8_t address_a2 = MCP4725::A2, uint8_t device_code = MCP4725::device_code){
    /*according to the MCP4725 datasheet, the address is determined by the A0, A1, and A2 pins. 
    * The address is a 3-bit value, with each bit corresponding to the state of the respective pin.
    * the 0bit corresponds to A0, the 1bit corresponds to A1, and the 2bit corresponds to A2.
    */
    if (address_a0 > 1){
        return 0x10; // invalid address bit A0
    }
    if (address_a1 > 1){
        return 0x11; // invalid address bit A1
    }
    if (address_a2 > 1){
        return 0x12; // invalid address bit A2
    }
    states.address  = device_code | (address_a2 << 2) | (address_a1 << 1) | address_a0; // combine the device code and the address bits to form the full 7-bit address
    states.state ^= MCP4725::address_set_mask; // clear the address set bit in the state register, indicating that the address has been set successfully
    return probe(); // probe the device to check if the address is valid and the device is responding
}; // change instance address
//
//
uint16_t MCP4725::reference_voltage(uint16_t reference_voltage=MCP4725::IdealReferenceVoltage){// change the reference_voltage for the DAC calculation
    if (reference_voltage < 0 || reference_voltage > 5000){
        return 0xFFFF; // invalid reference voltage, must be between 0 and 5000 mV
    }
    states.reference_voltage = reference_voltage;
    states.state ^= MCP4725::reference_voltage_set_mask; // clear the reference voltage set bit in the state register, indicating that the reference voltage has been set successfully
    return 0x0000;
};// change the reference_voltage for the DAC calculation
//
//
uint16_t MCP4725::eeprom(uint16_t voltage){
    return 0x0000;
};// set the eeprom and output voltage
//
//
uint16_t MCP4725::output(uint16_t voltage){// set output voltage
    return 0x0000;
};
//
//
uint8_t MCP4725::mode(uint8_t mode){// set power mode
    return 0x00;
}




// void MCP4725::updateOutputVoltage(uint16_t newVoltage)
// {
//     states.output_voltage = newVoltage;
// }