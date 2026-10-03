/* Portable stand-in for a repeated gate. Flexo and TAE gadgets are x86
 * cache/BTB code and do not cross-compile. These eight copies are the
 * ISA-transfer positive: the same body, no inline asm, no libc.
 */
#define GATE(name) \
    __attribute__((noinline, used)) int name(int x, int y) { \
        int a = (x ^ y) + 13; \
        int b = a * 3 + (x >> 2); \
        int c = b ^ (a << 1); \
        int d = c + y * 5; \
        return d ^ (a >> 1); \
    }

GATE(g0)
GATE(g1)
GATE(g2)
GATE(g3)
GATE(g4)
GATE(g5)
GATE(g6)
GATE(g7)
