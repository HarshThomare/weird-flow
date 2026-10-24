/* Compiler-shaped TAE program.
   WM::write and WM::readTransient are the real inlines from
   third_party/tae/include/WeirdStates/IndirectJmp.h.
   create_window is the ret-hijack from TransientWindows/RetBased.cpp,
   provided by substrate.S.

   This is the cross-function shape of examples/search.cpp:
   one function trains BTB slots, a different function reads them and
   writes a result slot, and the first function reads that slot back.
   Slot ids 0, 1, and 2 are constants. driver_opaque reads
   (opaque_zero() + 5), which should stay partial. driver_neg_c and
   weird_neg_c share no slot.

   The cache-timing loop inside WM::read is not linked. readTransient
   is the BTB operand of that read (see btbToCache in IndirectJmp.cpp). */

#include "WeirdStates/IndirectJmp.h"

extern "C" {
extern int opaque_zero(void);
extern void create_window(void* dest);
unsigned weird_c(unsigned dependency);
unsigned weird_neg_c(unsigned dependency);
}

static inline __attribute__((always_inline)) void write_slot(unsigned id, unsigned val) {
  (void)WM::write(static_cast<uint16_t>(id), static_cast<uint16_t>(val));
}

static inline __attribute__((always_inline)) unsigned read_slot(unsigned id) {
  return WM::readTransient(static_cast<uint16_t>(id), /*delayed=*/1);
}

extern "C" __attribute__((noinline)) unsigned driver_c(unsigned a, unsigned b) {
  write_slot(0, a & 0xFFFF);
  write_slot(1, b & 0xFFFF);
  (void)weird_c(0);
  unsigned first = read_slot(2);
  unsigned second = read_slot(2);
  return first + second;
}

extern "C" __attribute__((noinline)) unsigned weird_c(unsigned dependency) {
  unsigned first = 0, second = 0, other = 0, sum;
  uint64_t delay = dependency;
  /* Label stays on this instruction; a C &&label was moved by GCC. */
  asm volatile(
      "lea end_weird_c(%%rip), %%rdi\n"
      "call create_window\n" ::: "rdi", "memory");
  asm volatile(
      "xor %%rax, %%rax\n"
      "movq %q[delay], %%rbx\n"
      "call jmpreg0\n"
      "movl %%eax, %k[got]\n"
      : [got] "=&r"(first)
      : [delay] "r"(delay)
      : "rax", "rbx", "memory");
  asm volatile(
      "xor %%rax, %%rax\n"
      "movq %q[delay], %%rbx\n"
      "call jmpreg0\n"
      "movl %%eax, %k[got]\n"
      : [got] "=&r"(second)
      : [delay] "r"(delay)
      : "rax", "rbx", "memory");
  asm volatile(
      "xor %%rax, %%rax\n"
      "movq %q[delay], %%rbx\n"
      "call jmpreg1\n"
      "movl %%eax, %k[got]\n"
      : [got] "=&r"(other)
      : [delay] "r"(delay)
      : "rax", "rbx", "memory");
  sum = (second + other) & 0xFFFF;
  uint8_t* tbl = reinterpret_cast<uint8_t*>(decode_table);
  WR_WRITE(2, tbl + sum * TBL_STRIDE);
  asm volatile("end_weird_c:\n nop\n" ::: "memory");
  return sum;
}

extern "C" __attribute__((noinline)) unsigned driver_neg_c(unsigned a) {
  write_slot(0, a & 0xFFFF);
  return weird_neg_c(a);
}

extern "C" __attribute__((noinline)) unsigned weird_neg_c(unsigned dependency) {
  unsigned got = 0;
  uint64_t delay = dependency;
  asm volatile(
      "lea end_weird_neg_c(%%rip), %%rdi\n"
      "call create_window\n" ::: "rdi", "memory");
  asm volatile(
      "xor %%rax, %%rax\n"
      "movq %q[delay], %%rbx\n"
      "call jmpreg7\n"
      "movl %%eax, %k[got]\n"
      : [got] "=&r"(got)
      : [delay] "r"(delay)
      : "rax", "rbx", "memory");
  asm volatile("end_weird_neg_c:\n nop\n" ::: "memory");
  return got;
}

extern "C" __attribute__((noinline)) unsigned driver_opaque(unsigned val) {
  uint8_t* tbl = reinterpret_cast<uint8_t*>(decode_table);
  WR_WRITE(5, tbl + (val & 0xFFFF) * TBL_STRIDE);
  unsigned idx = static_cast<unsigned>(opaque_zero()) + 5;
  return read_slot(idx);
}
