//========================================================================
// FILE:
//    IndirectJmp.cpp
//
// DESCRIPTION:
//    Store data using indirect jumps (BTB in the microarchitecture).
//
// License: MIT
//========================================================================
#include <cassert>
#include <cstdlib>
#include <sys/mman.h>
#include <x86intrin.h>
#include <cstdio>
#include "WeirdStates/IndirectJmp.h"
#include "Util.h"
#include "TransientWindows/RetBased.h"
#include "WeirdStates/CacheChannel.h"

#define REG_COUNT 1024
#define REG_BYTES 2
#define SIDE_CHANNEL_SIZE 16384

uint8_t* sideChannel;
// extern void* end;

namespace WM {

// generate a random history of recent branches
int randHistory() {
  return setHistory(rand());
}

// set the history of recent branches
int setHistory(int val) {
  int out = val;
  #pragma clang loop unroll(full)
  for (int i = 0; i < 32; i++) {
    asm volatile(
      // read 2 bits at a time
      // jump to different locations based on the 2-bit value
      "cmp $3, %[val]\n"
      "jz .+16\n"
      "cmp $2, %[val]\n"
      "jz .+12\n"
      "cmp $1, %[val]\n"
      "jz .+4\n"
      "jmp .+3\n"
      "nop\n"
      "nop\n"
      "nop\n"
      "nop\n"
      "nop\n"
      "nop\n"
      :: [val]"r"(val & 3)
      :
    );
    val >>= 2;
  }
  return out;
}

// allocate memory for the cache side channel
void allocate() {
  int protRW = PROT_READ | PROT_WRITE;

  sideChannel = (uint8_t*)mmap(
    nullptr, SIDE_CHANNEL_SIZE, protRW, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0
  );
  assert(sideChannel != MAP_FAILED && "Failed to allocate memory for side channel");

  // init the cache side channel
  for (int i = 0; i < SIDE_CHANNEL_SIZE; i++) sideChannel[i] = 0;
  for (int i = 63; i < SIDE_CHANNEL_SIZE; i += 4096) sideChannel[i] = 123;
}

// deallocate memory for the cache side channel
void deallocate() {
  munmap(sideChannel, SIDE_CHANNEL_SIZE);
  sideChannel = nullptr;
}

// update the votes for the value of a register
uint64_t updateVotes(uint64_t votes, unsigned got) {
  // the upper 16 bits of the votes are values, the other bits are counts
  const uint64_t mask = (((uint64_t)1 << 48) - 1);
  uint64_t newVotes = 0, values = votes >> 48, counts = votes & mask;

  // For each chunk (2 bits) of the register, there are 8 bits in the votes.
  // 6 bits for the count, and 2 bits for the value.
  // Here, if the new got value is not error, we increment the count if the value
  // is the same as the previous value.
  // If the new got value is different, we decrease the count.
  // If the count is 0, we update the value.
  for (int i = 0; i < 8; i++) {
    if (got >> (16 + i) & 1) continue;
    uint64_t newVal = (got >> (2 * i)) & 3;
    uint64_t val = (values >> (2 * i)) & 3;
    uint64_t count = (counts >> (6 * i)) & 0x3F;
    if (count == 0) {
      val = newVal;
      count = 1;
    } else if (newVal == val && count < 0x3F) {
      count += 1;
    } else if (newVal != val) {
      count -= 1;
    }
    newVotes |= (count << (6 * i)) + (val << (2 * i + 48));
  }
  return newVotes;
}

// merge the votes and output the results
unsigned mergeVotes(uint64_t votes) {
  unsigned got = votes >> 48;
  const uint64_t mask = (((uint64_t)1 << 48) - 1);
  uint64_t counts = votes & mask;
  for (int i = 0; i < 8; i++) {
    unsigned count = (counts >> (6 * i)) & 0x3F;
    if (!count) {
      got |= 1 << (i + 16);
    }
  }
  return got;
}

// check if any count is zero
bool hasEmptyCount(uint64_t votes) {
  const uint64_t mask = (((uint64_t)1 << 48) - 1);
  uint64_t counts = votes & mask;
  for (int i = 0; i < 8; i++) {
    if ((counts >> (6 * i)) & 0x3F) continue;
    return true;
  }
  return false;
}

// read from jmpreg using a side channel
// the lower 16 bits of the return value are the bits of the register
// the upper 16 bits of the return value are the error detection bits
unsigned read(uint16_t regId, int retry) {
  unsigned got = 0;
  uint64_t votes = 0;

  for (int i = 0; i < retry; i++) {
    // make sure the previous byte is decoded
    bool smallDelay = delay(got, 1);
    sideChannel += smallDelay;
    got = decoder(regId + smallDelay);

    if (retry == 1) return got;
    votes = updateVotes(votes, got);
    if (!hasEmptyCount(votes)) break;
  }

  return mergeVotes(votes);
}

// decode a byte from jmpreg using cache side channel
unsigned decoder(uint16_t regId) {
  // flush side channel
  WM::fence();
  flush(sideChannel, 36);
  bool smallDelay = delay(regId, 1);
  int halt = setHistory(smallDelay + rand());
  halt = setHistory(halt + rand());
  smallDelay = delay(halt, 1);

  WM::fence();
  sideChannel += smallDelay;
  unsigned got = btbToCache(regId + smallDelay);
  WM::fence();

  // read from side channel
  unsigned result = 0, lines = 0, offset = rand() % 32;
  sideChannel += delay(got, 1);
  #pragma clang loop unroll(full)
  for (int i = 0; i < 32; i++) {
    const int idx = (i * 17 + offset) % 32;
    uint8_t* addr = getAddr(sideChannel, idx + 1);
    lines |= inCache(addr) << idx;
  }
  for (int i = 0; i < 8; i++) {
    unsigned got = (lines >> (i * 4)) & 0xF;
    switch (got) {
      case 1: break;
      case 2: result |= 1 << (i * 2); break;
      case 4: result |= 2 << (i * 2); break;
      case 8: result |= 3 << (i * 2); break;
      default: result |= 1 << (i + 16); break;
    }
  }
  return result;
}

// decode a byte from jmpreg using cache side channel (done in transient execution).
unsigned btbToCache(uint16_t regId) {
  uint8_t* windowDelay = getAddr(sideChannel, 0);
  uint8_t* targetDelay1 = getAddr(sideChannel, 33);
  uint8_t* targetDelay2 = getAddr(sideChannel, 34);

  // transient execution starts
  uint8_t slow = windowDelay[longDelay(regId, 1)];
  createWindow(((char*)&&end) + slow);

  // read from jmpreg
  unsigned val = readTransient(regId, targetDelay2[targetDelay1[slow]]);

  for (int j = 0; j < 8; j++) {
    uint8_t* addr = getAddr(sideChannel, j * 4 + ((val >> (2 * j)) & 3) + 1);
    access(addr);
  }
  WM::nopDelay(65536);

  // transient execution ends
  end: asm volatile("nop");
  return slow;
}

}

// Below is the allocation of the BTB weird registers. Section 4.2 and 4.3 of our
// paper explain how they work in details.

// BTB weird registers (1024 indirect jumps)
__attribute__((aligned(32)))
void jmpreg0() {
  asm volatile (
    // macro to generate the indirect jumps
    ".macro GEN_JMP\n"
    "    .global jmpreg\\@\n"
    "    .align 32\n"
    "    jmpreg\\@:\n"
    "        jmp *%rbx\n"
    ".endm\n"
    ".rept 1024\n"
    "    GEN_JMP\n"
    ".endr\n"
  );
}

// the decode table with 65536 entries (see Section 4.3)
__attribute__((aligned(4096)))
void decode_table() {
  asm volatile (
    // decode table
    ".global decode_table\n"
    ".align 4096\n"
    "decode_table:\n"
    "value=0\n"
    ".rept 65536\n"
    "    movw $value,%ax\n"
    "    ret\n"
    "value=value+1\n"
    ".endr\n"
  );
}
