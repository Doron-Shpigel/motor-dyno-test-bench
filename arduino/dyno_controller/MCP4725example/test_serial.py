import serial
import time
import sys

try:
    ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
except Exception as e:
    print(f"Failed to open port: {e}")
    sys.exit(1)

time.sleep(2)  # Wait for Arduino to reset

def send_command(cmd):
    print(f"\n--- Sending: {cmd} ---")
    ser.write((cmd + '\n').encode())
    time.sleep(0.5)
    while ser.in_waiting:
        line = ser.readline().decode(errors='ignore').strip()
        if line:
            print(line)

print("Reading initial output:")
while ser.in_waiting:
    line = ser.readline().decode(errors='ignore').strip()
    if line:
        print(line)

send_command("out 1000")
send_command("OFF")
send_command("ON")
send_command("save 2500")
send_command("out 4000")
send_command("OFF")
send_command("ON")

ser.close()
