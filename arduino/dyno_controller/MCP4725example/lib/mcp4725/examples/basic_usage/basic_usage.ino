#include <Wire.h>
#include "src/MCP4725_lib.h"

MCP4725 dac;

void setup() {
  Serial.begin(115200);
  Wire.begin();
  
  Serial.println("Initializing MCP4725...");
  
  // Initialize the DAC with default setup (address A0, 5V ref, 1k power-down mode)
  uint8_t err = dac.default_setup();
  if (err != 0) {
    Serial.print("Error during setup: ");
    Serial.println(err);
    while (1) {
      delay(100); // Halt on error
    }
  }
  
  // Activate the DAC to normal mode
  uint8_t act_err = dac.activate();
  if (act_err != 0) {
    Serial.print("Error during activate: 0x");
    Serial.println(act_err, HEX);
  }
  
  // Write a starting value of 2500mV (2.5V)
  dac.output(2500);
  err = dac.update_to_device();
  if (err == 0) {
    Serial.println("DAC output successfully set to 2500 mV.");
  } else {
    Serial.print("Failed to update DAC, error: 0x");
    Serial.println(err, HEX);
  }
}

void loop() {
  // Ramp up
  for (int16_t voltage = 0; voltage <= 5000; voltage += 500) {
    dac.output(voltage);
    dac.update_to_device();
    delay(500); // 0.5 sec delay
    
    // Read from device to verify
    dac.update_from_device();
    Serial.print("Ramp UP - Set: ");
    Serial.print(voltage);
    Serial.print(" mV | Read: ");
    Serial.print(dac.value(MCP4725::Prop::output_voltage));
    Serial.print(" mV | Mode: ");
    Serial.println(dac.value(MCP4725::Prop::mode));
  }
  
  // Ramp down
  for (int16_t voltage = 5000; voltage >= 0; voltage -= 500) {
    dac.output(voltage);
    dac.update_to_device();
    delay(500); // 0.5 sec delay
    
    // Read from device to verify
    dac.update_from_device();
    Serial.print("Ramp DOWN - Set: ");
    Serial.print(voltage);
    Serial.print(" mV | Read: ");
    Serial.print(dac.value(MCP4725::Prop::output_voltage));
    Serial.print(" mV | Mode: ");
    Serial.println(dac.value(MCP4725::Prop::mode));
  }
}
