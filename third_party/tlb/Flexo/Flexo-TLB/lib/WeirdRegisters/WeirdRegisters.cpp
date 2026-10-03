//=============================================================================
// FILE:
//    WeirdRegisters.cpp
//
// DESCRIPTION:
//    Manage the weird registers of a WM in function scope
//
// License: MIT
//=============================================================================
#include <string>

#include "WeirdRegisters/WeirdRegisters.h"
#include "Flexo.h"
#include "Utils.h"
#include "WeirdRegisters/Mappings/Mapping.h"
#include "WeirdRegisters/Mappings/ShuffleMap.h"
#include "tlb_ioctl.h"

using namespace llvm;

int WeirdRegisters::regOffset = PAGE;
int WeirdRegisters::fakeOffset = 0;

WeirdRegisters::WeirdRegisters(
  Flexo* flexo, IRBuilder<>& builder, int align
): flexo(flexo), builder(builder), count(-1), align(Align(align)) {

  string mappingType = get_str_env("WR_MAPPING", "Shuffle");
  if (mappingType == "Baseline") {
    mapping = new Mapping(flexo, builder);
  } else if (mappingType == "Shuffle") {
    mapping = new ShuffleMap(flexo, builder);
  } else {
    errs() << "Invalid WR_MAPPING: " << mappingType << "\n";
    exit(1);
  }
}

WeirdRegisters::~WeirdRegisters() {
  delete mapping;
}

// release memory and clean up WRegIdxArr
void WeirdRegisters::cleanup() {

  WRegIdxArr.clear();
  WRegOffsets.clear();
  FWRegIdxArr.clear();
  FWRegOffsets.clear();
}

// allocate WRegs using mmap or alloca
void WeirdRegisters::allocate(int count) {
  assert(this->count == -1);
  this->count = count;
  flexo->register_count = max(count, flexo->register_count);
  mapping->init(count);

  WRegIdxArr.insert(WRegIdxArr.begin(), count, nullptr);
  WRegOffsets.insert(WRegOffsets.begin(), count, nullptr);
  FWRegIdxArr.insert(FWRegIdxArr.begin(), count, nullptr);
  FWRegOffsets.insert(FWRegOffsets.begin(), count, nullptr);

  size = (count + firstIdx) * regOffset;
  
  WRegs = builder.CreateLoad(builder.getInt8PtrTy(), flexo->getGlobal("wregs"));
}

// assign an arch value to WR
// This will create new basic blocks.
void WeirdRegisters::assignArch(Value* archVal, int regId, bool invert) {
  LLVMContext &CTX = builder.getContext();
  Value *WRegIdx = getCreateReg(regId);

  // init weirdReg to 1 (arch value 0)
  builder.CreateCall(flexo->getFunc("maccess"), {WRegIdx});

  // create branches to assign archReg to weirdReg
  Function* func = builder.GetInsertBlock()->getParent();
  BasicBlock *assignBlk = BasicBlock::Create(CTX, "assign", func);
  BasicBlock *assignEndBlk = BasicBlock::Create(CTX, "assign.end", func);
  if (archVal->getType() != builder.getInt1Ty()) {
    archVal = builder.CreateICmpNE(archVal, builder.getInt8(0));
  }
  builder.CreateCondBr(
    archVal,
    invert ? assignBlk : assignEndBlk,
    invert ? assignEndBlk : assignBlk
  );
  builder.SetInsertPoint(assignBlk);

  // flush weirdReg if archReg is False
  builder.CreateCall(
    flexo->getFunc("invlpg"), {WRegIdx}
  );
  builder.CreateBr(assignEndBlk);
  builder.SetInsertPoint(assignEndBlk);
}

// assign a constant value (either 0 or 1) to WR
void WeirdRegisters::assignConst(int val, int regId) {
  Value* WRegIdx = getCreateReg(regId);

  if (val == 0){
    builder.CreateCall(
      flexo->getFunc("invlpg"), {WRegIdx}
    );
  }
  else {
    builder.CreateCall(flexo->getFunc("maccess"), {WRegIdx});
  }
}

// return 1 if WR in cache, else return 0
Value* WeirdRegisters::loadReg(int regId) {
  auto cycles = builder.CreateCall(
    flexo->getFunc("timer"), {getReg(regId)}
  );
  auto threshold = builder.CreateLoad(builder.getInt64Ty(), flexo->getGlobal("WR_HIT_THRESHOLD"));
  // cache hit if cycles <= threshold
  auto archVal = builder.CreateICmpULT(cycles, threshold);
  return archVal;
};

// create a new WR Idx if not exist
Value* WeirdRegisters::getCreateReg(int regId) {
  Value* got = WRegIdxArr[regId];
  if (got != nullptr) return got;

  IntegerType *I8Ty = builder.getInt8Ty();
  Value* WRegOffset = getCreateRegOffset(regId);
  Value* FWRegOffset = getCreateFRegOffset(regId);

  std::string name = "WR" + std::to_string(regId);
  WRegIdxArr[regId] = builder.CreateGEP(
    I8Ty, WRegs, {WRegOffset}, name, /*IsInBounds*/true
  );
  FWRegIdxArr[regId] = builder.CreateGEP(
    I8Ty, WRegs, {FWRegOffset}, "F" + name, /*IsInBounds*/true
  );
  return WRegIdxArr[regId];
}

// create a new WR offset if not exist
Value* WeirdRegisters::getCreateRegOffset(int regId) {
  Value* got = WRegOffsets[regId];
  if (got != nullptr) return got;

  IntegerType *I64Ty = builder.getInt64Ty();

  if (mapping->compileTimeMap) {
    int realId = mapping->getRealId(regId);
    int offset = (realId + firstIdx) * regOffset;
    got = builder.getInt64(offset);
  }
  else {
    Value* realId = mapping->getRuntimeRealId(regId);
    Value* realId64 = builder.CreateZExt(realId, I64Ty);
    got = builder.CreateMul(
      builder.CreateAdd(realId64, builder.getInt64(firstIdx)),
      builder.getInt64(regOffset), "offset." + std::to_string(regId)
    );
  }

  WRegOffsets[regId] = got;
  return got;
}

// create a new FWR offset if not exist
Value* WeirdRegisters::getCreateFRegOffset(int regId) {
  Value* got = FWRegOffsets[regId];
  if (got != nullptr) return got;

  Value* WRegOffset = getCreateRegOffset(regId);
  if (mapping->compileTimeMap) {
    int realId = mapping->getRealId(regId);
    int offset = (realId + firstIdx) * regOffset;
    got = builder.getInt64(offset - fakeOffset);
  }
  else {
    got = builder.CreateSub(
      WRegOffset, builder.getInt64(fakeOffset), 
      "fake.offset." + std::to_string(regId)
    );
  }

  FWRegOffsets[regId] = got;
  return got;
}

// get WR using its ID (starts from 0)
Value* WeirdRegisters::getReg(int regId) {
  Value* got = WRegIdxArr[regId];
  assert(got != nullptr);
  return got;
}

// get FWR (WR_FAKE_OFFSET away from WR) using its ID (starts from 0)
Value* WeirdRegisters::getFakeReg(int regId) {
  Value* got = FWRegIdxArr[regId];
  assert(got != nullptr);
  return got;
}
