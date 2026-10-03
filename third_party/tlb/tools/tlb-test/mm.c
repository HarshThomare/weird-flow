#include <stdlib.h>
#include <stdio.h>
#include <assert.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/mman.h>

#include "mm.h"

extern uintptr_t temporary_memory[TEMP_MEMORY_SIZE];
extern uintptr_t available_temporary_memory;

static uintptr_t enter_number = TEMP_MEMORY_SIZE;

void* allocate_pages(uint64_t n, int fd, uint64_t page, uint64_t offset) {
	assert(offset >= page);
	// reserve space
	void *base = mmap(NULL, n * (offset), PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if(base == MAP_FAILED) {
		perror("mmap");
		exit(1);
	}
	void *ret;
	for (uint64_t i = 0; i < n; i++) {
		ret = mmap((void *) base + (i*(offset)), page, PROT_READ|PROT_WRITE|PROT_EXEC, MAP_FIXED|MAP_SHARED|MAP_POPULATE|MAP_FILE, fd, 0);
		if (ret == MAP_FAILED) {
			perror("mmap");
			exit(1);
		}
		memset(ret, 0, page);
	}
	return base;
}

void random_shuffle(uintptr_t memory, uintptr_t *addresses, size_t n, uint64_t offset) {
	// Fill with addresses
	for (size_t i = 0; i < n; i++) {
		addresses[i] = memory + (i * offset);
	}
	// Fisher-Yates shuffle algorithm
	for (size_t i = n - 1; i > 0; i--) {
		size_t j = rand() % (i + 1);
		void *temp = addresses[i];
		addresses[i] = addresses[j];
		addresses[j] = temp;
	}
}

uintptr_t get_temporary_memory() {
	if (available_temporary_memory == 0) {
		printf("Out of temporary memory!\n");
		while(1) {}
		// return 0;
	}
	return temporary_memory[--available_temporary_memory];
		
}

void return_temporary_memory(uintptr_t offset) {
	temporary_memory[available_temporary_memory++] = offset; 
}
