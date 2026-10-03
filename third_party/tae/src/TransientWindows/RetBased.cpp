//========================================================================
// FILE:
//    RetBased.cpp
//
// DESCRIPTION:
//    Trigger transient execution by modifying the return address on the
//    stack.
//
// License: MIT
//========================================================================
#include "TransientWindows/RetBased.h"

namespace WM {

// trigger transient execution by modifying the return address
// `dest` is the new return address and its access latency determines the transient
// window size
__attribute__((noinline))
void createWindow(void* dest) {
  asm volatile(
    "mov %[dest], (%%rsp)\n"
    "ret\n"
    :: [dest] "r" (dest)
    :
  );
}

}
