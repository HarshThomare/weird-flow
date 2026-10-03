#pragma once
#include <stdbool.h>
#include <stdint.h>

inline void maccess(uint64_t *addr) {
	asm volatile(
		"mov (%0), %0\n"
		: "+r"(addr)
	);
}

void __always_inline mfence() {
		asm volatile("mfence");
}

void __always_inline lfence() {
		asm volatile("lfence");
}

uint64_t __always_inline rdtsc() {
	uint32_t a, d;
	__asm__ volatile (    
	"rdtsc\n"  // Does serialization fo preceding loads
	"mov %%edx, %0\n"
	"mov %%eax, %1\n"
	: "=r" (a), "=r" (d)
	:: "%rax", "%rdx");
	return ((uint64_t)a << 32) | d;
}

uint64_t __always_inline rdtscp() {
	uint32_t a, d;
	__asm__ volatile (    
	"rdtscp\n"  // Does serialization fo preceding loads
	"mov %%edx, %0\n"
	"mov %%eax, %1\n"
	: "=r" (a), "=r" (d)
	:: "rcx", "%rax", "%rdx");
	return ((uint64_t)a << 32) | d;
}

__always_inline uint64_t timer(uint64_t *addr) {
	uint64_t result;
	__asm__ volatile (
		/**
		 * RDTSCP
		 * wait until all previous instructions have executed and all previous loads are globally visible
		 * subsequent instructions may begin execution before the read operation is performed
		 */
		"rdtscp\n\t"
		"shl    $0x20, %%rdx\n\t"
		"or     %%rdx, %%rax\n\t"
		
		"mov    %%rax, %%rsi\n\t"  // r8 holds start timestamp
		/* Use timestamp result for serialization */
		"cmp    $0xbaaaaad, %%rax\n\t"
		"sete   %%al\n\t"
		"movzbl %%al, %%eax\n\t"
		"or     %%rax, %%rdi\n\t"

		"mov    (%%rdi), %%rax\n\t"

		"rdtscp\n\t"  // waits for previous loads
		"shl    $0x20, %%rdx\n\t"
		"or     %%rdx, %%rax\n\t"

		"sub    %%rsi, %%rax\n\t"
		: "=a"(result)
		: "D"(addr)
		: "rsi", "rdx", "rcx", "memory"
	);
	return result;
}

__always_inline uint64_t timer_flexo(uint64_t *addr) {
	uint64_t result;
	__asm__ volatile (
		/**
		 * RDTSCP
		 * wait until all previous instructions have executed and all previous loads are globally visible
		 * subsequent instructions may begin execution before the read operation is performed
		 */
		"rdtscp\n\t"
		"shl    $0x20, %%rdx\n\t"
		"or     %%rdx, %%rax\n\t"
		"mov    %%rax, %%rsi\n\t"

		"mov    (%%rdi), %%rax\n\t"

		"rdtscp\n\t"  // waits for previous loads
		"shl    $0x20, %%rdx\n\t"
		"or     %%rdx, %%rax\n\t"

		"sub    %%rsi, %%rax\n\t"
		: "=a"(result)
		: "D"(addr)
		: "rsi", "rdx", "rcx", "memory"
	);
	return result;
}

int createfile(const char *fn, const uint64_t size);

/**
 * Does a lot of computations scaled by `scale`
 * return always zero, but depends on computations
 */
uint64_t warm_up(uint64_t scale);
