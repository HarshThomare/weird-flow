//========================================================================
// FILE:
//    CacheChannel.h
//
// DESCRIPTION:
//    Manage the cache residency side-channel.
//
// License: MIT
//========================================================================
#ifndef CACHE_CHANNEL_H
#define CACHE_CHANNEL_H

#include <cstdint>
#include <x86intrin.h>

namespace WM {
  // layout of the cache lines
  const int cacheOffset = 64;
  const int cacheStride = 448;

  // flush `count` cache lines at `addr`
  inline void flush(uint8_t* addr, int count) {
    for (int i = 0; i < count; i++) {
      _mm_clflush(addr + i * cacheStride + cacheOffset);
    }
  }

  // get the address of a cache line
  inline uint8_t* getAddr(uint8_t* ptr, int idx) {
    return ptr + idx * cacheStride + cacheOffset;
  }

  // fetch the addr into the cache
  inline void access(uint8_t* addr) {
    asm volatile("movb (%0), %%al\n" :: "r" (addr) : "rax");
  }

  // use RDTSCP to time the access latency
  // `ptr` has a cache hit if latency < 80 cycles
  bool inline inCache(uint8_t* ptr) {
    uint64_t clk;
    asm volatile (
      "rdtscp\n\t"
      "shl $32, %%rdx\n\t"
      "mov %%rdx, %%rsi\n\t"
      "or %%eax, %%esi\n\t"
      "mov %1, %%al\n\t"
      "rdtscp\n\t"
      "shl $32, %%rdx\n\t"
      "or %%eax, %%edx\n\t"
      "sub %%rsi, %%rdx\n\t"
      "mov %%rdx, %0\n\t"
      : "=r" (clk)
      : "m" (ptr[0])
      : "rcx", "rdx", "rsi", "eax"
    );
    return clk < 80;
  }
}

#endif
