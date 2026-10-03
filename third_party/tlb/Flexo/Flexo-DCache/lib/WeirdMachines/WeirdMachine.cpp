//========================================================================
// FILE:
//    WeirdMachine.cpp
//
// DESCRIPTION:
//    Defines a weird machine in an LLVM module.
//
// License: MIT
//========================================================================
#include <string>
#include "Flexo.h"
#include "Utils.h"
#include "Circuits/Circuit.h"
#include "WeirdMachines/WeirdMachine.h"
#include "WeirdRegisters/WeirdRegisters.h"

using namespace llvm;

//-----------------------------------------------------------------------------
// base Weird Machine
//-----------------------------------------------------------------------------

// define a weird machine in an LLVM module
// should be executed in a module pass once
void WeirdMachine::create() {
  this->defineModuleAsm();
  this->declareLibIntrinsic();
  this->defineGlobalVariables();
  this->defineGlobalFunc();
  this->defineGates();
}

// init per-circuit data members
Value* WeirdMachine::createCircuit(
    Function* F, IRBuilder<> &builder, StringRef circuitFile, WeirdRegisters* WR
) {
  this->F = F;
  this->WR = WR;
  argMap.clear();
  inputValues.clear();
  regValues.clear();

  // create a map from Arg name to Arg index
  for (size_t i = 0, end = F->arg_size(); i < end; ++i) {
    string name = F->getArg(i)->getName().str();
    if (name == "") name = "_" + to_string((uintptr_t)(F->getArg(i)));
    argMap[name] = i;
  }

  return nullptr;
}

// declare clflush, llvm.lifetime, llvm.memset, and rand
void WeirdMachine::declareLibIntrinsic() {
  LLVMContext &CTX = this->flexo->getContext();

  // void @llvm.x86.sse2.clflush(ptr)
  PointerType *OpaquePtrTy = PointerType::getUnqual(CTX);
  Type *VoidTy = Type::getVoidTy(CTX);
  FunctionType *ClflushTy = FunctionType::get(VoidTy, OpaquePtrTy, false);
  this->flexo->addFunc("llvm.x86.sse2.clflush", ClflushTy);

  // void @llvm.lifetime.start.p0(i64 immarg, ptr nocapture)
  Type *I64Ty = IntegerType::getInt64Ty(CTX);
  FunctionType *LifetimeStartTy = FunctionType::get(
    VoidTy, { I64Ty, OpaquePtrTy }, false
  );
  this->flexo->addFunc("llvm.lifetime.start.p0", LifetimeStartTy);

  // void @llvm.lifetime.end.p0(i64 immarg, ptr nocapture)
  this->flexo->addFunc("llvm.lifetime.end.p0", LifetimeStartTy);

  // void @llvm.memset.p0.i64(ptr nocapture writeonly, i8, i64, i1 immarg)
  Type *I8Ty = IntegerType::getInt8Ty(CTX);
  Type *I1Ty = IntegerType::getInt1Ty(CTX);
  FunctionType *MemsetTy = FunctionType::get(
    VoidTy, { OpaquePtrTy, I8Ty, I64Ty, I1Ty }, false
  );
  this->flexo->addFunc("llvm.memset.p0.i64", MemsetTy);

  // i32 @rand()
  if (get_str_env("WR_SYSCALL_RAND", "false") == "false") {
    Type *I32Ty = IntegerType::getInt32Ty(CTX);
    FunctionType *RandTy = FunctionType::get(I32Ty, false);
    FunctionCallee Rand = this->flexo->addFunc("rand", RandTy);
    Function *RandF = dyn_cast<Function>(Rand.getCallee());
    RandF->setDoesNotThrow();  
  }
}

void WeirdMachine::defineGlobalVariables() {
  LLVMContext &CTX = this->flexo->getContext();
  this->flexo->addGlobal("WR_HIT_THRESHOLD", ConstantInt::get(IntegerType::getInt64Ty(CTX), get_int_env("WR_HIT_THRESHOLD", 180)));
}

// define delay and timer
void WeirdMachine::defineGlobalFunc() {
  // void @delay()
  LLVMContext &CTX = this->flexo->getContext();
  Type *VoidTy = Type::getVoidTy(CTX);
  FunctionType *DelayTy = FunctionType::get(VoidTy, false);
  FunctionCallee Delay = this->flexo->addFunc("delay", DelayTy);
  Function *DelayF = dyn_cast<Function>(Delay.getCallee());
  DelayF->addFnAttr(llvm::Attribute::AlwaysInline);
  this->defineDelay(DelayF);

  // define printf
  Type *I64Ty = IntegerType::getInt64Ty(CTX);
  Type *charPtrTy = PointerType::getInt8PtrTy(CTX);
  FunctionType *PrintfTy = FunctionType::get(I64Ty, {charPtrTy}, true);
  FunctionCallee Printf = this->flexo->addFunc("printf", PrintfTy);
  Function *PrintfF = dyn_cast<Function>(Printf.getCallee());
  PrintfF->addParamAttr(0, Attribute::NoUndef);
  PrintfF->getArg(0)->setName("str");

  // i64 @timer(ptr %ptr)
  PointerType *OpaquePtrTy = PointerType::getUnqual(CTX);
  FunctionType *TimerTy = FunctionType::get(I64Ty, {OpaquePtrTy}, false);
  FunctionCallee Timer = this->flexo->addFunc("timer", TimerTy);
  Function *TimerF = dyn_cast<Function>(Timer.getCallee());
  TimerF->addParamAttr(0, Attribute::NoUndef);
  TimerF->getArg(0)->setName("ptr");
  TimerF->addFnAttr(llvm::Attribute::AlwaysInline);
  this->defineTimer(TimerF);

  // define mfence
  FunctionType *FenceTy = FunctionType::get(VoidTy, {}, false);
  string constraints = "~{dirflag},~{fpsr},~{flags}";
  fenceAsm = InlineAsm::get(FenceTy, "mfence\n", constraints, true);

  // define syscall rand
  if (get_str_env("WR_SYSCALL_RAND", "false") == "true") {
    Type *I32Ty = IntegerType::getInt32Ty(CTX);
    FunctionType *SyscallRandTy = FunctionType::get(I32Ty, {}, false);
    FunctionCallee SyscallRand = this->flexo->addFunc("rand", SyscallRandTy);
    Function *SyscallRandF = dyn_cast<Function>(SyscallRand.getCallee());
    this->defineSyscallRand(SyscallRandF);
  }

  // define mmap
  FunctionType *MmapTy = FunctionType::get(OpaquePtrTy, {I64Ty}, false);
  FunctionCallee Mmap = this->flexo->addFunc("mmap", MmapTy);
  Function *MmapF = dyn_cast<Function>(Mmap.getCallee());
  MmapF->addParamAttr(0, Attribute::NoUndef);
  MmapF->getArg(0)->setName("len");
  this->defineMmap(MmapF);

  // define munmap
  FunctionType *MunmapTy = FunctionType::get(VoidTy, {OpaquePtrTy, I64Ty}, false);
  FunctionCallee Munmap = this->flexo->addFunc("munmap", MunmapTy);
  Function *MunmapF = dyn_cast<Function>(Munmap.getCallee());
  MunmapF->addParamAttr(0, Attribute::NoUndef);
  MunmapF->getArg(0)->setName("addr");
  MunmapF->addParamAttr(1, Attribute::NoUndef);
  MunmapF->getArg(1)->setName("len");
  this->defineMunmap(MunmapF);


  // define open
  PointerType *I8PtrTy = PointerType::getInt8PtrTy(CTX);
  FunctionType *OpenTy = FunctionType::get(I64Ty, {I8PtrTy, I64Ty, I64Ty}, false);
  FunctionCallee Open = this->flexo->addFunc("open", OpenTy);
  Function *OpenF = dyn_cast<Function>(Open.getCallee());
  OpenF->addParamAttr(0, Attribute::NoUndef);
  OpenF->getArg(0)->setName("path");
  OpenF->addParamAttr(1, Attribute::NoUndef);
  OpenF->getArg(1)->setName("oflag");
  OpenF->addParamAttr(2, Attribute::NoUndef);
  OpenF->getArg(2)->setName("mode");
  this->defineOpen(OpenF);

  // define close
  FunctionType *CloseTy = FunctionType::get(I64Ty, {I64Ty}, false);
  FunctionCallee Close = this->flexo->addFunc("close", CloseTy);
  Function *CloseF = dyn_cast<Function>(Close.getCallee());
  CloseF->addParamAttr(0, Attribute::NoUndef);
  CloseF->getArg(0)->setName("fildis");
  this->defineClose(CloseF);


  // define exit
  FunctionType *ExitTy = FunctionType::get(VoidTy, {I64Ty}, false);
  FunctionCallee Exit = this->flexo->addFunc("exit", ExitTy);
  Function *ExitF = dyn_cast<Function>(Exit.getCallee());
  ExitF->addParamAttr(0, Attribute::NoUndef);
  ExitF->getArg(0)->setName("code");
  this->defineExit(ExitF);

  // define maccess
  FunctionType *MaccessTy = FunctionType::get(VoidTy, {I8PtrTy}, false);
  FunctionCallee Maccess = this->flexo->addFunc("maccess", MaccessTy);
  Function *MaccessF = dyn_cast<Function>(Maccess.getCallee());
  MaccessF->addParamAttr(0, Attribute::NoUndef);
  MaccessF->getArg(0)->setName("addr");
  MaccessF->addFnAttr(llvm::Attribute::AlwaysInline);
  this->defineMaccess(MaccessF);

  /**
   * Late defined functions
   */

}

void WeirdMachine::defineGlobalFuncLate() {
}

// Define delay (wait for mem op)
void WeirdMachine::defineDelay(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I32Ty = IntegerType::getInt32Ty(CTX);
  auto Z = EntryBuilder.CreateAlloca(I32Ty, nullptr, "z");
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  EntryBuilder.CreateCall(
    this->flexo->getFunc("llvm.lifetime.start.p0"),
    {ConstantInt::get(I64Ty, 4), Z}
  );
  EntryBuilder.CreateStore(
    ConstantInt::get(I32Ty, 0), Z, /*isVolatile*/true
  );
  BasicBlock *IncBlk = BasicBlock::Create(CTX, "for.inc", F);
  EntryBuilder.CreateBr(IncBlk);

  // build for.inc block
  IRBuilder<> IncBuilder(IncBlk);
  auto zCurrent = IncBuilder.CreateLoad(
    I32Ty, Z, /*isVolatile*/true, "z.current"
  );
  auto zNext = IncBuilder.CreateAdd(
    zCurrent, ConstantInt::get(I32Ty, 1), "z.next", 
    /*HasNUW*/false, /*HasNSW*/true
  );
  IncBuilder.CreateStore(zNext, Z, /*isVolatile*/true);
  auto loopEnd = ConstantInt::get(I32Ty, get_int_env("WM_DELAY", 256));
  auto cmp = IncBuilder.CreateICmpSLT(zNext, loopEnd, "cmp");
  BasicBlock *CleanupBlk = BasicBlock::Create(CTX, "for.cleanup", F);
  IncBuilder.CreateCondBr(cmp, IncBlk, CleanupBlk);

  // build for.cleanup block
  IRBuilder<> CleanupBuilder(CleanupBlk);
  CleanupBuilder.CreateCall(
    this->flexo->getFunc("llvm.lifetime.end.p0"),
    {ConstantInt::get(I64Ty, 4), Z}
  );
  CleanupBuilder.CreateRetVoid();
}

// Define timer (time the mem access latency)
void WeirdMachine::defineTimer(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  PointerType *OpaquePtrTy = PointerType::getUnqual(CTX);
  FunctionType *TimerAsmTy = FunctionType::get(I64Ty, {OpaquePtrTy}, false);

  // timer asm code
  const char timerAsmCode[] = (
    "rdtscp\n"
    "shl $$32, %rdx\n"
    "mov %rdx, %rsi\n"
    "or %eax, %esi\n"
    "mov ($1), %al\n"
    "rdtscp\n"
    "shl $$32, %rdx\n"
    "or %eax, %edx\n"
    "sub %rsi, %rdx\n"
    "mov %rdx, $0"
  );  
  const char timerAsmConstraints[] = (
    "=r,r,~{rcx},~{rdx},~{rsi},~{eax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *TimerAsm = InlineAsm::get(
    TimerAsmTy, timerAsmCode, timerAsmConstraints, /*hasSideEffects*/true
  );
  auto got = EntryBuilder.CreateCall(TimerAsm, {F->getArg(0)});

  EntryBuilder.CreateRet(got);
}

// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineSyscallRand(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I32Ty = IntegerType::getInt32Ty(CTX);
  auto Z = EntryBuilder.CreateAlloca(I32Ty, nullptr, "z");
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  EntryBuilder.CreateCall(
    this->flexo->getFunc("llvm.lifetime.start.p0"),
    {ConstantInt::get(I64Ty, 4), Z}
  );

  PointerType *OpaquePtrTy = PointerType::getUnqual(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(I32Ty, {OpaquePtrTy}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $1, %rdi\n"
    "mov $$4, %rsi\n"
    "xor %rdx, %rdx\n"
    "mov $$318, %rax\n"
    "syscall\n"
    "mov (%rdi), %edi\n"
    "mov %edi, $0"
  );  
  const char syscallAsmConstraints[] = (
    "=r,r,~{rdi},~{rdx},~{rsi},~{rax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  auto got = EntryBuilder.CreateCall(SyscallAsm, {Z});
  EntryBuilder.CreateCall(
    this->flexo->getFunc("llvm.lifetime.end.p0"),
    {ConstantInt::get(I64Ty, 4), Z}
  );

  EntryBuilder.CreateRet(got);
}

// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineMmap(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  PointerType *OpaquePtrTy = PointerType::getUnqual(CTX);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(OpaquePtrTy, {I64Ty}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $$0, %rdi\n"   // addr (NULL)
    "mov $1, %rsi\n"    // len (arg)
    "mov $$3, %rdx\n"   // prot (PROT_READ | PROT_WRITE)
    "mov $$34, %r10\n"  // flags (MAP_PRIVATE | MAP_ANONYMOUS)
    "or  $$-1, %r8d\n"  // fd (-1)
    "mov $$0, %r9\n"    // offset (0)
    "mov $$9, %rax\n"   // syscall num
    "syscall\n"
    "mov %rax, $0"
  );  
  const char syscallAsmConstraints[] = (
    "=r,r,~{rdi},~{rdx},~{rsi},~{rax},~{r8},~{r9},~{r10},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  Value* len = F->getArg(0);
  auto got = EntryBuilder.CreateCall(SyscallAsm, {len});

  EntryBuilder.CreateRet(got);
}

// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineMunmap(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  PointerType *OpaquePtrTy = PointerType::getUnqual(CTX);
  Type *VoidTy = Type::getVoidTy(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(VoidTy, {OpaquePtrTy, I64Ty}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $0, %rdi\n"
    "mov $1, %rsi\n"
    "mov $$11, %rax\n"
    "syscall\n"
  );  
  const char syscallAsmConstraints[] = (
    "r,r,~{rdi},~{rsi},~{rax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  auto addr = F->getArg(0);
  auto len = F->getArg(1);
  EntryBuilder.CreateCall(SyscallAsm, {addr, len});
  EntryBuilder.CreateRetVoid();
}

// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineOpen(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  // FunctionType *OpenTy = FunctionType::get(I64Ty, {charPtrTy, I64Ty, I64Ty}, false);
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  Type *charPtrTy = PointerType::getInt8PtrTy(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(I64Ty, {charPtrTy, I64Ty, I64Ty}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $1, %rdi\n"  // path
    "mov $2, %rsi\n"  // flags
    "mov $3, %rdx\n"  // mode
    "mov $$2, %rax\n"
    "syscall\n"
    "mov %rax, $0"
  );  
  const char syscallAsmConstraints[] = (
    "=r,r,r,r,~{rdx},~{rdi},~{rsi},~{rax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  auto path = F->getArg(0);
  auto flags = F->getArg(1);
  auto mode = F->getArg(2);
  auto got = EntryBuilder.CreateCall(SyscallAsm, {path, flags, mode});
  EntryBuilder.CreateRet(got);
}

// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineClose(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(I64Ty, {I64Ty}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $1, %rdi\n"  // fildis
    "mov $$3, %rax\n"
    "syscall\n"
    "mov %rax, $0"
  );  
  const char syscallAsmConstraints[] = (
    "=r,r,~{rdi},~{rax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  auto fildis = F->getArg(0);
  auto got = EntryBuilder.CreateCall(SyscallAsm, {fildis});
  EntryBuilder.CreateRet(got);
}


// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineExit(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  Type *VoidTy = Type::getVoidTy(CTX);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(VoidTy, {I64Ty}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $0, %rdi\n" // code
    "mov $$60, %rax\n"
    "syscall\n"
  );  
  const char syscallAsmConstraints[] = (
    "r,~{rdi},~{rax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  auto code = F->getArg(0);
  EntryBuilder.CreateCall(SyscallAsm, {
    code
  });
  EntryBuilder.CreateRetVoid();
}

// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineMaccess(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  Type *VoidTy = Type::getVoidTy(CTX);
  PointerType *I8PtrTy = PointerType::getInt8PtrTy(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(VoidTy, {I8PtrTy}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov ($0), %rdi\n"
  );  
  const char syscallAsmConstraints[] = (
    "r,~{rdi},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  auto addr = F->getArg(0);
  EntryBuilder.CreateCall(SyscallAsm, {
    addr
  });
  EntryBuilder.CreateRetVoid();
}

// insert NOP instructions
void WeirdMachine::addNOP(IRBuilder<> &builder, int size) {
  assert(size > 0);
  LLVMContext &CTX = this->flexo->getContext();
  Type *VoidTy = Type::getVoidTy(CTX);
  FunctionType *NopAsmTy = FunctionType::get(VoidTy, false);

  std::string NopAsmCode(".byte 0x90");
  NopAsmCode.reserve(10 + (5 * (size - 1)));
  for (int i = 0; i < (size - 1); ++i) {
    NopAsmCode += ",0x90";
  }
  const char NopAsmConstraints[] = "~{memory},~{dirflag},~{fpsr},~{flags}";
  InlineAsm *NopAsm = InlineAsm::get(
    NopAsmTy, NopAsmCode, NopAsmConstraints, /*hasSideEffects*/true
  );
  auto NopAsmCall = builder.CreateCall(NopAsm);
  NopAsmCall->setTailCall();
}

// insert fence instructions (or empty loop)
void WeirdMachine::addDelay(IRBuilder<> &builder) {
  if (useFence) builder.CreateCall(fenceAsm);
  else builder.CreateCall(flexo->getFunc("delay"));
}

// load a synthesized circuit from a file
void WeirdMachine::loadCircuit(StringRef circuitFile, CircuitType circuitType) {
  if (circ != nullptr) delete circ;
  circ = new Circuit();

  circ->verbose = verbose;
  if (circuitType == CircuitType::BLIF) {
    circ->parseBlif(circuitFile);
  } else {
    assert(false && "Unsupported circuit type");
  }

  if (verbose) {
    outs() << "[Circuit]\n" << circ->dump();
  }
  outs() << "[Circuit] Wires: " << circ->getWireCount() << "\n";
  outs() << "[Circuit] Gates: " << circ->end() - circ->begin() << "\n";
}

// get the bit of an arch value, offset is the i-th bit of a bus (starts from 0)
Value* WeirdMachine::getInputArchValue(IRBuilder<> &builder, Wire* wire) {
  if (inputValues.find(wire) != inputValues.end()) return inputValues[wire];

  int inputIdx = circ->getInputIdx(wire);
  auto arg = F->getArg(argMap[circ->getInputName(inputIdx)]);
  size_t offset = circ->getInputOffset(inputIdx);

  IntegerType *I8Ty = builder.getInt8Ty();
  Value* output = arg;

  // load a single wire from a bus (unsigned char*)
  unsigned width;
  if (arg->getType()->isPointerTy()) {
    Value* loadAddr = offset >= 8 ? builder.CreateGEP(
      I8Ty, arg, {builder.getInt64(offset / 8)}, "", true
    ) : arg;
    output = builder.CreateLoad(I8Ty, loadAddr);
    width = 8;
  }
  else {
    width = output->getType()->getIntegerBitWidth();
  }

  // mask the output value to a single bit and cast to I8Ty
  if (width > 1) {
    if (offset % width) {
      output = builder.CreateLShr(output, builder.getIntN(width, offset % width));
    }
    if (width > 8) {
      output = builder.CreateTrunc(output, I8Ty);
    }
    output = builder.CreateAnd(output, builder.getInt8(1));
  }

  inputValues[wire] = output;
  return output;
}

// load a WR and cache its value
Value* WeirdMachine::getRegValue(int regId) {
  if (regValues.find(regId) != regValues.end()) return regValues[regId];

  Value* output = WR->loadReg(regId);
  regValues[regId] = output;
  return output;
}

// write output values to function arguments
void WeirdMachine::writeOutput(IRBuilder<> &builder, Value* arg, vector<Value*>& values) {
  LLVMContext &CTX = flexo->getContext();
  IntegerType *I8Ty = IntegerType::getInt8Ty(CTX);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);

  // write 8 outputWires at a time
  Value* byteVal = nullptr;
  for (size_t i = 0, end = values.size(); i < end; ++i) {
    if (values[i] != nullptr) {
      Value* wireVal = builder.CreateZExt(values[i], I8Ty);
      if (i % 8) wireVal = builder.CreateShl(wireVal, i % 8);

      if (byteVal == nullptr) {
        byteVal = wireVal;
      }
      else {
        byteVal = builder.CreateOr(byteVal, wireVal);
      }
    }

    // store byteVal if i is a multiple of 8 or the last byte
    if (i % 8 == 7 || i == end - 1) {
      assert(byteVal != nullptr);
      Value* storeAddr = arg;
      if (i / 8 != 0) {
        storeAddr = builder.CreateGEP(I8Ty, arg, {ConstantInt::get(I64Ty, i / 8)});
      }
      builder.CreateStore(byteVal, storeAddr);
      byteVal = nullptr;
    }
  }
}

// load the arch value of an output wire
Value* WeirdMachine::getWireValue(IRBuilder<> &builder, Wire* wire) {
  return getRegValue(wire->id);
}

// load the error detection value of an output wire
Value* WeirdMachine::getWireError(IRBuilder<> &builder, Wire* wire) {
  return builder.getInt1(0);
}

// read all output wires from a circuit
Value* WeirdMachine::readOutputWires(IRBuilder<> &builder) {
  unordered_map<size_t, vector<Value*>> argToValues;
  unordered_map<Wire*, Value*> wireToValue;
  unordered_map<Wire*, Value*> wireToError;
  Value* errorDetected = nullptr;


  for (size_t i = 0, end = circ->getOutputCount(); i < end; ++i) {
    Wire* outWire = circ->getOutput(i);
    size_t argIdx = argMap[circ->getOutputName(i)];
    size_t offset = circ->getOutputOffset(i);
    string errArgName = "error_" + circ->getOutputName(i).str();
    bool hasErrArg = argMap.find(errArgName) != argMap.end();
    size_t errArgIdx;

    // resize argToValues if necessary
    if (argToValues[argIdx].size() <= offset) {
      argToValues[argIdx].resize(offset + 1);
    }

    if (hasErrArg) {
      errArgIdx = argMap[errArgName];
      if (argToValues[errArgIdx].size() <= offset) {
        argToValues[errArgIdx].resize(offset + 1);
      }
    }

    // create wire values if not cached already
    if (wireToValue.find(outWire) == wireToValue.end()) {
      wireToValue[outWire] = getWireValue(builder, outWire);
      Value* hasError = getWireError(builder, outWire);
      wireToError[outWire] = hasError;
      if (errorDetected == nullptr) {
        errorDetected = hasError;
      }
      else {
        errorDetected = builder.CreateOr(errorDetected, hasError);
      }
    }

    argToValues[argIdx][offset] = wireToValue[outWire];
    if (hasErrArg) argToValues[errArgIdx][offset] = wireToError[outWire];
  }

  // write output wires to function arguments
  for (auto& args : argToValues) {
    writeOutput(builder, F->getArg(args.first), args.second);
  }

  return errorDetected == nullptr ? builder.getInt1(0) : errorDetected;
}
