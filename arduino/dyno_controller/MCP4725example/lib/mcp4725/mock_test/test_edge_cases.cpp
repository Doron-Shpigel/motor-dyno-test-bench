#include <stdio.h>
#include <assert.h>
#include "Wire.h"
#include "Arduino.h"
#include "MCP4725_lib.h"

TwoWire Wire;
void delay(int ms) {}
void pinMode(uint8_t pin, uint8_t mode) {}
void digitalWrite(uint8_t pin, uint8_t val) {}

int main() {
    printf("--- Running Edge Case & Robustness Unit Tests ---\n");

    // 1. Uninitialized instance check (no default_setup called)
    {
        MCP4725 dac_fresh;
        assert(dac_fresh.value(MCP4725::Prop::reference_voltage) == 5000);
        assert(dac_fresh.value(MCP4725::Prop::output_voltage) == 0);
        assert(dac_fresh.value(MCP4725::Prop::eeprom_voltage) == 0);
        assert(dac_fresh.value(MCP4725::Prop::mode) == MCP4725::power_down_modes::power_down_1k_mode);
        // Ensure no divide by zero even if update_to_device is called directly
        uint8_t err = dac_fresh.update_to_device();
        assert(err == 0x01); // address not set
        printf("[PASS] Default InternalState initialization verified.\n");
    }

    // 2. Divide by zero prevention with explicit reference_voltage edge cases
    {
        MCP4725 dac;
        assert(dac.reference_voltage(0) == 0xFFFF); // rejected
        assert(dac.reference_voltage(5001) == 0xFFFF); // rejected
        assert(dac.reference_voltage(3300) == 0x0000); // valid
        assert(dac.value(MCP4725::Prop::reference_voltage) == 3300);
        printf("[PASS] Reference voltage bounds and div-zero protection verified.\n");
    }

    // 3. Deactivation and activation state symmetry
    {
        MCP4725 dac;
        Wire.hw_eeprom = 0;
        Wire.hw_dac = 0;
        dac.default_setup();

        // Already deactivated on boot (power_down_1k_mode)
        assert(dac.deactivate() == 0x30); // already inactive
        assert(dac.deactivate(1) == 0x00); // can change mode directly

        // Activate
        assert(dac.activate() == 0x00);
        assert(dac.value(MCP4725::Prop::mode) == MCP4725::power_down_modes::normal_mode);
        assert(dac.activate() == 0x30); // already active

        // Deactivate parameterless remembers 1k
        assert(dac.deactivate() == 0x00);
        assert(dac.value(MCP4725::Prop::mode) == MCP4725::power_down_modes::power_down_1k_mode);

        // Change power down mode to 100k and activate/deactivate cycle
        assert(dac.deactivate(MCP4725::power_down_modes::power_down_100k_mode) == 0x00);
        assert(dac.value(MCP4725::Prop::mode) == MCP4725::power_down_modes::power_down_100k_mode);

        assert(dac.activate() == 0x00);
        assert(dac.value(MCP4725::Prop::mode) == MCP4725::power_down_modes::normal_mode);

        // Parameterless deactivate should restore 100k mode!
        assert(dac.deactivate() == 0x00);
        assert(dac.value(MCP4725::Prop::mode) == MCP4725::power_down_modes::power_down_100k_mode);
        printf("[PASS] Mode persistence and activation/deactivation symmetry verified.\n");
    }

    // 4. Output and EEPROM voltage bounds check
    {
        MCP4725 dac;
        assert(dac.output(5001) == 0xFFFF);
        assert(dac.output(5000) == 0x0000);
        assert(dac.eeprom(5001) == 0xFFFF);
        assert(dac.eeprom(5000) == 0x0000);
        printf("[PASS] Voltage boundary checks verified.\n");
    }

    // 5. Read error handling
    {
        MCP4725 dac;
        dac.default_setup();
        dac.output(2000);
        dac.activate();
        dac.update_to_device();
        dac.update_from_device();
        assert(dac.value(MCP4725::Prop::output_voltage) == 1999);

        // Simulate I2C read failure (buffer returns 0 bytes)
        Wire.fail_read = true;
        uint8_t err = dac.update_from_device();
        assert(err == 0x02); // read failure
        // Output voltage should NOT be clobbered to 0!
        assert(dac.value(MCP4725::Prop::output_voltage) == 1999);
        Wire.fail_read = false;
        printf("[PASS] I2C read failure error propagation verified.\n");
    }

    printf("\n>>> ALL EDGE CASE & ROBUSTNESS TESTS PASSED! <<<\n");
    return 0;
}
