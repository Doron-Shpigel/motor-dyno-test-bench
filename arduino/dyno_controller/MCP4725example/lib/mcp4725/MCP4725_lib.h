#ifndef MCP4725LIB
#define MCP4725LIB


#include <Arduino.h>

class MCP4725 {         
// Class attributes:
public:
    struct Prop {
        enum type8  { state, address, mode, COUNT8 };
        enum type16 { reference_voltage, eeprom_voltage, output_voltage, COUNT16 };
    };
    struct power_down_modes {
        static constexpr uint8_t normal_mode = 0x00;
        static constexpr uint8_t power_down_1k_mode = 0x01;
        static constexpr uint8_t power_down_100k_mode = 0x02;
        static constexpr uint8_t power_down_500k_mode = 0x03;
    };  
    uint8_t value(Prop::type8 key) const;
    uint16_t value(Prop::type16 key) const;
// ---Class methods:---
    uint8_t default_setup(); // default address, default reference voltage, set eeprom to 0V, power down mode 1k
/* --configuration methods--
    return 0x00 if successful, otherwise return an error code
*/
    uint8_t address(uint8_t address_a0, uint8_t address_a1 = A1, uint8_t address_a2 = A2, uint8_t device_code = 0x60); // change instance address
    uint16_t reference_voltage(uint16_t reference_voltage); // change the reference_voltage for the DAC calculation
    uint16_t eeprom(uint16_t voltage);// set the eeprom and output voltage
    uint16_t output(uint16_t voltage);  // set output voltage
    uint8_t mode(uint8_t mode); //* set power down mode
    /*Commands methods
    this methods are used to send commands to the device,
    return 0x00 if successful, otherwise return an error code*/
   //
    uint8_t probe();// will use the current instance address to probe the device, returns 0x00 if successful, otherwise returns an error code.
    uint8_t activate(); // change the power mode to normal mode, returns 0x00 if successful, otherwise returns an error code.
    uint8_t deactivate();// deactivates the DAC output, returns 0x00 if successful, otherwise returns an error code.
    uint8_t deactivate(uint8_t mode );//change the power mode to one of the power down modes, returns 0x00 if successful, otherwise returns an error code.
    uint8_t update_to_device(); // will check it the instance is ready to send the configuration to the device, if it is ready it will send the configuration to the device, returns 0x00 if successful, otherwise returns an error code.
    void read_from_device(uint8_t *current_dac_settings, uint16_t *current_dac_register, uint16_t *current_eeprom_register); // will read the current configuration from the device, and return to the user pointers the current DAC settings, DAC register value, and EEPROM register value.
    uint8_t update_from_device(); // will read the configuration from the device and update the class instance, returns 0x00 if successful, otherwise returns an error code.

private:
    struct InternalState {
        uint8_t state_register = 0xDF; // 0xFF with bit 5 (dac_active_mask) cleared (0)
        /*
        this is 8bit register, each bit represents a different state of the class instance, the bits are as follows:
        bit 0(0b00000001): address set: 1 if the address has not been set, 0 if the address has been set
        bit 1(0b00000010): mode set: 1 if the mode has not been set, 0 if the mode has been set
        bit 2(0b00000100): reference voltage set: 1 if the reference voltage has not been set, 0 if the reference voltage has been set
        bit 3(0b00001000): eeprom voltage set: 1 if the eeprom voltage has not been set, 0 if the eeprom voltage has been set
        bit 4(0b00010000): output voltage set: 1 if the output voltage has not been set, 0 if the output voltage has been set
        bit 5(0b00100000): DAC is active: 1 if the DAC is active, 0 if the DAC is not active
        bit 6(0b01000000): a power cycle flag, indicate the first steps to has done, and that the device is currently with power down mode, and ready to be used with the instance configuration. the flag update only once.
        bit 7(0b10000000): probe verification flag, indicate that the device has been probed and verified to be responding, the flag update only once. 1 if the device has not been probed, 0 if the device has been probed and verified to be responding.
        */
        uint8_t address;
        uint8_t mode ;
        uint16_t reference_voltage;
        uint16_t eeprom_voltage;
        uint16_t output_voltage;
    } states;
    uint8_t data[2] = {0x00, 0x00}; // this is the data that will be sent to the device, it is a 2 byte array, the first byte is the MSB and the second byte is the LSB
    // --- PRIVATE LIBRARY-ONLY CONSTANTS ---
    static constexpr uint8_t A0 = 0x00;
    static constexpr uint8_t A1 = 0x00;
    static constexpr uint8_t A2 = 0x00;
    static constexpr uint8_t device_code = 0x60; // 7-bit base address for MCP4725 0b,0110,0000
    static constexpr uint16_t IdealReferenceVoltage = 5000; // 5V reference voltage in mV
    static constexpr uint8_t address_set_mask = 0b00000001;
    static constexpr uint8_t mode_set_mask = 0b00000010;
    static constexpr uint8_t reference_voltage_set_mask = 0b00000100;
    static constexpr uint8_t eeprom_voltage_set_mask = 0b00001000;
    static constexpr uint8_t output_voltage_set_mask = 0b00010000;
    static constexpr uint8_t dac_active_mask = 0b00100000; 
    static constexpr uint8_t eeprom_read_corrupted_mask = 0b01000000; // if 1, the device read buffer for EEPROM is corrupted by a DAC write
    static constexpr uint8_t verification_mask = 0b10000000;
    static constexpr uint8_t write_dac_only_command = 0b01000000; // command to write to the DAC register only
    static constexpr uint8_t write_dac_and_eeprom_command = 0b01100000; // command to write to the DAC register and the EEPROM register

    void update_data_array(); // this method will update the data array with the current configuration of the class instance, it will be used before sending the configuration to the device.
};








#endif