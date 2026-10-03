//=============================================================================
// FILE:
//    WeirdRegisters.h
//
// DESCRIPTION:
//    Manage the weird registers of a WM in function scope
//
// License: MIT
//=============================================================================
#ifndef WEIRD_REGISTERS_H
#define WEIRD_REGISTERS_H

#include <vector>
#include "llvm/IR/IRBuilder.h"

class Mapping;
class Flexo;

#define PAGE 4096

using namespace llvm;

class WeirdRegisters {
public:
  WeirdRegisters(Flexo* flexo, IRBuilder<>& builder, int align);
  virtual ~WeirdRegisters();

  void cleanup();
  virtual void allocate(int count);
  virtual void assignArch(Value* archVal, int regId, bool invert = false);
  void assignConst(int val, int regId);
  Value* loadReg(int regId);
  Value* getReg(int regId);
  Value* getFakeReg(int regId);

  // separation between registers
  static int regOffset;
  // distance between a real WR and its fake location
  static int fakeOffset;
  // the first register index
  static const int firstIdx = 1;

protected:
  virtual Value* getCreateReg(int regId);
  Value* getCreateRegOffset(int regId);
  Value* getCreateFRegOffset(int regId);

  Flexo* flexo;
  IRBuilder<>& builder;
  // number of weird registers
  int count;
  // total memory size
  int size;
  // memory var in LLVM
  Value* WRegs;
  // memory alignment
  Align align;
  // WR index -> WR variable in LLVM
  std::vector<Value*> WRegIdxArr;
  // WR index -> WR offsets
  std::vector<Value*> WRegOffsets;
  // WR index -> fake WR variable in LLVM
  std::vector<Value*> FWRegIdxArr;
  // WR index -> fake WR offsets
  std::vector<Value*> FWRegOffsets;
  // mapping between WR index and memory address
  Mapping* mapping;
};

#endif
