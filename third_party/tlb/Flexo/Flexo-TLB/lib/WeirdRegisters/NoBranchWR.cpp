//=============================================================================
// FILE:
//    NoBranchWR.cpp
//
// DESCRIPTION:
//    Assign an arch value to WR without using branch instructions
//
// License: MIT
//=============================================================================
#include <string>
#include "Flexo.h"
#include "WeirdRegisters/NoBranchWR.h"

using namespace llvm;

// assign an arch value to WR
// This version avoids branch instructions (prevents BP to do weird things)
void NoBranchWR::assignArch(Value* archVal, int regId, bool invert) {
  getCreateReg(regId);
  Value* WRegOffset = getCreateRegOffset(regId);
  const std::string regName = "WR" + std::to_string(regId);

  // access: archVal ? WRegOffset : 0
  IntegerType *I64Ty = builder.getInt64Ty();
  auto archVal64 = builder.CreateZExt(archVal, I64Ty);
  auto archValOffset = builder.CreateMul(archVal64, WRegOffset);
  const auto accessOffset = archValOffset;

  // flush: archVal ? 0 : WRegOffset
  auto flushOffset = builder.CreateSub(WRegOffset, archValOffset);

  // access accessOffset and flush flushOffset
  const auto accessIdx = getWRegGEP(
    invert ? flushOffset : accessOffset, "access." + regName
  );
  builder.CreateCall(flexo->getFunc("maccess"), {accessIdx});
  const auto flushIdx = getWRegGEP(
    invert ? accessOffset : flushOffset, "flush." + regName
  );
  builder.CreateCall(
    flexo->getFunc("invlpg"), {flushIdx}
  );
}

// get GEP of a weird register (&WRegs[offset])
Value* NoBranchWR::getWRegGEP(Value* offset, StringRef name) {
  IntegerType *I8Ty = builder.getInt8Ty();
  return builder.CreateGEP(I8Ty, WRegs, {offset}, name, /*IsInBounds*/true);
}
