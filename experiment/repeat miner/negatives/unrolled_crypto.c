/* Unrolled ARX rounds. Eight identical noinline copies, plus one
 * function that inlines the same quarter-round eight times.
 * No weird-gate machinery. This is a hard negative for repetition.
 */
__attribute__((noinline, used)) static unsigned quarter(unsigned x, unsigned y, unsigned z, unsigned w) {
    x += y;
    w ^= x;
    w = (w << 16) | (w >> 16);
    z += w;
    y ^= z;
    y = (y << 12) | (y >> 20);
    x += y;
    w ^= x;
    w = (w << 8) | (w >> 24);
    z += w;
    y ^= z;
    y = (y << 7) | (y >> 25);
    return x ^ y ^ z ^ w;
}

#define ROUND(name) \
    __attribute__((noinline, used)) unsigned name(unsigned x, unsigned y, unsigned z, unsigned w) { \
        return quarter(x, y, z, w); \
    }

ROUND(r0)
ROUND(r1)
ROUND(r2)
ROUND(r3)
ROUND(r4)
ROUND(r5)
ROUND(r6)
ROUND(r7)

__attribute__((noinline, used)) unsigned unrolled(unsigned x, unsigned y, unsigned z, unsigned w) {
    unsigned a, b, c, d, e, f, g, h;
    a = quarter(x, y, z, w);
    b = quarter(a, y, z, w);
    c = quarter(b, y, z, w);
    d = quarter(c, y, z, w);
    e = quarter(d, y, z, w);
    f = quarter(e, y, z, w);
    g = quarter(f, y, z, w);
    h = quarter(g, y, z, w);
    return a ^ b ^ c ^ d ^ e ^ f ^ g ^ h;
}
