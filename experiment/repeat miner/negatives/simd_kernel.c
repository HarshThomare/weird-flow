/* Identical AVX2 saxpy kernels. A hard negative: repetition without a weird gate. */
#include <immintrin.h>

#define SAXPY(name) \
    __attribute__((noinline, used)) void name(float *a, const float *b, int n) { \
        int i; \
        for (i = 0; i + 8 <= n; i += 8) { \
            __m256 x = _mm256_loadu_ps(a + i); \
            __m256 y = _mm256_loadu_ps(b + i); \
            __m256 s = _mm256_add_ps(x, y); \
            s = _mm256_mul_ps(s, y); \
            _mm256_storeu_ps(a + i, s); \
        } \
    }

SAXPY(k0)
SAXPY(k1)
SAXPY(k2)
SAXPY(k3)
SAXPY(k4)
SAXPY(k5)
