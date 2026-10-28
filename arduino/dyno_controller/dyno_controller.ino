#include <Wire.h>
#include <EEPROM.h>
#include <MCP4725_lib.h>

MCP4725 dac;

// --- Hardware Pins & Addresses ---
#define MCP4725_ADDR      0x60   // I2C address of the DAC module
#define TORQUE_PIN        A0     // Analog pin reading the FYTH Torque
#define SPEED_PIN         A1     // Analog pin reading the FYTH Speed
#define SERIAL_BAUD       115200 // Fast communication speed with PC

#define RELAY_BRAKE_PIN   2      // D2: Relay for the Brake
#define RELAY_SENSOR_PIN  3      // D3: Relay for the Torque Sensor
#define RELAY_AUX_PIN     4      // D4: Auxiliary Relay

// --- EEPROM (Memory) Setup ---
// We store the PID gains at memory address 0 so they survive being unplugged
const int EEPROM_ADDR = 0;
struct PIDSettings {
  float Kp; // Proportional: Reacts to current error
  float Ki; // Integral: Reacts to accumulated past error
  float Kd; // Derivative: Reacts to the rate of error change
} pid;

// --- System State Variables ---
bool isRunning = false;     // Is the test currently active?
bool pidEnabled = false;    // Is PID control enabled, or manual DAC?
float targetTorque = 0.0;   // What the PC requested
float currentTorque = 0.0;  // What the sensor actually reads
float currentSpeed = 0.0;   // What the speed sensor reads

// --- PID Math Variables ---
float errorIntegral = 0.0;  // Holds the accumulated error over time
float prevError = 0.0;      // Holds the error from the previous loop for Derivative math
int dacValue = 0;           // The final 0-4095 signal sent to the brake

// --- Timing Variables ---
unsigned long lastPidTime = 0;
const unsigned long PID_INTERVAL = 20; // 20ms = 50 Hz control loop

unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 50; // 50ms = 20 Hz PC updates

String serialBuffer = "";

// =========================================================================
// MCP4725 DAC FUNCTION
// Uses custom MCP4725 library to send 12-bit voltage signals to the brake
// =========================================================================
void mcp4725_write(uint16_t value) {
  // Ensure we don't send a number higher than the 12-bit max (4095)
  value = constrain(value, 0, 4095); 
  dac.output(value);
  dac.update_to_device();
}

// =========================================================================
// INITIALIZATION (Runs once at startup)
// =========================================================================
void setup() {
  Serial.begin(SERIAL_BAUD);
  Wire.begin();

  pinMode(RELAY_BRAKE_PIN, OUTPUT);
  pinMode(RELAY_SENSOR_PIN, OUTPUT);
  pinMode(RELAY_AUX_PIN, OUTPUT);
  digitalWrite(RELAY_BRAKE_PIN, LOW);
  digitalWrite(RELAY_SENSOR_PIN, LOW);
  digitalWrite(RELAY_AUX_PIN, LOW);

  // Initialize MCP4725 DAC using custom library
  uint8_t dac_err = dac.default_setup();
  if (dac_err == 0) {
    dac.reference_voltage(4096); // 1:1 mapping between 12-bit DAC codes (0-4095) and output
    dac.activate();              // Switch from power-down 1k mode to normal operating mode
  } else {
    Serial.print(F("DAC_INIT_ERR:0x"));
    Serial.println(dac_err, HEX);
  }

  mcp4725_write(0); // Safety first: ensure brake is OFF on boot

  // Read the saved PID values from the chip's internal memory
  EEPROM.get(EEPROM_ADDR, pid);
  
  // If memory is blank (first time ever booting), set safe defaults
  if (isnan(pid.Kp) || pid.Kp < 0 || pid.Kp > 1000) {
    pid.Kp = 100.0; 
    pid.Ki = 10.0; 
    pid.Kd = 1.0;   
    EEPROM.put(EEPROM_ADDR, pid);
  }
  Serial.println(F("DYNO_READY"));
}

// =========================================================================
// MAIN LOOP (Runs continuously)
// =========================================================================
void loop() {
  handleSerialCommands(); // 1. Check if PC sent us a message

  unsigned long now = millis();

  // ---------------------------------------------------------
  // 2. HARDWARE PID CONTROL LOOP (Executes exactly every 20ms)
  // ---------------------------------------------------------
  if (now - lastPidTime >= PID_INTERVAL) {
    float dt = (now - lastPidTime) / 1000.0; // Calculate time delta in seconds
    lastPidTime = now;

    // Read the physical analog pins
    currentTorque = (float)analogRead(TORQUE_PIN); 
    currentSpeed = (float)analogRead(SPEED_PIN);   

    // Only calculate PID and apply brake if the test is running
    if (isRunning && pidEnabled) {
      // Step A: Calculate how far off we are from the target
      float error = targetTorque - currentTorque;
      
      // Step B: Proportional Math (Push harder if error is big)
      float pTerm = pid.Kp * error;
      
      // Step C: Integral Math (Nudge gently if we are stuck slightly off target)
      errorIntegral += error * dt;
      // Prevent "Integral Windup" (getting stuck counting infinitely)
      if (errorIntegral > 4000) errorIntegral = 4000;
      if (errorIntegral < -4000) errorIntegral = -4000;
      float iTerm = pid.Ki * errorIntegral;
      
      // Step D: Derivative Math (Pull back if we are approaching the target too fast)
      float derivative = (error - prevError) / dt;
      float dTerm = pid.Kd * derivative;
      prevError = error;

      // Step E: Combine P, I, and D to get the new DAC command
      dacValue = (int)(pTerm + iTerm + dTerm);
      
      // Step F: Keep within physical limits (0 to 4095)
      if (dacValue > 4095) dacValue = 4095;
      if (dacValue < 0) dacValue = 0;

      // Send the physical voltage command to the brake!
      mcp4725_write(dacValue);
    } else if (isRunning && !pidEnabled) {
      // In manual mode (open-loop), we just send the dacValue we received from PC
      mcp4725_write(dacValue);
    } else {
      // If test is stopped, ensure brake is completely off
      dacValue = 0;
      mcp4725_write(0);
    }
  }

  // ---------------------------------------------------------
  // 3. PC TELEMETRY LOOP (Executes exactly every 50ms)
  // ---------------------------------------------------------
  if (now - lastTelemetryTime >= TELEMETRY_INTERVAL) {
    lastTelemetryTime = now;
    // Send formatted string to PC: <DATA:Torque,Speed,DAC_Value>
    Serial.print("<DATA:");
    Serial.print(currentTorque, 2); Serial.print(",");
    Serial.print(currentSpeed, 2); Serial.print(",");
    Serial.print(dacValue);
    Serial.println(">");
  }
}

// =========================================================================
// SERIAL PARSER
// Reads letters from the PC one by one until it hits a "Newline" (\n)
// =========================================================================
void handleSerialCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      processCommand(serialBuffer); // We got a full message, process it
      serialBuffer = "";            // Clear buffer for the next message
    } else if (c != '\r') {
      serialBuffer += c;            // Add letter to our buffer
    }
  }
}

// Looks at the full message from PC and decides what to do
void processCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  // Lifecycle commands (Starts and Stops the PID loop)
  if (cmd == "START") {
    isRunning = true;
    Serial.println("ACK:START");
  }
  else if (cmd == "STOP" || cmd == "RESET") {
    isRunning = false;
    targetTorque = 0.0;
    errorIntegral = 0.0;
    mcp4725_write(0);
    Serial.print("ACK:"); Serial.println(cmd);
  }
  else if (cmd == "PING") {
    Serial.println("PONG");
  }
  // UI Commands: Send current memory values to the GUI
  else if (cmd.startsWith("<GET_PID>")) {
    Serial.print("<PID_VALS:");
    Serial.print(pid.Kp, 4); Serial.print(",");
    Serial.print(pid.Ki, 4); Serial.print(",");
    Serial.print(pid.Kd, 4); Serial.println(">");
  }
  // UI Commands: Save new tuning values to memory
  else if (cmd.startsWith("<SET_PID:")) {
    int startIdx = cmd.indexOf(':') + 1;
    int comma1 = cmd.indexOf(',', startIdx);
    int comma2 = cmd.indexOf(',', comma1 + 1);
    int endIdx = cmd.indexOf('>', comma2);

    pid.Kp = cmd.substring(startIdx, comma1).toFloat();
    pid.Ki = cmd.substring(comma1 + 1, comma2).toFloat();
    pid.Kd = cmd.substring(comma2 + 1, endIdx).toFloat();

    EEPROM.put(EEPROM_ADDR, pid); 
    errorIntegral = 0; // Reset math history to prevent sudden jumps
    Serial.println("ACK:SET_PID");
  }
  // PC Control Loop: Tell PID what the new goal is
  else if (cmd.startsWith("<SET_TORQUE:")) {
    int startIdx = cmd.indexOf(':') + 1;
    int endIdx = cmd.indexOf('>', startIdx);
    targetTorque = cmd.substring(startIdx, endIdx).toFloat();
    pidEnabled = true;
    Serial.print("ACK:SET_TORQUE:");
    Serial.println(targetTorque);
  }
  // PC Control Loop: Tell DAC to output a specific value (open-loop)
  else if (cmd.startsWith("<SET_DAC:")) {
    int startIdx = cmd.indexOf(':') + 1;
    int endIdx = cmd.indexOf('>', startIdx);
    dacValue = cmd.substring(startIdx, endIdx).toInt();
    pidEnabled = false;
    Serial.print("ACK:SET_DAC:");
    Serial.println(dacValue);
  }
  // Hardware Relay Control
  else if (cmd.startsWith("<RELAY:")) {
    int comma = cmd.indexOf(',');
    int endIdx = cmd.indexOf('>');
    String relayName = cmd.substring(7, comma);
    int state = cmd.substring(comma + 1, endIdx).toInt();
    
    if (relayName == "BRAKE") {
      digitalWrite(RELAY_BRAKE_PIN, state ? HIGH : LOW);
    } else if (relayName == "SENSOR") {
      digitalWrite(RELAY_SENSOR_PIN, state ? HIGH : LOW);
    } else if (relayName == "AUX") {
      digitalWrite(RELAY_AUX_PIN, state ? HIGH : LOW);
    }
    Serial.print("ACK:RELAY:");
    Serial.print(relayName);
    Serial.print(",");
    Serial.println(state);
  }
}