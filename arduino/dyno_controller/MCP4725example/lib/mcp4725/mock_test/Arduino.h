#pragma once
#include <stdint.h>
#include <stdio.h>
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
void delay(int ms);
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t val);
