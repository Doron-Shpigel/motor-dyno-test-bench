#include "MCP4725_lib.h"
#include <Wire.h> // used in the following methods: address(), probe(), 
// --- PUBLIC METHODS ---


//TODO: some methods update the property using xor operator, meaning that if the method is called twice, it will revert the property to its previous value. This is not the desired behavior, and should be fixed. The methods that use xor operator are: address(), mode(), reference_voltage(), eeprom(), output().
// These methods are used to get the current value of the class attributes, they are const methods, meaning they do not modify the class instance*/

uint8_t MCP4725::value(Prop::type8 key) const
{
    switch (key)
    {
    case Prop::state:
        return states.state_register;
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


//These methods are used to set the value of the class attributes, they are not const methods, meaning they can modify the class instance

/* default_setup() method will set the default configuration for the MCP4725 instance:
1.it will set the address to the default address.
2. it will set the reference voltage to the ideal reference voltage.
3. it will set the eeprom voltage to 0V.
4. it will set the power down mode to 1k. 
It will return 0x00 if successful, otherwise it will return an error code.*/
uint8_t MCP4725::default_setup(){// *DONE*
    if (MCP4725::address(MCP4725::A0, MCP4725::A1, MCP4725::A2)){ // will return 0x01 if the address is invalid, or probing to the device fails
        return 0x01;
    };
    states.state_register^= MCP4725::address_set_mask; // clear the address set bit in the state register, indicating that the address has been set successfully
    if (MCP4725::mode(MCP4725::power_down_modes::power_down_1k_mode))
    { // will return 0x02 if the mode is invalid or,  the device didn't enter power down 1k mode
        return 0x02;
    };
    states.state_register^= MCP4725::mode_set_mask; // clear the mode set bit in the state register, indicating that the mode has been set successfully
    if (MCP4725::reference_voltage(MCP4725::IdealReferenceVoltage)){// will return 0x03 if the reference voltage is out of range (0-5000 mV)
        return 0x03;
    };
    states.state_register^= MCP4725::reference_voltage_set_mask; // clear the reference voltage set bit in the state register, indicating that the reference voltage has been set successfully
    if (MCP4725::eeprom(0x0000)){ // will return 0x04 if the eeprom voltage is out of range (0-4095 mV), or if the eeprom write fails
        return 0x04;
    };
    states.state_register^= MCP4725::eeprom_voltage_set_mask; // clear the eeprom voltage set bit in the state register, indicating that the eeprom voltage has been set successfully
    if (MCP4725::output(0x0000)){ // will return 0x05 if the output voltage is out of range (0-4095 mV)
        return 0x05;
    };
    states.state_register^= MCP4725::output_voltage_set_mask; // clear the output voltage set bit in the state register, indicating that the output voltage has been set successfully
    return 0x00;
}; 
// change instance address, also it will probe the device to check if the address is valid and the device is responding, returns 0x00 if successful, otherwise returns an error code.
uint8_t MCP4725::address(uint8_t address_a0=MCP4725::A0, uint8_t address_a1 = MCP4725::A1, uint8_t address_a2 = MCP4725::A2, uint8_t device_code = MCP4725::device_code){// *DONE*
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
    states.state_register^= MCP4725::address_set_mask; // clear the address set bit in the state register, indicating that the address has been set successfully
    return probe(); // probe the device to check if the address is valid and the device is responding
}; // change instance address
// will use the current instance address to probe the device, returns 0x00 if successful, otherwise returns an error code.
uint8_t MCP4725::probe(){//*DONE*
    Wire.beginTransmission(states.address);
    uint8_t error = Wire.endTransmission();
    if (error == 0){
        return 0x00; // device is responding
    } else {
        return 0x20; // device is not responding
    }
};
// change the reference_voltage for the DAC calculation in the class instance, returns 0x00 if successful, otherwise returns an error code.
uint16_t MCP4725::reference_voltage(uint16_t reference_voltage=MCP4725::IdealReferenceVoltage){// *DONE*
    if (reference_voltage < 0 || reference_voltage > 5000){
        return 0xFFFF; // invalid reference voltage, must be between 0 and 5000 mV
    }
    states.reference_voltage = reference_voltage;
    states.state_register^= MCP4725::reference_voltage_set_mask; // clear the reference voltage set bit in the state register, indicating that the reference voltage has been set successfully
    return 0x0000;
};
//change the eeprom and output voltage in the class instance, returns 0x00 if successful, otherwise returns an error code.
uint16_t MCP4725::eeprom(uint16_t voltage){// *DONE*
    if (voltage < 0 || voltage > 5000){
        return 0xFFFF; // invalid eeprom voltage, must be between 0 and 5000 mV
    }
    states.eeprom_voltage = voltage;
    states.state_register^= MCP4725::eeprom_voltage_set_mask; // clear the eeprom set bit in the state register, indicating that the eeprom has been set successfully
    return MCP4725::output(voltage);
};// set the eeprom and output voltage
// change the output voltage in the class instance, returns 0x00 if successful, otherwise returns an error code.
uint16_t MCP4725::output(uint16_t voltage){// *DONE*
    if (voltage < 0 || voltage > 5000){
        return 0xFFFF; // invalid output voltage, must be between 0 and 5000 mV
    }
    states.output_voltage = voltage;
    states.state_register^= MCP4725::output_voltage_set_mask; // clear the output voltage set bit in the state register, indicating that the output voltage has been set successfully
    return 0x0000;
};
//
// change the power mode in the class instance, returns 0x00 if successful, otherwise returns an error code.
uint8_t MCP4725::mode(uint8_t mode = MCP4725::power_down_modes::power_down_1k_mode){// *DONE*
    if (mode > 0x03){
        return 0xFF; // invalid mode, must be between 0 and 3, watch the header file for power_down_modes 
    }
    states.mode = mode;
    states.state_register^= MCP4725::mode_set_mask; // clear the mode set bit in the state register, indicating that the mode has been set successfully
    return 0x00;
}

// This method sends a power mode command to the device, although it's called "deactivate", the activate method use this method to send the normal mode command to the device.
// It will return 0x00 if successful, otherwise it will return an error code.
uint8_t MCP4725::deactivate(){
    //for the first power cycle:
    if (states.state_register & MCP4725::power_cycle_mask){
        return deactivate(MCP4725::power_down_modes::power_down_1k_mode);
    }
    //the device is already in power down mode, to change the power down mode, use the deactivate(uint8_t mode) method.
    else if ((states.mode != MCP4725::power_down_modes::normal_mode) // mismatch between the current mode and the normal mode, meaning the device is in power down mode
        || (states.state_register & MCP4725::dac_active_mask) == 0) // the DAC is not active, meaning the device is in power down mode
    {
            return 0x30; // device is already in power down mode, to change the power down mode, use the deactivate(uint8_t mode) method.
    }
    return deactivate(states.mode);
};


uint8_t MCP4725::deactivate(uint8_t mode ){
    //first, checking if the device address has been set in the instance, and  probed and verified to be responding, if not, it will return an error code.
    if (states.state_register& MCP4725::address_set_mask){
        return 0x01; // device has not been probed and verified to be responding
    }
    if (states.state_register& MCP4725::power_cycle_mask){//regardless of the mode, and or the device current state, if the power cycle flag is set, it will send the power down command to the device, and clear the power cycle flag. it will return the verification value. only for the first time, both the DAC and the EEPROM will be written to the off state.
        uint8_t second_byte = write_dac_and_eeprom_command | (power_down_modes::power_down_1k_mode << 1);
        uint8_t third_byte = 0x00;
        uint8_t fourth_byte = 0x00;
        Wire.beginTransmission(states.address);
        Wire.write(second_byte);
        Wire.write(third_byte);
        Wire.write(fourth_byte);
        uint8_t error = Wire.endTransmission();
        if (error != 0){
            return 0x02; // device did not respond to the power down command
        }
        delay(10); // wait for the device to enter power down mode
        uint8_t current_dac_settings = 0x00;
        uint16_t current_eeprom_register = 0x0000;
        read_from_device(&current_dac_settings, nullptr, &current_eeprom_register);
        //bit 1,2 in current_dac_settings should be the same as the power down mode
        //bit 13,14 in current_eeprom_register should be the same as the power down mode
        if (((current_dac_settings & 0b00000110) >> 1) != power_down_modes::power_down_1k_mode || ((current_eeprom_register & 0b0110000000000000) >> 13) != power_down_modes::power_down_1k_mode)
        {
            return 0x03; // device did not enter the correct power down mode
        }//verification successful, clear the power cycle flag, clear the verification flag, and return 0x00
        states.state_register&= ~MCP4725::verification_mask;
        states.state_register&= ~MCP4725::power_cycle_mask;
        states.state_register&= ~MCP4725::dac_active_mask; // set the DAC_active bit to 0 in the state register, indicating that the DAC is not active
        return 0x00;
    }
    if (mode > 0x03){
        return 0x04; // invalid mode, must be between 0 and 3, watch the header file for power_down_modes 
    }
    Wire.beginTransmission(states.address);
    uint8_t second_byte = write_dac_only_command | (mode << 1);
    Wire.write(second_byte);
    Wire.endTransmission();
    return 0x00;
};

uint8_t MCP4725::activate(){
    //first, checking if the device address has been set in the instance, and  probed and verified to be responding, if not, it will return an error code.
    if (states.state_register& MCP4725::address_set_mask){
        return 0x01; // device has not been probed and verified to be responding
    }
    //if the device is already active, it will return an error code.
    if ( ((states.state_register & MCP4725::dac_active_mask) != 0)){
        return 0x30; // device is already in normal mode (active)
    };
    return deactivate(MCP4725::power_down_modes::normal_mode); // send the normal mode command to the device, and return the verification value.
};



