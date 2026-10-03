//========================================================================
// FILE:
//    RetBased.h
//
// DESCRIPTION:
//    Trigger transient execution by modifying the return address on the
//    stack.
//
// License: MIT
//========================================================================
#ifndef RET_BASED_H
#define RET_BASED_H

#include <cstdint>

namespace WM {
  void createWindow(void* dest);
}

#endif
