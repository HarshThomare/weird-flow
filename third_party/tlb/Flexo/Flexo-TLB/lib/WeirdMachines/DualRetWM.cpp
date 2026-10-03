//========================================================================
// FILE:
//    DualRetWM.cpp
//
// DESCRIPTION:
//    A weird machine implementation using return address modification
//    to trigger transient execution.
//
// License: MIT
//========================================================================

#include <string>
#include <vector>
#include <cstdlib>
#include "llvm/Support/raw_ostream.h"
#include "llvm/ADT/StringMap.h"
#include "Circuits/Circuit.h"
#include "Circuits/TruthTbl.h"
#include "Flexo.h"
#include "Utils.h"
#include "WeirdMachines/DualRetWM.h"
#include "WeirdRegisters/WeirdRegisters.h"
#include <cmath>

using namespace llvm;
using namespace std;

//-----------------------------------------------------------------------------
// Ret-based weird machine definition (dual-rail wires)
//-----------------------------------------------------------------------------

// rewrite circuit with 4-input LUTs
void DualRetWM::setYosysPasses(vector<string> &yosysPasses, string &filename) {
  yosysPasses.push_back("read_verilog " + filename + ".v");
  yosysPasses.push_back("opt");
  yosysPasses.push_back("synth -lut " + to_string(maxInput));
  yosysPasses.push_back("opt_clean -purge");
  yosysPasses.push_back("stat");
  yosysPasses.push_back("write_blif " + filename + ".blif");
}

// define mod_ret_addr in module asm
void DualRetWM::defineModuleAsm() {
  string globalAsm = (
    ".align 16\n"
    "mod_ret_addr:\n"
  );

  // ==================================================

  uint64_t pow_limit = mulSize-1;
  uint32_t limit = 1 << pow_limit;
  uint64_t backstep = limit - 1;
  std::string rdx_prefix = (mulSize == 16 ? "" : (mulSize == 64 ? "r" : "e"));
  std::string rdx_str = rdx_prefix + "dx";

	uint64_t target_power = log2(jmpSize);
	uint64_t remaining = jmpSize - (1 << target_power);

	uint64_t start_power = mod((int64_t) target_power - (mulRounds % pow_limit), pow_limit);
  uint64_t rdx = 1 << start_power;
  globalAsm += "    mov $" + to_string(rdx) + ", %rdx\n";
  // globalAsm += "    mov $" + to_string(backstep) + ", %" + rcx_str + "\n";

	for (uint64_t i = 0; i < mulRounds; i++) {
		globalAsm += "    imul  $2, %" + rdx_str + ", %" + rdx_str + "\n";
		rdx *= 2;
		if (rdx >= limit) {
      globalAsm += "    sub  $" + to_string(backstep) + ", %" + rdx_str + "\n";
      rdx -= backstep;
    }
  }

	if (remaining != 0) {
		globalAsm += "    add  $" + to_string(remaining) + ", %" + rdx_str + "\n";
  }

  // ==================================================

  globalAsm += (
    "    addq %rdx, (%rsp)\n"
    "    ret\n"
  );
  flexo->setModuleAsm(globalAsm);
}

void DualRetWM::defineGates() {}

// define a single logic gates
void DualRetWM::defineGate(
  string name, unsigned inputs, unsigned outputs, unsigned truthTbl
) {
  LLVMContext &CTX = flexo->getContext();
  Type *VoidTy = Type::getVoidTy(CTX);
  PointerType *OpaquePtrTy = PointerType::getUnqual(CTX);

  vector<Type*> argsTy;
  argsTy.resize(2 * (inputs + outputs), OpaquePtrTy);
  FunctionType *FTy = FunctionType::get(VoidTy, argsTy, false);
  FunctionCallee gateF = flexo->addFunc(name, FTy);
  Function* F = dyn_cast<Function>(gateF.getCallee());

  // define args
  for (unsigned i = 0; i < 2 * (inputs + outputs); ++i) {
    F->addParamAttr(i, Attribute::NoUndef);
    string name = (i < 2 * inputs) ? "in" : "out";
    name += to_string(i >> 1) + "_" + to_string(i & 1);
    F->getArg(i)->setName(name);
  }

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);

  string params = "";
  for (unsigned i = 0; i < 2 * (inputs + outputs); ++i) params += "r,";
  string constraints = params + "~{rax},~{rcx},~{rdx},~{r10}";
  constraints += ",~{dirflag},~{fpsr},~{flags}";
  InlineAsm *gateAsm = InlineAsm::get(
    FTy, gen_gate_asm(inputs, outputs, truthTbl), constraints, true
  );
  vector<Value*> argsVec;
  for (unsigned i = 0; i < 2 * (inputs + outputs); ++i) {
    argsVec.push_back(F->getArg(i));
  }
  auto gateAsmCall = EntryBuilder.CreateCall(gateAsm, argsVec);
  gateAsmCall->setTailCall();

  addNOP(EntryBuilder, get_int_env("RET_WM_JMP_SIZE", 512));
  EntryBuilder.CreateRetVoid();
}

Value* DualRetWM::createCircuit(
  Function* F, IRBuilder<> &builder, StringRef circuitFile, WeirdRegisters* WR
) {
  WeirdMachine::createCircuit(F, builder, circuitFile, WR);
  loadCircuit(circuitFile, CircuitType::BLIF);
  WR->allocate(2 * circ->getWireCount());

  // create gates
  for (Gate* gate : *circ) {
    if (gate->getType() != GateType::TABLE) {
      if (this->verbose) {
        outs() << "Unsupported gate type: " << toString(gate->getType()) << "\n";
      }
      assert(false);
    }

    // create gate if not exist
    string gateName = "__DualGate__" + to_string(gate->inputs.size()) + "_" +
      to_string(gate->outputs.size()) + "_" + to_string(gate->getTruthTbl());
    if (createdGates.find(gateName) == createdGates.end()) {
      createdGates.insert(gateName);
      defineGate(
        gateName, gate->inputs.size(), gate->outputs.size(), gate->getTruthTbl()
      );
    }

    // init input wires
    for (Wire* inWire : gate->inputs) {
      if (!circ->isInputWire(inWire)) continue;

      Value* inputVal = getInputArchValue(builder, inWire);
      WR->assignArch(inputVal, 2 * inWire->id, true);
      WR->assignArch(inputVal, 2 * inWire->id + 1);
    }

    // init output
    for (size_t i = 0, end = gate->outputs.size(); i < end; ++i) {
      WR->assignConst(0, 2 * gate->outputs[i]->id);
      WR->assignConst(0, 2 * gate->outputs[i]->id + 1);
    }

    // delay for output variables
    addDelay(builder);

    // execute the gate
    vector<Value*> args;
    for (size_t i = 0, inputs = gate->inputs.size(); i < inputs; ++i) {
      args.push_back(WR->getReg(2 * gate->inputs[i]->id));
      args.push_back(WR->getReg(2 * gate->inputs[i]->id + 1));
    }
    for (size_t i = 0, outputs = gate->outputs.size(); i < outputs; ++i) {
      args.push_back(WR->getFakeReg(2 * gate->outputs[i]->id));
      args.push_back(WR->getFakeReg(2 * gate->outputs[i]->id + 1));
    }
    builder.CreateCall(flexo->getFunc(gateName), args);

    // delay for gate execution
    addDelay(builder);
  }

  return readOutputWires(builder);
}

// load the arch value of an output wire
Value* DualRetWM::getWireValue(IRBuilder<> &builder, Wire* wire) {
  // handle constant wires
  if (circ->isConstantWire(wire)) {
    return builder.getInt1(circ->getTrueWire() == wire ? 1 : 0);
  }
  // handle input wires
  if (circ->isInputWire(wire)) {
    return getInputArchValue(builder, wire);
  }
  return getRegValue(2 * wire->id + 1);
}

// load the error detection value of an output wire
Value* DualRetWM::getWireError(IRBuilder<> &builder, Wire* wire) {
  // handle constant/input wires
  if (circ->isConstantWire(wire) || circ->isInputWire(wire)) {
    return builder.getInt1(0);
  }

  Value* O0 = getRegValue(2 * wire->id);
  Value* O1 = getRegValue(2 * wire->id + 1);
  Value* noError = builder.CreateXor(O0, O1);
  Value* hasError = builder.CreateNot(noError);
  return hasError;
}
