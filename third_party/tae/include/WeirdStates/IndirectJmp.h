//========================================================================
// FILE:
//    IndirectJmp.h
//
// DESCRIPTION:
//    Store data using indirect jumps (BTB in the microarchitecture).
//
// License: MIT
//========================================================================
#ifndef INDIRECT_JMP_H
#define INDIRECT_JMP_H

#include <cstdint>

#define ALIGN 32
#define TBL_STRIDE 5

extern uint8_t* jmpreg;
extern uint8_t* decodeTbl;
void jmpreg0();
void decode_table();

/* low-level read and write macros */
// clear rax and add the target to bl
#define WR_READ_INIT(target) "xor %%rax, %%rax\nmov %[" #target "], %%rbx\n"

// read a WR
#define WR_READ(id) "call jmpreg" #id "\n"

// read 2 WRs and put the results in eax
#define WR_READ_2(id1, id2) WR_READ(id1) "shl $16, %%rax\n" WR_READ(id2)

// read 4 WRs and put the results in rax
#define WR_READ_4(id1, id2, id3, id4) \
  WR_READ_2(id1, id2) \
  "shl $16, %%rax\n" \
  WR_READ_2(id3, id4)

// write `val` to WR (`id` is static)
#define WR_WRITE(id, val) asm volatile( \
  "mov %[target], %%rbx\n" \
  "call jmpreg" #id "\n" \
  :: [target]"r"(val) \
  : "rax", "rbx")

namespace WM {
  int randHistory();
  int setHistory(int);
  void allocate();
  void deallocate();
  unsigned read(uint16_t regId, int retry = 1);
  unsigned decoder(uint16_t regId);
  unsigned btbToCache(uint16_t regId);

  // read WR in transient execution
  // the value of `delayed` should NOT be ready before transient execution ends
  inline unsigned readTransient(uint16_t regId, uint16_t delayed) {
    uint8_t* regPtr = (uint8_t*)jmpreg0 + regId * ALIGN;
    uint8_t* tblPtr = (uint8_t*)nullptr + delayed;
    unsigned got;
    asm volatile(
      WR_READ_INIT(tblPtr)
      "call *%[regPtr]\n"
      "mov %%eax, %[got]\n"
      : [got] "=r" (got)
      : [tblPtr] "r" (tblPtr), [regPtr] "r" (regPtr)
      : "rax", "rbx"
    );
    return got;
  }

  // write `val` to WR (`regId` can be dynamic)
  inline unsigned write(uint16_t regId, uint16_t val) {
    uint8_t* regPtr = (uint8_t*)jmpreg0 + regId * ALIGN;
    uint8_t* tblPtr = (uint8_t*)decode_table + val * TBL_STRIDE;
    unsigned got;
    asm volatile(
      "mov %[tblPtr], %%rbx\n"
      "call *%[regPtr]\n"
      "mov %%eax, %[got]\n"
      : [got] "=r" (got)
      : [tblPtr] "r" (tblPtr), [regPtr] "r" (regPtr)
      : "rax", "rbx"
    );
    return got;
  }
}

#endif
