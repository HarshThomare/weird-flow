//========================================================================
// FILE:
//    WeirdMachine.h
//
// DESCRIPTION:
//    The main or global functions of the library.
//
// License: MIT
//========================================================================
#ifndef WEIRD_MACHINE_H
#define WEIRD_MACHINE_H

#include "Util.h"
#include "WeirdStates/IndirectJmp.h"
#include "TransientWindows/RetBased.h"

namespace WM {
  void init();
  void cleanup();
}

#endif
