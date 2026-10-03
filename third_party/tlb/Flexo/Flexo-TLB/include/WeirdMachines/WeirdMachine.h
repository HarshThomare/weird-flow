//==============================================================================
// FILE:
//    WeirdMachine.h
//
// DESCRIPTION:
//    Defines a weird machine in an LLVM module.
//
// License: MIT
//==============================================================================
#ifndef WEIRD_MACHINE_H
#define WEIRD_MACHINE_H

#include <string>
#include <vector>
#include <unordered_map>
#include "llvm/IR/InlineAsm.h"
#include "llvm/IR/IRBuilder.h"
#include "Utils.h"

class Circuit;
class Flexo;
class WeirdRegisters;
class Wire;

using namespace llvm;
using namespace std;

enum class CircuitType { BLIF, VERILOG };

class WeirdMachine {
public:
  WeirdMachine(Flexo* f):flexo(f), circ(nullptr) {
    useFence = get_str_env("WM_USE_FENCE", "") != "false";
  };
  virtual ~WeirdMachine() = default;

  void create();
  virtual void setYosysPasses(vector<string> &yosysPasses, string &filename) = 0;
  virtual Value* createCircuit(
    Function* F, IRBuilder<> &builder, StringRef circuitFile, WeirdRegisters* WR
  );
  void defineGlobalFuncLate();

  bool verbose = false;

protected:
  void addNOP(IRBuilder<> &builder, int size);
  void addDelay(IRBuilder<> &builder);
  void loadCircuit(StringRef circuitFile, CircuitType circuitType);
  Value* getInputArchValue(IRBuilder<> &builder, Wire* wire);
  Value* getRegValue(int regId);
  void writeOutput(IRBuilder<> &builder, Value* arg, vector<Value*>& values);
  virtual Value* getWireValue(IRBuilder<> &builder, Wire* wire);
  virtual Value* getWireError(IRBuilder<> &builder, Wire* wire);
  Value* readOutputWires(IRBuilder<> &builder);

  Flexo* flexo;
  bool useFence;
  InlineAsm* fenceAsm = nullptr;

  // per-circuit data
  Function* F;
  WeirdRegisters* WR;
  Circuit* circ;
  StringMap<size_t> argMap;
  unordered_map<Wire*, Value*> inputValues;
  unordered_map<int, Value*> regValues;

private:
  void declareLibIntrinsic();
  void defineGlobalVariables();
  void defineGlobalFunc();
  void defineDelay(Function* F);
  void defineTimer(Function* F);
  void defineSyscallRand(Function* F);
  void defineMmap(Function* F);
  void defineMunmap(Function* F);
  void defineOpen(Function *F);
  void defineClose(Function *F);
  void defineExit(Function *F);
  void defineMaccess(Function *F);
  void defineWrite(Function *F);
  void defineAccess(Function *F);
  void defineInvlpg(Function *F);
  void defineOnMainStart(Function *F);
  void defineOnMainEnd(Function *F);
  void defineDeallocWeirdMemory(Function *F);
  void defineAllocWeirdMemory(Function *F);
  virtual void defineModuleAsm() = 0;
  virtual void defineGates() = 0;

};

#endif
