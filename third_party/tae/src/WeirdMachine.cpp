//========================================================================
// FILE:
//    WeirdMachine.cpp
//
// DESCRIPTION:
//    The main or global functions of the library.
//
// License: MIT
//========================================================================
#include "WeirdMachine.h"

namespace WM {
    // init the weird machine
    void init() {
        // allocate the cache side channel for BTB weird registers
        allocate();
    }

    // cleanup the weird machine
    void cleanup() {
        // deallocate the cache side channel
        deallocate();
    }
}
