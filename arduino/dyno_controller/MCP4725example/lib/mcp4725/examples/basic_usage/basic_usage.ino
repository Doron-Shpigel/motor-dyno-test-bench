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
  dac.activate();
  
  // Write a starting value of 2500mV (2.5V)
  dac.output(2500);
  err = dac.update_to_device();
  if (err == 0) {
    Serial.println("DAC output successfully set to 2500 mV.");
  } else {
    Serial.println("Failed to update DAC.");
  }
}

void loop() {
  // Simple triangle wave generation
  
  // Ramp up
  for (int16_t voltage = 0; voltage <= 5000; voltage += 50) {
    dac.output(voltage);
    dac.update_to_device();
    delay(10);
  }
  
  // Ramp down
  for (int16_t voltage = 5000; voltage >= 0; voltage -= 50) {
    dac.output(voltage);
    dac.update_to_device();
    delay(10);
  }
}
