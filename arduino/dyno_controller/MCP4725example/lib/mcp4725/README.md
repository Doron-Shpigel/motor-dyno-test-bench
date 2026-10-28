# MCP4725 Arduino Library

A lightweight, robust, and state-caching Arduino library for the **Microchip MCP4725 12-bit Digital-to-Analog Converter (DAC)** with non-volatile EEPROM.

---

## Table of Contents
1. [Overview & Key Features](#overview--key-features)
2. [Quickstart Example](#quickstart-example)
3. [Function Reference (Ranked by Usage Frequency)](#function-reference-ranked-by-usage-frequency)
   - [1. `output(uint16_t voltage)`](#1-outputuint16_t-voltage)
   - [2. `update_to_device()`](#2-update_to_device)
   - [3. `default_setup()`](#3-default_setup)
   - [4. `activate()`](#4-activate)
   - [5. `deactivate(uint8_t mode)`](#5-deactivateuint8_t-mode)
   - [6. `eeprom(uint16_t voltage)`](#6-eepromuint16_t-voltage)
   - [7. `value(Prop::type)`](#7-valueproptype)
   - [8. `update_from_device()`](#8-update_from_device)
   - [9. `probe()`](#9-probe)
   - [10. `reference_voltage(uint16_t reference_voltage)`](#10-reference_voltageuint16_t-reference_voltage)
   - [11. `address(a0, a1, a2, device_code)`](#11-addressa0-a1-a2-device_code)
   - [12. `read_from_device(...)`](#12-read_from_device)
   - [13. `mode(uint8_t mode)`](#13-modeuint8_t-mode)
4. [Constants and Enums](#constants-and-enums)
5. [Compilation with `arduino-cli`](#compilation-with-arduino-cli)
6. [Architecture](#architecture)

---

## Overview & Key Features

- **State Caching & Staging Pattern**: Methods like `output()` and `mode()` stage configuration locally in the object instance. `update_to_device()` commits the staged state over I2C to reduce bus contention and maximize execution speed.
- **Physical Voltage in Millivolts**: Work directly in millivolts ($0\text{ mV}$ to $5000\text{ mV}$) rather than raw 12-bit integer register counts.
- **EEPROM Lifecycle Protection**: `update_to_device()` automatically uses the fast DAC-only register write (`0x40`) unless an EEPROM change was explicitly staged with `eeprom()`, protecting the onboard flash from wear.
- **Hardware Clone Read-Buffer Workaround**: Transparently filters known read-buffer bugs found on clone MCP4725 silicon when reading EEPROM after DAC-only writes.

---

## Quickstart Example

```cpp
#include <Wire.h>
#include <MCP4725_lib.h>

MCP4725 dac;

void setup() {
  Serial.begin(115200);
  Wire.begin(); // Wire must be initialized before using MCP4725!

  // 1. Run default setup (0x60 address, 5V reference, 1k power-down, 0V default)
  uint8_t err = dac.default_setup();
  if (err != 0) {
    Serial.print("MCP4725 setup failed! Error: 0x");
    Serial.println(err, HEX);
    while (1);
  }

  // 2. Activate the DAC to normal operating mode
  dac.activate();

  // 3. Set initial voltage to 2500 mV (2.5 V)
  dac.output(2500);
  dac.update_to_device();
}

void loop() {
  // Output a 3.3V signal (3300 mV)
  dac.output(3300);
  dac.update_to_device();
  delay(1000);

  // Output a 1.0V signal (1000 mV)
  dac.output(1000);
  dac.update_to_device();
  delay(1000);
}
```

---

## Function Reference (Ranked by Usage Frequency)

### 1. `output(uint16_t voltage)`
* **Usage**: Most common runtime method. Call this every time you want to change the analog output voltage.
* **Signature**: `uint16_t output(uint16_t voltage)`
* **Parameters**: `voltage`: Target output in millivolts ($0$ to $5000\text{ mV}$).
* **Returns**: `0x0000` on success; `0xFFFF` if `voltage > 5000`.
* **Note**: Stages the output voltage in the local instance. Follow with [`update_to_device()`](#2-update_to_device) to transmit the change over I2C.

```cpp
dac.output(1800);          // Stage 1800 mV (1.8V)
dac.update_to_device();    // Transmit to hardware
```

---

### 2. `update_to_device()`
* **Usage**: Commits staged changes (voltage, mode) to the physical MCP4725 over I2C.
* **Signature**: `uint8_t update_to_device()`
* **Parameters**: None.
* **Returns**:
  - `0x00`: Success.
  - `0x01`: Address not configured.
  - `0x02`: I2C transmission error (NACK or bus failure).
* **Behavior**: If `eeprom()` was called, writes both DAC register and EEPROM (command `0x60`). Otherwise, writes only to the DAC register (command `0x40`) to avoid EEPROM wear.

---

### 3. `default_setup()`
* **Usage**: Standard initialization method called once inside Arduino `setup()`.
* **Signature**: `uint8_t default_setup()`
* **Parameters**: None.
* **Returns**:
  - `0x00`: Success (device acknowledged at 0x60 and configured).
  - `0x01`: Address invalid or probe failed.
  - `0x02`: Mode configuration failed.
  - `0x03`: Reference voltage out of range.
  - `0x04`: EEPROM initialization failed.
  - `0x05`: Output initialization failed.
* **Behavior**: Configures default 7-bit I2C address `0x60` ($A_0=0, A_1=0, A_2=0$), reference voltage to $5000\text{ mV}$, EEPROM to $0\text{ V}$, output to $0\text{ V}$, and initial power-down mode to $1\text{ k}\Omega$. Writes to device and blocks for $50\text{ ms}$ for EEPROM write.

---

### 4. `activate()`
* **Usage**: Enables analog output by switching from power-down mode to normal operating mode.
* **Signature**: `uint8_t activate()`
* **Parameters**: None.
* **Returns**:
  - `0x00`: Success.
  - `0x01`: Address not configured or probe failed.
  - `0x30`: Device is already in normal (active) mode.
* **Behavior**: Sends normal power mode command to the hardware via `update_to_device()`.

```cpp
dac.activate(); // Now the DAC will actively drive the output pin
```

---

### 5. `deactivate(uint8_t mode)`
* **Usage**: Safely powers down DAC output when stopped or idle.
* **Signature**:
  - `uint8_t deactivate(uint8_t mode)`: Powers down with specified resistor mode ($1\text{ k}\Omega$, $100\text{ k}\Omega$, or $500\text{ k}\Omega$ pull-down to ground).
  - `uint8_t deactivate()`: Parameterless variant (requires previously configured power-down mode).
* **Parameters**: `mode`: One of `MCP4725::power_down_modes::power_down_1k_mode`, `power_down_100k_mode`, or `power_down_500k_mode`.
* **Returns**: `0x00` on success; error code on failure.

```cpp
// Disable DAC output and tie pin to GND via 1k resistor:
dac.deactivate(MCP4725::power_down_modes::power_down_1k_mode);
```

---

### 6. `eeprom(uint16_t voltage)`
* **Usage**: Saves a persistent bootup output voltage to non-volatile EEPROM.
* **Signature**: `uint16_t eeprom(uint16_t voltage)`
* **Parameters**: `voltage`: Power-on default voltage in millivolts ($0$ to $5000\text{ mV}$).
* **Returns**: `0x0000` on success; `0xFFFF` if out of range.
* **Note**: Stages the EEPROM write flag. When followed by `update_to_device()`, the chip writes to EEPROM. **Always delay at least 50 ms after `update_to_device()` when writing EEPROM.**

```cpp
dac.eeprom(2500);          // Stage 2.5V as the bootup default
dac.activate();            // Ensure normal operating mode is saved
dac.update_to_device();    // Write to EEPROM and DAC
delay(50);                 // Required physical EEPROM write delay!
```

---

### 7. `value(Prop::type)`
* **Usage**: Queries cached properties from the class instance without making an I2C transaction.
* **Signatures**:
  - `uint8_t value(Prop::type8 key) const`
    - `MCP4725::Prop::state`: Returns raw internal 8-bit state register.
    - `MCP4725::Prop::address`: Returns configured 7-bit I2C address.
    - `MCP4725::Prop::mode`: Returns current power mode ($0=\text{Normal}$, $1=1\text{k}\Omega$, $2=100\text{k}\Omega$, $3=500\text{k}\Omega$).
  - `uint16_t value(Prop::type16 key) const`
    - `MCP4725::Prop::output_voltage`: Cached output voltage in mV.
    - `MCP4725::Prop::eeprom_voltage`: Cached EEPROM voltage in mV.
    - `MCP4725::Prop::reference_voltage`: Reference voltage in mV ($5000\text{ mV}$ default).

```cpp
uint16_t current_mv = dac.value(MCP4725::Prop::output_voltage);
uint8_t current_mode = dac.value(MCP4725::Prop::mode);
```

---

### 8. `update_from_device()`
* **Usage**: Reads actual hardware state from the physical MCP4725 over I2C and synchronizes internal class instance attributes.
* **Signature**: `uint8_t update_from_device()`
* **Returns**: `0x00` on success; `0x01` if address is not set.
* **Behavior**: Requests 5 bytes from the chip, decodes the DAC register and EEPROM contents back into millivolts, and updates `states.mode`, `states.output_voltage`, and `states.eeprom_voltage`. Includes internal protection for clone chip read bugs.

---

### 9. `probe()`
* **Usage**: Pings the configured I2C address to verify hardware connectivity.
* **Signature**: `uint8_t probe()`
* **Returns**: `0x00` if the device responds with ACK; `0x20` if device does not respond (NACK).

---

### 10. `reference_voltage(uint16_t reference_voltage)`
* **Usage**: Sets the reference voltage used for scaling millivolts to 12-bit register values ($D_{11}\dots D_0 = \frac{V_{\text{out}} \times 4096}{V_{\text{ref}}}$).
* **Signature**: `uint16_t reference_voltage(uint16_t reference_voltage)`
* **Parameters**: `reference_voltage`: Reference voltage in millivolts ($0$ to $5000$). Default is $5000\text{ mV}$. Setting to `4096` enables 1:1 mapping between millivolts and 12-bit DAC codes ($0-4095$).
* **Returns**: `0x0000` on success; `0xFFFF` if out of range.

---

### 11. `address(a0, a1, a2, device_code)`
* **Usage**: Custom I2C address configuration when the address pin $A_0$ is tied to $V_{\text{CC}}$ or custom address bits are used.
* **Signature**: `uint8_t address(uint8_t address_a0, uint8_t address_a1 = A1, uint8_t address_a2 = A2, uint8_t device_code = 0x60)`
* **Parameters**:
  - `address_a0`: $0$ (GND) or $1$ ($V_{\text{CC}}$).
  - `address_a1`, `address_a2`: Factory address bits (typically $0$).
  - `device_code`: 7-bit base code (`0x60` for standard MCP4725A0).
* **Returns**: `0x00` if valid and device responds to probe; `0x10`-`0x12` for invalid pin arguments; `0x20` if probe fails.

---

### 12. `read_from_device(...)`
* **Usage**: Low-level diagnostic inspection of raw device registers.
* **Signature**: `void read_from_device(uint8_t *current_dac_settings, uint16_t *current_dac_register, uint16_t *current_eeprom_register)`
* **Parameters**: Pointers to output variables (pass `nullptr` to ignore any).

---

### 13. `mode(uint8_t mode)`
* **Usage**: Stages the power mode without immediately transmitting over I2C.
* **Signature**: `uint8_t mode(uint8_t mode)`
* **Parameters**: Mode value ($0$ to $3$).
* **Returns**: `0x00` on success; `0xFF` if invalid mode.

---

## Constants and Enums

```cpp
// Power Down Modes:
MCP4725::power_down_modes::normal_mode         = 0x00; // Active analog output
MCP4725::power_down_modes::power_down_1k_mode   = 0x01; // Output tied to GND via 1k resistor
MCP4725::power_down_modes::power_down_100k_mode = 0x02; // Output tied to GND via 100k resistor
MCP4725::power_down_modes::power_down_500k_mode = 0x03; // Output tied to GND via 500k resistor

// Property Keys (for dac.value(...)):
MCP4725::Prop::state              // 8-bit state register
MCP4725::Prop::address            // Configured 7-bit I2C address
MCP4725::Prop::mode               // Current power mode
MCP4725::Prop::reference_voltage  // Reference voltage in mV
MCP4725::Prop::eeprom_voltage     // Stored EEPROM voltage in mV
MCP4725::Prop::output_voltage     // Current output voltage in mV
```

---

## Compilation with `arduino-cli`

When building sketches with `arduino-cli`, provide the path to the library folder using `--libraries`:

```bash
# From workspace root:
arduino-cli compile --fqbn arduino:avr:uno --libraries arduino/dyno_controller/libs arduino/dyno_controller

# Flash to connected Arduino UNO:
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno arduino/dyno_controller
```

---

## Architecture

```mermaid
flowchart RL
    %% Styling
    classDef method fill:#d4edda,stroke:#28a745,stroke-width:2px,color:black;
    classDef attribute fill:#cce5ff,stroke:#007bff,stroke-width:2px,color:black;
    classDef globalFunc fill:#f8d7da,stroke:#dc3545,stroke-width:2px,color:black;

    subgraph MCP4725 ["MCP4725 Class Scope"]
        
        subgraph Attributes ["Private Attributes (State)"]
            direction TB
            a_state[("states.state_register")]:::attribute
            a_addr[("states.address")]:::attribute
            a_ref[("states.reference_voltage")]:::attribute
            a_mode[("states.mode")]:::attribute
            a_eep[("states.eeprom_voltage")]:::attribute
            a_out[("states.output_voltage")]:::attribute
            a_data[("data array")]:::attribute
        end
        subgraph Methods ["Public Methods (Actions)"]
            direction TB
            m_setup(["default_setup()"]):::method
            m_addr(["address(...)"]):::method
            m_ref(["reference_voltage(...)"]):::method
            m_mode(["mode(...)"]):::method
            m_eeprom(["eeprom(...)"]):::method
            m_out(["output(...)"]):::method
            m_act(["activate()"]):::method
            m_deact(["deactivate(...)"]):::method
            m_updev(["update_to_device()"]):::method
            m_upfrom(["update_from_device()"]):::method
            m_read(["read_from_device(...)"]):::method
        end

    end

    subgraph External ["Global Scope (Main / Libraries)"]
        direction TB
        w_begin["Wire.beginTransmission()"]:::globalFunc
        w_write["Wire.write()"]:::globalFunc
        w_end["Wire.endTransmission()"]:::globalFunc
        w_req["Wire.requestFrom()"]:::globalFunc
        w_read["Wire.read()"]:::globalFunc
    end

    %% Method to Attribute interactions
    m_setup -->|Sets| a_addr & a_ref & a_mode & a_eep & a_out
    m_addr -->|Updates| a_addr & a_state
    m_ref -->|Updates| a_ref & a_state
    m_mode -->|Updates| a_mode & a_state
    
    m_out -->|Updates| a_out & a_state
    m_eeprom -->|Updates| a_eep & a_state
    
    m_updev -->|Reads| a_addr & a_out & a_ref & a_mode
    m_updev -->|Updates| a_data & a_state
    
    m_upfrom -->|Updates| a_mode & a_out & a_eep & a_state

    %% Method to Global function interactions
    m_updev -->|Uses| w_begin & w_write & w_end
    m_deact -->|Uses| w_begin & w_write & w_end
    m_addr -->|Uses| w_begin & w_end
    m_read -->|Uses| w_req & w_read
```