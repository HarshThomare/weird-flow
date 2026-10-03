#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <time.h>
#include <errno.h>
#include <assert.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <immintrin.h>
#include <sys/mman.h>

#include "consts.h"
#include "mm.h"
#include "math_util.h"
#include "tlb_utils.h"
#include "util.h"

extern void window_call_ret();

uint64_t RDTSC_THRESHOLD_TLB = 0;

#define N_ADDRESSES 14
#if N_ADDRESSES == 8
		#define ACCESS_FUNC access_8
#elif N_ADDRESSES == 10
		#define ACCESS_FUNC access_10
#elif N_ADDRESSES == 12
		#define ACCESS_FUNC access_12
#elif N_ADDRESSES == 14
		#define ACCESS_FUNC access_14
#else
		#error "Unsupported value for N"
#endif

// ============ Access Functions =====================

__attribute__((always_inline)) inline
void access_8(uint64_t **addresses) {
	asm volatile(
			"mov %0, %%rax\n\t"
			"mov %1, %%rcx\n\t"
			"mov %2, %%rdx\n\t"
			"mov %3, %%rsi\n\t"
			"mov %4, %%r8\n\t"
			"mov %5, %%r9\n\t"
			"mov %6, %%r10\n\t"
			"mov %7, %%r11\n\t"
			:
			: "m"(addresses[0]), "m"(addresses[1]), "m"(addresses[2]), "m"(addresses[3]), "m"(addresses[4]), "m"(addresses[5]), "m"(addresses[6]), "m"(addresses[7])
			: "%rax", "%rcx", "%rdx", "%rsi", "%r8", "%r9", "%r10", "%r11");

	asm volatile(
			"mov (%rax), %rax\n\t"
			"mov (%rcx), %rcx\n\t"
			"mov (%rdx), %rdx\n\t"
			"mov (%rsi), %rsi\n\t"
			"mov (%r8), %r8\n\t"
			"mov (%r9), %r9\n\t"
			"mov (%r10), %r10\n\t"
			"mov (%r11), %r11\n\t"
		);
}

__attribute__((always_inline)) inline
void access_10(uint64_t **addresses) {
	asm volatile(
			"mov %0, %%rax\n\t"
			"mov %1, %%rcx\n\t"
			"mov %2, %%rdx\n\t"
			"mov %3, %%rsi\n\t"
			"mov %4, %%rdi\n\t"
			"mov %5, %%r8\n\t"
			"mov %6, %%r9\n\t"
			"mov %7, %%r10\n\t"
			"mov %8, %%r11\n\t"
			"mov %9, %%rbx\n\t"
			:
			: "m"(addresses[0]), "m"(addresses[1]), "m"(addresses[2]), "m"(addresses[3]), "m"(addresses[4]), "m"(addresses[5]), "m"(addresses[6]), "m"(addresses[7]), "m"(addresses[8]), "m"(addresses[9])
			: "%rax", "%rcx", "%rdx", "%rsi", "%rdi", "%r8", "%r9", "%r10", "%r11", "%rbx");

	asm volatile(
			"mov (%rax), %rax\n\t"
			"mov (%rcx), %rcx\n\t"
			"mov (%rdx), %rdx\n\t"
			"mov (%rsi), %rsi\n\t"
			"mov (%rdi), %rdi\n\t"
			"mov (%r8), %r8\n\t"
			"mov (%r9), %r9\n\t"
			"mov (%r10), %r10\n\t"
			"mov (%r11), %r11\n\t"
			"mov (%rbx), %rbx\n\t"
		);
}

__attribute__((always_inline)) inline
void access_12(uint64_t **addresses) {
	asm volatile(
			"mov %0, %%rax\n\t"
			"mov %1, %%rcx\n\t"
			"mov %2, %%rdx\n\t"
			"mov %3, %%rsi\n\t"
			"mov %4, %%rdi\n\t"
			"mov %5, %%r8\n\t"
			"mov %6, %%r9\n\t"
			"mov %7, %%r10\n\t"
			"mov %8, %%r11\n\t"
			"mov %9, %%rbx\n\t"
			"mov %10, %%r12\n\t"
			"mov %11, %%r13\n\t"
			:
			: "m"(addresses[0]), "m"(addresses[1]), "m"(addresses[2]), "m"(addresses[3]), "m"(addresses[4]), "m"(addresses[5]), "m"(addresses[6]), "m"(addresses[7]), "m"(addresses[8]), "m"(addresses[9]), "m"(addresses[10]), "m"(addresses[11])
			: "%rax", "%rcx", "%rdx", "%rsi", "%rdi", "%r8", "%r9", "%r10", "%r11", "%rbx", "%r12", "%r13");

	asm volatile(
			"mov (%rax), %rax\n\t"
			"mov (%rcx), %rcx\n\t"
			"mov (%rdx), %rdx\n\t"
			"mov (%rsi), %rsi\n\t"
			"mov (%rdi), %rdi\n\t"
			"mov (%r8), %r8\n\t"
			"mov (%r9), %r9\n\t"
			"mov (%r10), %r10\n\t"
			"mov (%r11), %r11\n\t"
			"mov (%rbx), %rbx\n\t"
			"mov (%r12), %r12\n\t"
			"mov (%r13), %r13\n\t"
		);
}

__attribute__((always_inline)) inline
void access_14(uint64_t **addresses) {
	asm volatile(
			"mov %0, %%rax\n\t"
			"mov %1, %%rcx\n\t"
			"mov %2, %%rdx\n\t"
			"mov %3, %%rsi\n\t"
			"mov %4, %%rdi\n\t"
			"mov %5, %%r8\n\t"
			"mov %6, %%r9\n\t"
			"mov %7, %%r10\n\t"
			"mov %8, %%r11\n\t"
			"mov %9, %%rbx\n\t"
			"mov %10, %%r12\n\t"
			"mov %11, %%r13\n\t"
			"mov %12, %%r14\n\t"
			"mov %13, %%r15\n\t"
			:
			: "m"(addresses[0]), "m"(addresses[1]), "m"(addresses[2]), "m"(addresses[3]), "m"(addresses[4]), "m"(addresses[5]), "m"(addresses[6]), "m"(addresses[7]), "m"(addresses[8]), "m"(addresses[9]), "m"(addresses[10]), "m"(addresses[11]), "m"(addresses[12]), "m"(addresses[13])
			: "%rax", "%rcx", "%rdx", "%rsi", "%rdi", "%r8", "%r9", "%r10", "%r11", "%rbx", "%r12", "%r13", "%r14", "%r15");

	asm volatile(
			"mov (%rax), %rax\n\t"
			"mov (%rcx), %rcx\n\t"
			"mov (%rdx), %rdx\n\t"
			"mov (%rsi), %rsi\n\t"
			"mov (%rdi), %rdi\n\t"
			"mov (%r8), %r8\n\t"
			"mov (%r9), %r9\n\t"
			"mov (%r10), %r10\n\t"
			"mov (%r11), %r11\n\t"
			"mov (%rbx), %rbx\n\t"
			"mov (%r12), %r12\n\t"
			"mov (%r13), %r13\n\t"
			"mov (%r14), %r14\n\t"
			"mov (%r15), %r15\n\t");
}

// ============ Helper ===============================

uintptr_t read_addr(uintptr_t addr, uintptr_t *output, uintptr_t trash) {
	uint64_t diff = timer(addr);
	*output = diff <= RDTSC_THRESHOLD_TLB;
	// printf("%ld\n", (end-start));

	return trash;
}
uintptr_t read_addr_bool(uintptr_t addr, bool *output, uintptr_t trash) {
	uint64_t diff = timer(addr);
	*output = diff <= RDTSC_THRESHOLD_TLB;
	// printf("%ld\n", (end-start));

	return trash;
}

// =========== Window Helper =========================

/**
 * Tests how many addresses were loaded
 */
int many_loaded(uint64_t *addresses, bool *outs, uint32_t n, uint64_t trash) {
	for (uint32_t i = 0; i < n; i++) {
		trash = read_addr_bool(addresses[i], &outs[i], trash);
	}
	return trash;
}

/**
 * Tests how many addresses were loaded, skipping each 2nd
 */
int many_loaded_2nd(uint64_t *addresses, bool *outs, uint32_t n, uint64_t trash) {
	for (uint32_t i = 1; i < n; i+=2) {
		trash = read_addr_bool(addresses[i], &outs[i/2], trash);
	}
	return trash;
}

/**
 * Accesses addresses inside transient window
 */
int transient_window_addresses(uint64_t *addresses) {
	window_call_ret();
	ACCESS_FUNC(addresses);

	asm volatile(
			".rept 512\n\t"
			"nop\n\t"
			".endr");
	return;
}

/**
 * Test the window sizes and gets the median value over iterations
 */
uint64_t get_size_addresses(uint64_t iterations, bool only_2nd, bool print) {
	uint64_t maxSize = 0;
	uint64_t ***addresses = calloc(iterations, sizeof(uint64_t *));
	bool **out = calloc(iterations, sizeof(bool*));
	uint64_t *sizes = calloc(iterations, sizeof(uint64_t));
	uint64_t trash = 0;
	uint64_t *opt = get_temporary_memory();

	/**
	 * Get addresses that shall be accessed each round
	 */
	for (uint64_t i = 0; i < iterations; i++) {
		addresses[i] = calloc(N_ADDRESSES, sizeof(uint64_t));
		out[i] = calloc(N_ADDRESSES, sizeof(bool));
		for (uint32_t j = 0; j < N_ADDRESSES; j++)
		{
			uint64_t *addr = get_temporary_memory();
			addresses[i][j] = addr;
		}
	}
	mfence();
	lfence();

	for (int64_t i = iterations-1; i >= 0; i--) {
		*opt;
		for (uint32_t j = 0; j < N_ADDRESSES; j += 1) {
			flush_tlb_addr_no_pt_caches(addresses[i][j]);
		}
		mfence();
		lfence();
		if (only_2nd) {
			for (uint32_t j = 0; j < N_ADDRESSES; j += 2) {
				*addresses[i][j];
			}
		}
		*opt;
		mfence();
		lfence();
		transient_window_addresses(addresses[i]);
		mfence();
		lfence();
		many_loaded(addresses[i], out[i], N_ADDRESSES, trash);
		mfence();
		lfence();
	}
	
	for (uint64_t i = 0; i < iterations; i++) {
		for (uint32_t j = 0; j < N_ADDRESSES; j++) {
			if (out[i][j]) {
				sizes[i]++;
			}
		}
	}
	arr_info_t info = arr_info(iterations, sizes, print, "Sizes");
	mfence();
	lfence();
	return_temporary_memory(opt);
	for (uint64_t i = 0; i < iterations; i++) {
		for (uint32_t j = 0; j < N_ADDRESSES; j++) {
			flush_tlb_addr(addresses[i][j]);
			return_temporary_memory(addresses[i][j]);
		}
		free(addresses[i]);
		free(out[i]);
	}
	free(addresses);
	free(out);
	free(sizes);
	return info.median;
}


uint64_t _measure_window_call_ret_cycles() {
	uint64_t _p;
	volatile uint64_t t;

	mfence();
	lfence();
	t = rdtscp();
	window_call_ret();

	asm volatile(
			".rept 512\n\t"
			"nop\n\t"
			".endr");
	t = rdtscp() - t;
	return t;
}

/**
 * Measure cycles the window_call_ret method needs
 */
uint64_t measure_window_call_ret_cycles(uint64_t iterations, bool print) {
	uint64_t *t = calloc(iterations, sizeof(uint64_t));

	mfence();
	lfence();
	for (int i = 0; i < iterations; i++) {
		t[i] = _measure_window_call_ret_cycles();
		mfence();
		lfence();
	}

	arr_info_t info = arr_info(iterations, t, print, "Cycles mod_ret_addr:\n\t");
	return info.median;
}

// ============== Globals ============================

void *memory = NULL;

uintptr_t temporary_memory[TEMP_MEMORY_SIZE];
uintptr_t available_temporary_memory;

/**
 * Gets the threshold by the ENV variable `THRESHOLD`
 */
void set_tlb_threshold() {
	mfence();
	lfence();
	uint64_t THRESHOLD;
	char *THRESHOLD_STR = getenv("THRESHOLD");
	if (THRESHOLD_STR != NULL) {
		THRESHOLD = atoi(THRESHOLD_STR);
	} else {
		printf("Please give threshold via ENV `THRESHOLD=...`\n");
		exit(1);
	}
	RDTSC_THRESHOLD_TLB = THRESHOLD;
	printf("Set threshold to %ld\n", RDTSC_THRESHOLD_TLB);
}

/**
 * Main
 */
int main(int argc, char **argv) {
	set_tlb_threshold();
	srand(time(NULL));

	int fd = createfile(SHAREFILE, PAGE);
	memory = allocate_pages(TEMP_MEMORY_SIZE, fd, PAGE, OFFSET);

	random_shuffle(memory, temporary_memory, TEMP_MEMORY_SIZE, PAGE);

	available_temporary_memory = TEMP_MEMORY_SIZE;

	for (int i = 0; i < TEMP_MEMORY_SIZE; i++) {
		uint64_t *page = temporary_memory[i];
		*page = 1;
		*page = 0;
	}

	// Start
	uint64_t t = warm_up(28);
	set_tlb_threshold(20000 + t);

	// Dry run
	get_size_addresses(10000, false, false);
	get_size_addresses(10000, true, false);
	measure_window_call_ret_cycles(10000, false);

	// Wet run
	uint64_t cycles = measure_window_call_ret_cycles(10000, true);
	uint64_t loads = get_size_addresses(10000, false, true);
	uint64_t loads_2nd = get_size_addresses(10000, true, true);
	printf("%ld,%ld,%ld\n", loads, loads_2nd, cycles);
	fflush(stdout);

end:
	munmap(memory, TEMP_MEMORY_SIZE * PAGE);
	return 0;
}
