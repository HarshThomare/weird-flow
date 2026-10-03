#include <stdint.h>

#define TEMP_MEMORY_SIZE 200000

void* allocate_pages(uint64_t n, int fd, uint64_t page, uint64_t offset);
void random_shuffle(uintptr_t memory, uintptr_t *addresses, size_t n, uint64_t offset);
uintptr_t get_temporary_memory();
void return_temporary_memory(const uintptr_t offset);
