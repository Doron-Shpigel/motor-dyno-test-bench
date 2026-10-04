#ifndef "MCP4725LIB"
#define "MCP4725LIB"

#include <Arduino.h>

class MCP4725 {
	public:
		void default_setup();	// default address, default reference voltage, set eeprom to 0V, power down mode 1k
		uint8_t address(uint8_t address_a0, uint8_t address_a1 = 0x00, uint8_t address_a2 = 0x00);	//change instance address
		uint16_t reference_voltage(uint16_t reference_voltage);	// change the reference_voltage for the DAC calculation
		uint16_t eeprom(uint16_t voltage = 0);	//set the eeprom and output voltage
		uint16_t output(uint16_t voltage);	//set output voltage
		uint8_t mode(uint8_t mode = 0);	// set power mode
	private:
		_address;
		_reference_voltage;
		_mode;
		_eeprom_voltage;
		_output_voltage;
		
};