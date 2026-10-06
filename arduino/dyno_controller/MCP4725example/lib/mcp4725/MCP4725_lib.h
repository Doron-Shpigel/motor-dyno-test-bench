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
    uint8_t value(Prop::type8 key) const;
    uint16_t value(Prop::type16 key) const;
// Class methods:
    uint8_t default_setup(); // default address, default reference voltage, set eeprom to 0V, power down mode 1k
// configuration methods, return 0x00 if successful, otherwise return an error code
    uint8_t address(uint8_t address_a0, uint8_t address_a1 = A1, uint8_t address_a2 = A2, uint8_t device_code = device_code); // change instance address
    uint16_t reference_voltage(uint16_t reference_voltage); // change the reference_voltage for the DAC calculation
    uint16_t eeprom(uint16_t voltage);// set the eeprom and output voltage
    uint16_t output(uint16_t voltage);  // set output voltage
    uint8_t mode(uint8_t mode); // set power mode
// toggle methods and direct power control methods, return 0x00 if successful, otherwise return an error code
    uint8_t activate(); // reads the instance configuration, and check the state register, if both valid, activates the DAC output. returns 0x00 if successful, otherwise returns an error code.
    uint8_t deactivate(); // deactivates the DAC output, returns 0x00 if successful, otherwise returns an error code.
    uint8_t power_down(uint8_t mode); // sets the power down mode, returns 0x00 if successful, otherwise returns an error code.
// read and check methods, return 0x00 if successful, otherwise return an error code
    uint8_t probe();// will use the current instance address to probe the device, returns 0x00 if successful, otherwise returns an error code.


private:
    struct InternalState {
        uint8_t state = 0xFF;
        /*
        this is 8bit register, each bit represents a different state of the class instance, the bits are as follows:
        bit 0(0b00000001): address set: 1 if the address has not been set, 0 if the address has been set
        bit 1(0b00000010): mode set: 1 if the mode has not been set, 0 if the mode has been set
        bit 2(0b00000100): reference voltage set: 1 if the reference voltage has not been set, 0 if the reference voltage has been set
        bit 3(0b00001000): eeprom voltage set: 1 if the eeprom voltage has not been set, 0 if the eeprom voltage has been set
        bit 4(0b00010000): output voltage set: 1 if the output voltage has not been set, 0 if the output voltage has been set
        bit 5(0b00100000): DAC is active: 1 if the DAC is not active, 0 if the DAC is active
        */
        uint8_t address;
        uint8_t mode ;
        uint16_t reference_voltage;
        uint16_t eeprom_voltage;
        uint16_t output_voltage;
    } states;

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
    static constexpr uint8_t power_down_1k_mode = 0x01;
};








#endif