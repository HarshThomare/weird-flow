//========================================================================
// FILE:
//    Util.h
//
// DESCRIPTION:
//    Utility functions.
//
// License: MIT
//========================================================================
#ifndef UTIL_H
#define UTIL_H

#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace WM {

template<class T>
void shuffle(T* arr, uint32_t size) {
  for (uint32_t i = 0; i < size; i++) {
    uint32_t j = rand() % size;
    T tmp = arr[i];
    arr[i] = arr[j];
    arr[j] = tmp;
  }
}

// create a small delay, the length is controlled by `amount`
// this function should always return false
bool __always_inline delay(int input, const int amount) {
  int result = 0;

  #pragma clang loop unroll(full)
  for(int i = 0; i < amount; i++) {
      asm volatile ("add %0, %1" : "+r"(result), "+r"(input) :: );
  }

  return result == 0x7FFFFFFF;
}

// create a long delay using floating point operations, the length is
// controlled by `amount`. This function should always return false.
bool __always_inline longDelay(uint64_t input, const int amount) {

  double result;
  asm volatile ("cvtsi2sd %1, %0" : "=x"(result) : "r"(input & 0xFFFF) :);

  #pragma clang loop unroll(full)
  for (int i = 0; i < amount; i++) {
    // square root of a double
    asm volatile ("sqrtsd %0, %0" : "+x"(result) ::);
  }

  return result == 98765.4321;
}

// create delay using NOP instructions
void __always_inline nopDelay(int amount, int begin = 0) {
  for (int i = begin; i < amount; i++) {
    asm volatile("nop");
  }
  return;
}

// create memory fence
void __always_inline fence() {
  asm volatile("SERIALIZE");
  asm volatile("lfence");
  asm volatile("mfence");
  return;
}

}

#endif
