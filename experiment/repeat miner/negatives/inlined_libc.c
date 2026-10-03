/* Small constant-size libc calls. At -O3 the compiler inlines memcpy,
 * memset, and strlen; those bodies then repeat across functions.
 */
#include <string.h>

#define MEM(name, off) \
    __attribute__((noinline, used)) int name(char *d, const char *s) { \
        memcpy(d, s, 32); \
        memset(d + 8, off, 16); \
        return (int)strlen(s); \
    }

MEM(m0, 0)
MEM(m1, 1)
MEM(m2, 2)
MEM(m3, 3)
MEM(m4, 4)
MEM(m5, 5)
