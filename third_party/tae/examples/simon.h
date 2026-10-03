#ifndef SIMON_H
#define SIMON_H

/*
  Macros for Simon encryption
*/

#define z0 0b10110011100001101010010001011111
#define ROUNDS 32
#define ROR(x, r) ((x >> r) | (x << (16 - r)))
#define ROL(x, r) ((x << r) | (x >> (16 - r)))

#define SIMON_ROUND(x, y, k) \
  tmp = (ROL(x, 1) & ROL(x, 8)) ^ y ^ ROL(x, 2); \
  y = x; \
  x = tmp ^ k;

#define NEXT_KEY(k0, k1, k2, k3, z0, i) \
  tmp2 = k3; \
  tmp = ROR(k3, 3) ^ k1; \
  tmp ^= ROR(tmp, 1); \
  k3 = ~k0 ^ tmp ^ 3 ^ ((z0 >> (i - 4)) & 1); \
  k0 = k1; \
  k1 = k2; \
  k2 = tmp2;

#define LOAD_INPUT(id1, id2, id3, id4, id5, id6) \
  asm volatile( \
    WR_READ_INIT(target) \
    WR_READ(id1) \
    "mov %%rax, %[i0]\n" \
    WR_READ(id2) \
    "mov %%rax, %[i1]\n" \
    WR_READ(id3) \
    "mov %%rax, %[i2]\n" \
    WR_READ(id4) \
    "mov %%rax, %[i3]\n" \
    WR_READ(id5) \
    "mov %%rax, %[i4]\n" \
    WR_READ(id6) \
    "mov %%rax, %[i5]\n" \
    : [i0]"=r"(i0), [i1]"=r"(i1), [i2]"=r"(i2), \
    [i3]"=r"(i3), [i4]"=r"(i4), [i5]"=r"(i5) \
    : [target]"r"(delay) : "rax", "rbx" \
  ); \
  x  = i0 & 0xFFFF; \
  y  = i1 & 0xFFFF; \
  k0 = i5 & 0xFFFF; \
  k1 = i4 & 0xFFFF; \
  k2 = i3 & 0xFFFF; \
  k3 = i2 & 0xFFFF;

#define WRITE_OUTPUT(id1, id2, id3, id4, id5, id6) \
  uint8_t* tblPtr = (uint8_t*)decode_table; \
  WR_WRITE(id1, tblPtr + x * TBL_STRIDE); \
  WM::nopDelay(4); \
  WR_WRITE(id2, tblPtr + y * TBL_STRIDE); \
  WM::nopDelay(4); \
  WR_WRITE(id3, tblPtr + k3 * TBL_STRIDE); \
  WM::nopDelay(4); \
  WR_WRITE(id4, tblPtr + k2 * TBL_STRIDE); \
  WM::nopDelay(4); \
  WR_WRITE(id5, tblPtr + k1 * TBL_STRIDE); \
  WM::nopDelay(4); \
  WR_WRITE(id6, tblPtr + k0 * TBL_STRIDE);

#define GATE_PROLOGUE \
  uint8_t slow = delays[delays[WM::longDelay(dependency, 1)] + 3072]; \
  uint64_t i0, i1, i2, i3, i4, i5; \
  uint16_t x, y, k0, k1, k2, k3, tmp, tmp2; \
  WM::createWindow(((char*)&&end) + slow); \
  uint64_t delay = delays[delays[slow + 2048] + 1024];

#define GATE_EPILOGUE \
  WM::nopDelay(65536); \
  end: asm volatile("nop"); \
  return slow;

#define SIMON_FOUR_ROUNDS(start) \
  _Pragma("unroll") \
  for (unsigned i = 0; i < 4; ++i) { \
    NEXT_KEY(k0, k1, k2, k3, z0, i + start); \
    SIMON_ROUND(x, y, k3); \
  }

#endif
