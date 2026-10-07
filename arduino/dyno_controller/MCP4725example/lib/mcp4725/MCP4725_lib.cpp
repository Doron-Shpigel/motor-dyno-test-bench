#include "MCP4725_lib.h"
#include <Wire.h> // used in the following methods: address(), probe(), 
// --- PUBLIC METHODS ---


//TODO: some methods update the property using xor operator, meaning that if the method is called twice, it will revert the property to its previous value. This is not the desired behavior, and should be fixed. The methods that use xor operator are: address(), mode(), reference_voltage(), eeprom(), output(). aaaa
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
    states.state_register &= ~MCP4725::address_set_mask; // clear the address set bit in the state register, indicating that the address has been set successfully
    if (MCP4725::mode(MCP4725::power_down_modes::power_down_1k_mode))
    { // will return 0x02 if the mode is invalid or,  the device didn't enter power down 1k mode
        return 0x02;
    };
    states.state_register &= ~MCP4725::mode_set_mask; // clear the mode set bit in the state register, indicating that the mode has been set successfully
    if (MCP4725::reference_voltage(MCP4725::IdealReferenceVoltage)){// will return 0x03 if the reference voltage is out of range (0-5000 mV)
        return 0x03;
    };
    states.state_register &= ~MCP4725::reference_voltage_set_mask; // clear the reference voltage set bit in the state register, indicating that the reference voltage has been set successfully
    if (MCP4725::eeprom(0x0000)){ // will return 0x04 if the eeprom voltage is out of range (0-4095 mV), or if the eeprom write fails
        return 0x04;
    };
    states.state_register &= ~MCP4725::eeprom_voltage_set_mask; // clear the eeprom voltage set bit in the state register, indicating that the eeprom voltage has been set successfully
    if (MCP4725::output(0x0000)){ // will return 0x05 if the output voltage is out of range (0-4095 mV)
        return 0x05;
    };
    states.state_register &= ~MCP4725::output_voltage_set_mask; // clear the output voltage set bit in the state register, indicating that the output voltage has been set successfully
    
    uint8_t err = MCP4725::update_to_device();
    if (err != 0) return err;
    delay(50); // wait for EEPROM write to finish
    
    states.state_register &= ~MCP4725::eeprom_read_corrupted_mask; // Initialized EEPROM correctly, read is trusted
    
    return 0x00;
}; 
// change instance address, also it will probe the device to check if the address is valid and the device is responding, returns 0x00 if successful, otherwise returns an error code.
uint8_t MCP4725::address(uint8_t address_a0, uint8_t address_a1, uint8_t address_a2, uint8_t device_code){// *DONE*
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
    states.state_register &= ~MCP4725::address_set_mask; // clear the address set bit in the state register, indicating that the address has been set successfully
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
    states.state_register &= ~MCP4725::reference_voltage_set_mask; // clear the reference voltage set bit in the state register, indicating that the reference voltage has been set successfully
    return 0x0000;
};
//change the eeprom and output voltage in the class instance, returns 0x00 if successful, otherwise returns an error code.
uint16_t MCP4725::eeprom(uint16_t voltage){// *DONE*
    if (voltage < 0 || voltage > 5000){
        return 0xFFFF; // invalid eeprom voltage, must be between 0 and 5000 mV
    }
    states.eeprom_voltage = voltage;
    states.state_register &= ~MCP4725::eeprom_voltage_set_mask; // clear the eeprom set bit in the state register, indicating that the eeprom has been set successfully
    return MCP4725::output(voltage);
};// set the eeprom and output voltage
// change the output voltage in the class instance, returns 0x00 if successful, otherwise returns an error code.
uint16_t MCP4725::output(uint16_t voltage){// *DONE*
    if (voltage < 0 || voltage > 5000){
        return 0xFFFF; // invalid output voltage, must be between 0 and 5000 mV
    }
    states.output_voltage = voltage;
    states.state_register &= ~MCP4725::output_voltage_set_mask; // clear the output voltage set bit in the state register, indicating that the output voltage has been set successfully
    return 0x0000;
};
//
// change the power mode in the class instance, returns 0x00 if successful, otherwise returns an error code.
uint8_t MCP4725::mode(uint8_t mode = MCP4725::power_down_modes::power_down_1k_mode){// *DONE*
    if (mode > 0x03){
        return 0xFF; // invalid mode, must be between 0 and 3, watch the header file for power_down_modes 
    }
    states.mode = mode;
    states.state_register &= ~MCP4725::mode_set_mask; // clear the mode set bit in the state register, indicating that the mode has been set successfully
    return 0x00;
}

// This method sends a power mode command to the device, although it's called "deactivate", the activate method use this method to send the normal mode command to the device.
// It will return 0x00 if successful, otherwise it will return an error code.
uint8_t MCP4725::deactivate(){
    //the device is already in power down mode, to change the power down mode, use the deactivate(uint8_t mode) method.
    //the device is already in power down mode, to change the power down mode, use the deactivate(uint8_t mode) method.
    if ((states.mode != MCP4725::power_down_modes::normal_mode) // mismatch between the current mode and the normal mode, meaning the device is in power down mode
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
    if (mode > 0x03){
        return 0x04; // invalid mode, must be between 0 and 3, watch the header file for power_down_modes 
    }
    states.mode = mode;
    states.state_register &= ~MCP4725::mode_set_mask;
    return update_to_device();
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

void MCP4725::update_data_array() {
    uint32_t output_voltage_32 = ((uint32_t)states.output_voltage * 4096) / states.reference_voltage;
    if (output_voltage_32 > 4095) {
        output_voltage_32 = 4095;
    }
    uint16_t dac_value = (uint16_t)output_voltage_32;
    data[0] = (dac_value >> 4) & 0xFF; // Upper 8 bits (D11-D4)
    data[1] = (dac_value << 4) & 0xF0; // Lower 4 bits (D3-D0)
}

uint8_t MCP4725::update_to_device() {
    if (states.state_register & MCP4725::address_set_mask) {
        return 0x01; // address has not been set
    }
    update_data_array();
    
    uint8_t command;
    // If eeprom_voltage has been set, we write DAC and EEPROM, else just DAC
    if ((states.state_register & MCP4725::eeprom_voltage_set_mask) == 0) {
        command = MCP4725::write_dac_and_eeprom_command;
        // reset the flag so we don't continuously wear out EEPROM on subsequent DAC updates
        states.state_register |= MCP4725::eeprom_voltage_set_mask;
        // Hardware bug tracking: EEPROM was written, so read buffer is valid
        states.state_register &= ~MCP4725::eeprom_read_corrupted_mask;
    } else {
        command = MCP4725::write_dac_only_command;
        // Hardware bug tracking: DAC only write corrupts the EEPROM read buffer
        states.state_register |= MCP4725::eeprom_read_corrupted_mask;
    }
    command |= (states.mode << 1);
    
    Wire.beginTransmission(states.address);
    Wire.write(command);
    Wire.write(data[0]);
    Wire.write(data[1]);
    uint8_t error = Wire.endTransmission();
    if (error != 0) {
        return 0x02; // transmission error
    }
    
    if (states.mode == MCP4725::power_down_modes::normal_mode) {
        states.state_register |= MCP4725::dac_active_mask;
    } else {
        states.state_register &= ~MCP4725::dac_active_mask;
    }
    
    return 0x00;
}

void MCP4725::read_from_device(uint8_t *current_dac_settings, uint16_t *current_dac_register, uint16_t *current_eeprom_register) {
    if (states.state_register & MCP4725::address_set_mask) {
        return; // address has not been set
    }
    Wire.requestFrom((uint8_t)states.address, (uint8_t)5);
    if (Wire.available() < 5) {
        return; // failed to read required bytes
    }
    uint8_t byte1 = Wire.read();
    uint8_t byte2 = Wire.read();
    uint8_t byte3 = Wire.read();
    uint8_t byte4 = Wire.read();
    uint8_t byte5 = Wire.read();
    
    if (current_dac_settings != nullptr) {
        *current_dac_settings = byte1;
    }
    if (current_dac_register != nullptr) {
        *current_dac_register = ((uint16_t)byte2 << 4) | (byte3 >> 4);
    }
    if (current_eeprom_register != nullptr) {
        *current_eeprom_register = ((uint16_t)byte4 << 8) | byte5;
    }
}

uint8_t MCP4725::update_from_device() {
    if (states.state_register & MCP4725::address_set_mask) {
        return 0x01; // address has not been set
    }
    uint8_t current_dac_settings = 0;
    uint16_t current_dac_register = 0;
    uint16_t current_eeprom_register = 0;
    
    read_from_device(&current_dac_settings, &current_dac_register, &current_eeprom_register);
    
    // Update mode
    states.mode = (current_dac_settings & 0b00000110) >> 1;
    states.state_register |= MCP4725::mode_set_mask;
    
    // Calculate back the voltage if reference voltage is available
    if ((states.state_register & MCP4725::reference_voltage_set_mask) == 0) {
        uint32_t output_voltage_32 = ((uint32_t)current_dac_register * states.reference_voltage) / 4096;
        states.output_voltage = (uint16_t)output_voltage_32;
        states.state_register |= MCP4725::output_voltage_set_mask; // MARK AS CLEAN! Local cache now perfectly matches hardware
        
        uint16_t eeprom_val = (current_eeprom_register & 0x0FFF);
        
        // Hardware bug filter: clone MCP4725 chips corrupt EEPROM read buffer on DAC-only writes
        if ((states.state_register & MCP4725::eeprom_read_corrupted_mask) == 0) {
            uint32_t eeprom_voltage_32 = ((uint32_t)eeprom_val * states.reference_voltage) / 4096;
            states.eeprom_voltage = (uint16_t)eeprom_voltage_32;
            states.state_register |= MCP4725::eeprom_voltage_set_mask; // MARK AS CLEAN! Local cache perfectly matches true EEPROM
        }
    }
    
    if (states.mode == MCP4725::power_down_modes::normal_mode) {
        states.state_register |= MCP4725::dac_active_mask;
    } else {
        states.state_register &= ~MCP4725::dac_active_mask;
    }
    
    return 0x00;
}



