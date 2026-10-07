#pragma once
#include <stdint.h>
#include <stdio.h>

class TwoWire {
public:
    uint8_t buffer[32];
    int buf_idx = 0;
    int buf_len = 0;
    uint8_t address = 0;
    
    // Mock registers
    uint16_t hw_dac = 0;
    uint16_t hw_eeprom = 0;
    uint8_t hw_mode = 0;
    uint8_t hw_eeprom_mode = 0;
    
    void begin() {}
    void beginTransmission(uint8_t addr) { address = addr; buf_idx = 0; }
    void write(uint8_t data) { buffer[buf_idx++] = data; }
    uint8_t endTransmission() {
        // Process write command
        uint8_t cmd = buffer[0];
        if ((cmd & 0xE0) == 0x40) { // Write DAC
            hw_mode = (cmd & 0x06) >> 1;
            hw_dac = (buffer[1] << 4) | (buffer[2] >> 4);
        } else if ((cmd & 0xE0) == 0x60) { // Write DAC and EEPROM
            hw_mode = (cmd & 0x06) >> 1;
            hw_dac = (buffer[1] << 4) | (buffer[2] >> 4);
            hw_eeprom_mode = hw_mode;
            hw_eeprom = hw_dac;
        }
        return 0; 
    }
    uint8_t requestFrom(uint8_t addr, uint8_t len) {
        buf_len = len; buf_idx = 0;
        // Mock read response
        uint8_t rdy = 1;
        buffer[0] = (rdy << 7) | (hw_mode << 1);
        buffer[1] = (hw_dac >> 4) & 0xFF;
        buffer[2] = (hw_dac << 4) & 0xF0;
        
        // Clone bug simulation!
        uint16_t read_eeprom = hw_eeprom;
        if (hw_mode == 0) read_eeprom = (~hw_dac) & 0xFFF;
        else if (hw_mode == 1) read_eeprom = hw_dac;
        
        buffer[3] = (hw_eeprom_mode << 5) | (read_eeprom >> 8);
        buffer[4] = read_eeprom & 0xFF;
        return len;
    }
    int available() { return buf_len - buf_idx; }
    uint8_t read() { return buffer[buf_idx++]; }
};
extern TwoWire Wire;
