#include <Arduino.h>
#include <Wire.h>
#include "src/MCP4725_lib.h"

MCP4725 dac;

void print_dac_status() {
  dac.update_from_device();
  Serial.println("\n--- DAC Status ---");
  Serial.print("Output Voltage: ");
  Serial.print(dac.value(MCP4725::Prop::output_voltage));
  Serial.println(" mV");
  
  Serial.print("EEPROM Voltage: ");
  Serial.print(dac.value(MCP4725::Prop::eeprom_voltage));
  Serial.println(" mV");
  
  Serial.print("Mode (0=Normal, >0=PowerDown): ");
  Serial.println(dac.value(MCP4725::Prop::mode));
  Serial.println("------------------\n");
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  
  Serial.println("Initializing MCP4725...");
  
  // Initialize the DAC with default setup (address A0, 5V ref, 1k power-down mode)
  // This satisfies the requirement to restart the DAC (clearing output/eeprom values in the instance)
  uint8_t err = dac.default_setup();
  if (err != 0) {
    Serial.print("Error during setup: 0x");
    Serial.println(err, HEX);
    while (1) {
      delay(100); // Halt on error
    }
  }
  
  Serial.println("DAC Reset! Instance EEPROM and Output cleared.");
  Serial.println("\nAvailable commands:");
  Serial.println("  ON             -> Turn ON output with value that is stored in EEPROM");
  Serial.println("  OFF            -> Turn OFF output (Power down 1k)");
  Serial.println("  save <number>  -> Save <number> mV to EEPROM (0-5000)");
  Serial.println("  out <number>   -> Output <number> mV to DAC (0-5000)");
  
  print_dac_status();
}

void loop() {
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    
    if (input.length() == 0) return;
    
    if (input.equalsIgnoreCase("ON")) {
      // output voltage ON with the value that is stored in EEPROM
      uint16_t eeprom_val = dac.value(MCP4725::Prop::eeprom_voltage);
      dac.output(eeprom_val);
      dac.activate();
      dac.update_to_device();
      
      Serial.println("Command: ON applied.");
      print_dac_status();
    }
    else if (input.equalsIgnoreCase("OFF")) {
      // output voltage off
      dac.deactivate(MCP4725::power_down_modes::power_down_1k_mode);
      
      Serial.println("Command: OFF applied.");
      print_dac_status();
    }
    else if (input.startsWith("save ")) {
      String valStr = input.substring(5);
      valStr.trim();
      uint16_t mv = valStr.toInt();
      if (mv > 5000) mv = 5000;
      
      dac.eeprom(mv);
      dac.activate(); // Ensure we save Normal mode to EEPROM so it boots up ON
      dac.update_to_device();
      delay(50); // MUST wait 50ms for the physical EEPROM write to finish!
      
      Serial.print("Command: Saved ");
      Serial.print(mv);
      Serial.println(" mV to EEPROM.");
      print_dac_status();
    }
    else if (input.startsWith("out ")) {
      String valStr = input.substring(4);
      valStr.trim();
      uint16_t mv = valStr.toInt();
      if (mv > 5000) mv = 5000;
      
      dac.output(mv);
      dac.activate(); // Ensure it is in normal mode
      dac.update_to_device();
      
      Serial.print("Command: Output set to ");
      Serial.print(mv);
      Serial.println(" mV.");
      print_dac_status();
    }
    else {
      Serial.println("Unknown command. Available: ON, OFF, save <number>, out <number>");
    }
  }
}
