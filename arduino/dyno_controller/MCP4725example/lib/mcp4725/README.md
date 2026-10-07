# MCP4725 Arduino Library

A robust, redundant, and highly efficient Arduino library for the MCP4725 12-bit Digital-to-Analog Converter (DAC) with EEPROM.

## Features
- **State Caching**: The class instance caches device states to minimize redundant I2C communications and improve speed.
- **Bitwise Operations**: Optimized bitwise operations are used for high-efficiency register masking and state tracking.
- **Full Configuration**: Easy setup for addressing, normal mode, power-down modes (1kΩ, 100kΩ, 500kΩ), reference voltage, and EEPROM state.
- **Bi-directional Updating**: Read the full configuration and EEPROM settings directly from the device and sync it back to the library instance, or update the device with new settings.

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