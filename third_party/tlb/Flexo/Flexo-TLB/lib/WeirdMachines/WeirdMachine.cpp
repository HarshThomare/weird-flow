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
#include <fcntl.h>
#include <sys/mman.h>

#include "Flexo.h"
#include "Utils.h"
#include "Circuits/Circuit.h"
#include "WeirdMachines/WeirdMachine.h"
#include "WeirdRegisters/WeirdRegisters.h"
#include "tlb_ioctl.h"

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
  this->flexo->addGlobal("fd_kernel_module", IntegerType::getInt64Ty(CTX));
  this->flexo->addGlobal("wregs", ConstantPointerNull::get(IntegerType::getInt8PtrTy(CTX)));
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

  // define lfence
  FunctionType *FenceTy = FunctionType::get(VoidTy, {}, false);
  string constraints = "~{dirflag},~{fpsr},~{flags}";
  // lfence is enough, because we use only loads, no stores
  fenceAsm = InlineAsm::get(FenceTy, "lfence\n", constraints, true);

  // define syscall rand
  if (get_str_env("WR_SYSCALL_RAND", "false") == "true") {
    Type *I32Ty = IntegerType::getInt32Ty(CTX);
    FunctionType *SyscallRandTy = FunctionType::get(I32Ty, {}, false);
    FunctionCallee SyscallRand = this->flexo->addFunc("rand", SyscallRandTy);
    Function *SyscallRandF = dyn_cast<Function>(SyscallRand.getCallee());
    this->defineSyscallRand(SyscallRandF);
  }

  // define mmap
  FunctionType *MmapTy = FunctionType::get(OpaquePtrTy, {OpaquePtrTy, I64Ty, I64Ty, I64Ty, I64Ty}, false);
  FunctionCallee Mmap = this->flexo->addFunc("mmap", MmapTy);
  Function *MmapF = dyn_cast<Function>(Mmap.getCallee());
  MmapF->addParamAttr(0, Attribute::NoUndef);
  MmapF->getArg(0)->setName("addr");
  MmapF->addParamAttr(1, Attribute::NoUndef);
  MmapF->getArg(1)->setName("len");
  MmapF->addParamAttr(2, Attribute::NoUndef);
  MmapF->getArg(2)->setName("prot");
  MmapF->addParamAttr(3, Attribute::NoUndef);
  MmapF->getArg(3)->setName("flags");
  MmapF->addParamAttr(4, Attribute::NoUndef);
  MmapF->getArg(4)->setName("fildes");
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

  // define write
  FunctionType *WriteTy = FunctionType::get(I64Ty, {I64Ty, I8PtrTy, I64Ty}, false);
  FunctionCallee Write = this->flexo->addFunc("write", WriteTy);
  Function *WriteF = dyn_cast<Function>(Write.getCallee());
  WriteF->addParamAttr(0, Attribute::NoUndef);
  WriteF->getArg(0)->setName("fildes");
  WriteF->addParamAttr(1, Attribute::NoUndef);
  WriteF->getArg(1)->setName("buf");
  WriteF->addParamAttr(2, Attribute::NoUndef);
  WriteF->getArg(2)->setName("nbyte");
  this->defineWrite(WriteF);

  // define access
  FunctionType *AccessTy = FunctionType::get(I64Ty, {I8PtrTy, I64Ty}, false);
  FunctionCallee Access = this->flexo->addFunc("access", AccessTy);
  Function *AccessF = dyn_cast<Function>(Access.getCallee());
  AccessF->addParamAttr(0, Attribute::NoUndef);
  AccessF->getArg(0)->setName("path");
  AccessF->addParamAttr(1, Attribute::NoUndef);
  AccessF->getArg(1)->setName("amode");
  this->defineAccess(AccessF);

  // define invlpg
  FunctionType *InvlpgTy = FunctionType::get(I64Ty, {I8PtrTy}, false);
  FunctionCallee Invlpg = this->flexo->addFunc("invlpg", InvlpgTy);
  Function *InvlpgF = dyn_cast<Function>(Invlpg.getCallee());
  InvlpgF->addParamAttr(0, Attribute::NoUndef);
  InvlpgF->getArg(0)->setName("addr");
  this->defineInvlpg(InvlpgF);


  /**
   * Late defined functions
   */

  // define allocWeirdMemory
  FunctionType *OnMainStartTy = FunctionType::get(VoidTy, {}, false);
  this->flexo->addFunc("onMainStart", OnMainStartTy);

  FunctionType *OnMainEndTy = FunctionType::get(VoidTy, {}, false);
  this->flexo->addFunc("onMainEnd", OnMainEndTy);

  FunctionType *AllocWeirdMemoryTy = FunctionType::get(VoidTy, {}, false);
  this->flexo->addFunc("allocWeirdMemory", AllocWeirdMemoryTy);

  // define deallocWeirdMemory
  FunctionType *DeallocWeirdMemoryTy = FunctionType::get(VoidTy, {}, false);
  this->flexo->addFunc("deallocWeirdMemory", DeallocWeirdMemoryTy);

}

void WeirdMachine::defineGlobalFuncLate() {
  FunctionCallee OnMainStart = this->flexo->getFunc("onMainStart");
  Function *OnMainStartF = dyn_cast<Function>(OnMainStart.getCallee());
  this->defineOnMainStart(OnMainStartF);

  FunctionCallee OnMainEnd = this->flexo->getFunc("onMainEnd");
  Function *OnMainEndF = dyn_cast<Function>(OnMainEnd.getCallee());
  this->defineOnMainEnd(OnMainEndF);

  FunctionCallee AllocWeirdMemory = this->flexo->getFunc("allocWeirdMemory");
  Function *AllocWeirdMemoryF = dyn_cast<Function>(AllocWeirdMemory.getCallee());
  this->defineAllocWeirdMemory(AllocWeirdMemoryF);

  FunctionCallee DeallocWeirdMemory = this->flexo->getFunc("deallocWeirdMemory");
  Function *DeallocWeirdMemoryF = dyn_cast<Function>(DeallocWeirdMemory.getCallee());
  this->defineDeallocWeirdMemory(DeallocWeirdMemoryF);
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
    "rdtscp\n\t"
    "shl    $$0x20, %rdx\n\t"
    "or     %rdx, %rax\n\t"
    "mov    %rax, %rsi\n\t"

    /* Use timestamp result for serialization */
    "cmp    $$0xbaaaaad, %rsi\n\t"
    "sete   %al\n\t"
    "movzbl %al, %eax\n\t"
    "or     %rax, $1\n\t"
    "mov    ($1), %al\n\t"

    "rdtscp\n\t"  // waits for previous loads
    "shl    $$0x20, %rdx\n\t"
    "or     %rdx, %rax\n\t"
    "sub    %rsi, %rax\n\t"
    "mov    %rax, $0"
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

void WeirdMachine::defineMmap(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  PointerType *OpaquePtrTy = PointerType::getUnqual(CTX);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(OpaquePtrTy, {OpaquePtrTy, I64Ty, I64Ty, I64Ty, I64Ty}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $1, %rdi\n"  // addr
    "mov $2, %rsi\n"  // len
    "mov $3, %rdx\n"  // prot
    "mov $4, %r10\n"  // flags
    "mov $5, %r8\n"   // fd
    "mov $$0, %r9\n"  // offset (0)
    "mov $$9, %rax\n" // syscall num
    "syscall\n"
    "mov %rax, $0"
  );  
  const char syscallAsmConstraints[] = (
    "=r,r,r,r,r,r,~{rdi},~{rdx},~{rsi},~{rax},~{r8},~{r9},~{r10},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  Value *addr = F->getArg(0);
  Value *len = F->getArg(1);
  Value *prot = F->getArg(2);
  Value *flags = F->getArg(3);
  Value *fildes = F->getArg(4);
  auto got = EntryBuilder.CreateCall(SyscallAsm, {addr, len, prot, flags, fildes});

  EntryBuilder.CreateRet(got);
}

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
void WeirdMachine::defineWrite(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  PointerType *charPtrTy = PointerType::getInt8PtrTy(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(I64Ty, {I64Ty, charPtrTy, I64Ty}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $1, %rdi\n"  // fildis
    "mov $2, %rsi\n"  // buf
    "mov $3, %rdx\n"  // nbyte
    "mov $$1, %rax\n"
    "syscall\n"
    "mov %rax, $0"
  );  
  const char syscallAsmConstraints[] = (
    "=r,r,r,r,~{rdx},~{rdi},~{rsi},~{rax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  auto fildis = F->getArg(0);
  auto buf = F->getArg(1);
  auto nbyte = F->getArg(2);
  auto got = EntryBuilder.CreateCall(SyscallAsm, {fildis, buf, nbyte});
  EntryBuilder.CreateRet(got);
}

// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineAccess(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  // FunctionType *AccessTy = FunctionType::get(I64Ty, {charPtrTy, I64Ty}, false);
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  PointerType *charPtrTy = PointerType::getInt8PtrTy(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(I64Ty, {charPtrTy, I64Ty}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $1, %rdi\n"
    "mov $2, %rsi\n"
    "mov $$21, %rax\n"
    "syscall\n"
    "mov %rax, $0"
  );  
  const char syscallAsmConstraints[] = (
    "=r,r,r,~{rdi},~{rsi},~{rax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );
  auto path = F->getArg(0);
  auto amode = F->getArg(1);
  auto got = EntryBuilder.CreateCall(SyscallAsm, {path, amode});
  EntryBuilder.CreateRet(got);
}


// Define syscall rand (random w/o stdlib)
void WeirdMachine::defineInvlpg(Function *F) {
  LLVMContext &CTX = this->flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> EntryBuilder(EntryBlk);
  IntegerType *I64Ty = IntegerType::getInt64Ty(CTX);
  PointerType *I8PtrTy = PointerType::getInt8PtrTy(CTX);
  FunctionType *SyscallAsmTy = FunctionType::get(I64Ty, {I64Ty, I64Ty, I8PtrTy}, false);

  // syscall asm code
  const char syscallAsmCode[] = (
    "mov $1, %rdi\n"  // fd
    "mov $2, %rsi\n"  // code
    "mov $3, %rdx\n"  // addr
    "mov $$16, %rax\n"
    "syscall\n"
    "mov %rax, $0\n"
  );  
  const char syscallAsmConstraints[] = (
    "=r,r,r,r,~{rdx},~{rdi},~{rsi},~{rax},~{dirflag},~{fpsr},~{flags}"
  );
  InlineAsm *SyscallAsm = InlineAsm::get(
    SyscallAsmTy, syscallAsmCode, syscallAsmConstraints, /*hasSideEffects*/true
  );

  Value *fd_kernel_module = EntryBuilder.CreateLoad(
    EntryBuilder.getInt64Ty(),
    this->flexo->getGlobal("fd_kernel_module")
  );
  auto addr = F->getArg(0);
  auto got = EntryBuilder.CreateCall(SyscallAsm, {
    fd_kernel_module,
    EntryBuilder.getInt64(IOCTL_FLUSH_TLB_INVLPG),
    addr
  });
  EntryBuilder.CreateRet(got);
}

void WeirdMachine::defineOnMainStart(Function *F) {
  LLVMContext &CTX = flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> builder(EntryBlk);

  builder.CreateCall(flexo->getFunc("allocWeirdMemory"));

  // Open kernel_module filedescriptor
  Value *permissions = builder.getInt64(0644);
  Value *flagsOpen = builder.getInt64(O_RDWR);

  auto fd_kernel_module = this->flexo->getGlobal("fd_kernel_module");
  Value *tlb_device_name = builder.CreateGlobalStringPtr(TLB_DEVICE_NAME_FULL);
  Value *tlb_fd = builder.CreateCall(flexo->getFunc("open"), {tlb_device_name, flagsOpen, permissions});

  BasicBlock *fdCheckFail = BasicBlock::Create(CTX, "fd_check.fail", F);
  BasicBlock *fdCheckEnd = BasicBlock::Create(CTX, "fd_check.end", F);

  // Check if fd is valid
  Value *tlb_fdCond = builder.CreateICmpSLT(tlb_fd, builder.getInt64(0));
  builder.CreateCondBr(tlb_fdCond, fdCheckFail, fdCheckEnd);

  builder.SetInsertPoint(fdCheckFail);
  Value *error_msg = builder.CreateGlobalStringPtr("Could not open device\n");

  builder.CreateCall(flexo->getFunc("printf"), {error_msg});
  builder.CreateCall(flexo->getFunc("exit"), {builder.getInt64(1)});
  builder.CreateBr(fdCheckEnd);

  builder.SetInsertPoint(fdCheckEnd);
  // Store fd globally
  builder.CreateStore(tlb_fd, fd_kernel_module);

  builder.CreateRetVoid();
}

void WeirdMachine::defineOnMainEnd(Function *F) {
  LLVMContext &CTX = flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> builder(EntryBlk);

  builder.CreateCall(flexo->getFunc("deallocWeirdMemory"));

  // Close kernel_module filedescriptor
  Value *global_fd_kernel_module = flexo->getGlobal("fd_kernel_module");
  Value *fd_kernel_module = builder.CreateLoad(builder.getInt64Ty(), global_fd_kernel_module, "fd_kernel_module");
  builder.CreateCall(flexo->getFunc("close"), {fd_kernel_module});
  builder.CreateStore(builder.getInt64(-1), global_fd_kernel_module);

  builder.CreateRetVoid();
}

void WeirdMachine::defineAllocWeirdMemory(Function *F) {
  LLVMContext &CTX = flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> builder(EntryBlk);

  FunctionCallee accessFunc = flexo->getFunc("access");
  FunctionCallee writeFunc = flexo->getFunc("write");
  FunctionCallee mmapFunc = flexo->getFunc("mmap");
  FunctionCallee openFunc = flexo->getFunc("open");
  FunctionCallee closeFunc = flexo->getFunc("close");

  auto size = (flexo->register_count + WeirdRegisters::firstIdx) * WeirdRegisters::regOffset;

  /**
   * Locals
   */
  Value *filename = builder.CreateGlobalStringPtr("myfile.bin");
  Value *sharebuf = builder.CreateAlloca(ArrayType::get(builder.getInt8Ty(), WeirdRegisters::regOffset), nullptr, "sharebuf");
  builder.CreateMemSet(
      sharebuf,
      builder.getInt8(0), // value to set (0)
      WeirdRegisters::regOffset,  // size (bytes)
      MaybeAlign(1)       // alignment
  );
  Value *fd = builder.CreateAlloca(builder.getInt64Ty(), nullptr, "fd");

  /**
   * if (access(fn, F_OK) != 0)
   */
  Value *f_ok = builder.getInt64(F_OK);
  Value *accessRes = builder.CreateCall(accessFunc, {filename, f_ok});
  Value *ifCond = builder.CreateICmpNE(accessRes, builder.getInt64(0));

  BasicBlock *ifCreate = BasicBlock::Create(CTX, "accessif.create", F);
  BasicBlock *ifOpen = BasicBlock::Create(CTX, "accessif.open", F);
  BasicBlock *ifDone = BasicBlock::Create(CTX, "accessif.done", F);

  builder.CreateCondBr(ifCond, ifCreate, ifOpen);
  // {

  /**
   * Create missing file as PAGE
   */
  builder.SetInsertPoint(ifCreate);

  /**
   * fd = open(fn, O_RDWR | O_CREAT | O_TRUNC, 0644);
   */
  Value *flagsCreate = builder.getInt64(O_RDWR | O_CREAT | O_TRUNC);
  Value *permissions = builder.getInt64(0644);
  builder.CreateStore(builder.CreateCall(openFunc, {filename, flagsCreate, permissions}), fd);

  /**
   * write(fd, sharebuf, PAGE)
   */
  builder.CreateCall(writeFunc, {
    builder.CreateLoad(builder.getInt64Ty(), fd, "fd"),
    sharebuf,
    builder.getInt64(WeirdRegisters::regOffset)
  });
  builder.CreateBr(ifDone);
  // } else {
  /**
   * Just open file
   */
  builder.SetInsertPoint(ifOpen);
  Value *flagsOpen = builder.getInt64(O_RDWR);
  builder.CreateStore(builder.CreateCall(openFunc, {filename, flagsOpen, permissions}), fd);
  builder.CreateBr(ifDone);
  // }

  /**
   * After create/open file
   */
  builder.SetInsertPoint(ifDone);

  /**
   * WRegs = mmap(NULL, n * PAGE, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
   */
  Value *protReserve = builder.getInt64(PROT_NONE);
  Value *flagsReserve = builder.getInt64(MAP_PRIVATE | MAP_ANONYMOUS);
  auto weirdMem = builder.CreateCall(mmapFunc, {
    ConstantPointerNull::get(builder.getInt8PtrTy()),
    builder.getInt64(size),
    protReserve,
    flagsReserve,
    builder.getInt64(-1),
  });
  builder.CreateStore(weirdMem, flexo->getGlobal("wregs"), false);

  /**
   * mmap((void *) base + (i*PAGE), PAGE, PROT_READ|PROT_WRITE|PROT_EXEC, MAP_FIXED|MAP_SHARED|MAP_POPULATE|MAP_FILE, fd, 0);
   */
  Value *protMmap = builder.getInt64(PROT_READ | PROT_WRITE | PROT_EXEC);
  Value *flagsMmapFixed = builder.getInt64(MAP_FIXED | MAP_SHARED | MAP_POPULATE | MAP_FILE);

  Value *loadedFd = builder.CreateLoad(builder.getInt64Ty(), fd);


  BasicBlock *allocBlk = BasicBlock::Create(CTX, "alloc", F);
  BasicBlock *allocEndBlk = BasicBlock::Create(CTX, "alloc.end", F);

  Value *i = builder.CreateAlloca(builder.getInt64Ty(), nullptr, "i");
  builder.CreateStore(builder.getInt64(0), i);
  builder.CreateBr(allocBlk);
  builder.SetInsertPoint(allocBlk);

  Value* iVal = builder.CreateLoad(builder.getInt64Ty(), i);
  auto allocAddr = builder.CreateGEP(
    builder.getInt8Ty(), weirdMem, {iVal}, "alloc.addr", /*IsInBounds*/true
  );

  builder.CreateCall(mmapFunc, {
    allocAddr,
    builder.getInt64(WeirdRegisters::regOffset),
    protMmap,
    flagsMmapFixed,
    loadedFd
  });

  Value* nextI = builder.CreateAdd(iVal, builder.getInt64(WeirdRegisters::regOffset));
  builder.CreateStore(nextI, i);
  auto endCond = builder.CreateICmpUGE(nextI, builder.getInt64(size));
  builder.CreateCondBr(endCond, allocEndBlk, allocBlk);


  builder.SetInsertPoint(allocEndBlk);

  builder.CreateCall(closeFunc, {loadedFd});

  builder.CreateRetVoid();
}
void WeirdMachine::defineDeallocWeirdMemory(Function *F) {
  LLVMContext &CTX = flexo->getContext();

  // build entry block
  BasicBlock *EntryBlk = BasicBlock::Create(CTX, "entry", F);
  IRBuilder<> builder(EntryBlk);

  auto size = (flexo->register_count + WeirdRegisters::firstIdx) * WeirdRegisters::regOffset;
  auto WRegs = builder.CreateLoad(builder.getInt8PtrTy(), flexo->getGlobal("wregs"));

  // Start loop to unmap all individual pages
  BasicBlock *deallocBlk = BasicBlock::Create(CTX, "dealloc", F);
  BasicBlock *deallocEndBlk = BasicBlock::Create(CTX, "dealloc.end", F);

  Value *i = builder.CreateAlloca(builder.getInt64Ty(), nullptr, "i");
  builder.CreateStore(builder.getInt64(0), i);
  builder.CreateBr(deallocBlk);
  builder.SetInsertPoint(deallocBlk);

  Value* iVal = builder.CreateLoad(builder.getInt64Ty(), i);
  auto deallocAddr = builder.CreateGEP(
    builder.getInt8Ty(), WRegs, {iVal}, "dealloc.addr", /*IsInBounds*/true
  );
  
  builder.CreateCall(
    flexo->getFunc("munmap"), {deallocAddr, builder.getInt64(WeirdRegisters::regOffset)});

  Value* nextI = builder.CreateAdd(iVal, builder.getInt64(WeirdRegisters::regOffset));
  builder.CreateStore(nextI, i);
  auto endCond = builder.CreateICmpUGE(nextI, builder.getInt64(size));
  builder.CreateCondBr(endCond, deallocEndBlk, deallocBlk);

  // Loop ended, unmap whole memory range
  builder.SetInsertPoint(deallocEndBlk);

  builder.CreateCall(
    flexo->getFunc("munmap"), {
      WRegs,
      builder.getInt64(size)
    }
  );

  builder.CreateRetVoid();
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
