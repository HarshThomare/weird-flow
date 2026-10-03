//==============================================================================
// FILE:
//    DualRetWM.h
//
// DESCRIPTION:
//    Defines a return address modification-based weird machine with dual rail
//    wires.
//
// License: MIT
//==============================================================================
#ifndef DUAL_RET_WEIRD_MACHINE_H
#define DUAL_RET_WEIRD_MACHINE_H

#include <string>
#include <unordered_map>
#include <unordered_set>
#include "llvm/IR/InlineAsm.h"
#include "llvm/IR/IRBuilder.h"
#include "WeirdMachines/WeirdMachine.h"

class Flexo;
class Wire;

using namespace llvm;
using namespace std;

class DualRetWM : public WeirdMachine {
public:
  DualRetWM(
    Flexo* f, unsigned mulRounds = 4, unsigned mulSize = 64,
    unsigned jmpSize = 512, unsigned maxInput = 4
  )
  : WeirdMachine(f), mulRounds(mulRounds), mulSize(mulSize), jmpSize(jmpSize),
  maxInput(maxInput) {};

  void setYosysPasses(vector<string> &yosysPasses, string &filename) override;
  Value* createCircuit(
    Function* F, IRBuilder<> &builder, StringRef circuitFile, WeirdRegisters* WR
  ) override;

private:
  void defineModuleAsm() override;
  void defineGates() override;
  void defineGate(
    string name, unsigned inputs, unsigned outputs, unsigned truthTbl
  );

  Value* getWireValue(IRBuilder<> &builder, Wire* wire) override;
  Value* getWireError(IRBuilder<> &builder, Wire* wire) override;

  unsigned mulRounds;
  unsigned mulSize;
  unsigned jmpSize;
  unsigned maxInput;
  unordered_set<string> createdGates;
};

#endif
