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
    uint8_t address(uint8_t address_a0, uint8_t address_a1 = 0x00, uint8_t address_a2 = 0x00); // change instance address
    uint16_t reference_voltage(uint16_t reference_voltage); // change the reference_voltage for the DAC calculation
    uint16_t eeprom(uint16_t voltage);// set the eeprom and output voltage
    uint16_t output(uint16_t voltage);  // set output voltage
    uint8_t mode(uint8_t mode); // set power mode


private:
    struct InternalState {
        uint8_t state = 0xFF;
        uint8_t address;
        uint8_t mode ;
        uint16_t reference_voltage;
        uint16_t eeprom_voltage;
        uint16_t output_voltage;
    } states;

    // --- PRIVATE LIBRARY-ONLY CONSTANTS ---
    static constexpr uint8_t A1 = 0x00;
    static constexpr uint8_t A2 = 0x01;

    
};








#endif