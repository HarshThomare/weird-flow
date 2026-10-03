#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>

#include "helper.h"

extern uint64_t RDTSC_THRESHOLD_TLB;
extern uint64_t *wregs;
// extern uint64_t *additional_page;
extern uint64_t invlpg(uint64_t *addr);
extern uint64_t maccess(uint64_t *addr);

static void __always_inline mfence() {
	asm volatile("mfence");
}

static void __always_inline lfence() {
	asm volatile("lfence");
}

/**
* Math helper
*/
static int compare(const void *a, const void *b) {
	return (*(uint64_t*)a - *(uint64_t*)b);
}

static void sort_array(uint64_t n, uint64_t *arr) {
	qsort(arr, n, sizeof(uint64_t), compare);
}

static inline double mean(uint64_t n, uint64_t *arr) {
	uint64_t sum = 0;
	for (uint64_t i = 0; i < n; i++) {
		sum += arr[i];
	}
	return (double) sum / n;
}

static arr_info_t arr_info(uint64_t n, uint64_t *arr, bool print, char *prefix) {
	sort_array(n, arr);
	double outlier = 0.1;

	arr_info_t info = {
		.min = arr[0],
		.max = arr[n-1],
		.llimit = arr[(uint64_t)(n * outlier)],
		.rlimit = arr[(uint64_t)(n * (1.0-outlier))],
		.median = arr[n / 2],
		.mean = mean(n, arr),
		.meanLimited = mean(n * 0.9, &arr[(uint64_t) (n*outlier)]),
	};
	if (print) {
		if (prefix != NULL) {
			printf("%s ", prefix);
		}
		printf("(min mean meanLimited max) (%ld, %lf, %lf, %ld) - (%ld, %ld, %ld)\n",
			info.min,
			info.mean,
			info.meanLimited,
			info.max,
			info.llimit,
			info.median,
			info.rlimit
		);
	}
	return info;
}

// static uint64_t find_threshold_tlb(uint64_t iterations, bool print) {
//   uint64_t *address = wregs;
//   uint64_t *times_h = calloc(iterations, sizeof(uint64_t));
//   uint64_t *times_m = calloc(iterations, sizeof(uint64_t));
//   uint64_t *opt = additional_page;

//   volatile uintptr_t trash = 0;
//   uint64_t start;
//   uint64_t end;
// 	mfence();
// 	for (int64_t i = iterations-1; i >= 0; i--) {
// 		invlpg(address);
//     mfence();
//     lfence();
// 		maccess(opt);
//     mfence();
//     lfence();
// 		maccess(opt);
//     mfence();
//     lfence();
//     times_m[i] = timer(address);

//     // ###############################################
//     mfence();
//     lfence();
// 		maccess(opt);
// 		maccess(address);
//     mfence();
//     lfence();
// 		maccess(opt);
// 		maccess(address);
//     mfence();
//     lfence();
// 		times_h[i] = timer(address);
// 	}

//   arr_info_t info_m = arr_info(iterations, times_m, print, "Miss thresholds:");
//   arr_info_t info_h = arr_info(iterations, times_h, print, "Hit thresholds:");
//   uint64_t threshold = info_h.rlimit+1;
// 	if (print) {
//     printf("Recommended threshold ~%ld\n", threshold);
//   }
//   mfence();
//   free(times_m);
//   free(times_h);
//   return threshold;
// }

// void set_tlb_threshold(uint64_t iterations) {
// 	find_threshold_tlb(iterations, false);
// 	find_threshold_tlb(iterations, false);
// 	find_threshold_tlb(iterations, false);
// 	mfence();
// 	lfence();
// 	RDTSC_THRESHOLD_TLB = find_threshold_tlb(iterations, true);
//   printf("Set threshold to %ld\n", RDTSC_THRESHOLD_TLB);
// }


// uint64_t timer(uint64_t *addr) {
//   uint64_t result;
//   __asm__ volatile (
//     /**
//      * RDTSCP
//      * wait until all previous instructions have executed and all previous loads are globally visible
//      * subsequent instructions may begin execution before the read operation is performed
//      */
//     "rdtscp\n\t"
//     "shl    $0x20, %%rdx\n\t"
//     "or     %%rdx, %%rax\n\t"
    
//     "mov    %%rax, %%rsi\n\t"  // rsi holds start timestamp
//     /* Use timestamp result for serialization */
//     "cmp    $0xbaaaaad, %%rax\n\t"
//     "sete   %%al\n\t"
//     "movzbl %%al, %%eax\n\t"
//     "or     %%rax, %%rdi\n\t"

//     "mov    (%%rdi), %%rax\n\t"

//     "rdtscp\n\t"  // waits for previous loads
//     "shl    $0x20, %%rdx\n\t"
//     "or     %%rdx, %%rax\n\t"

//     "sub    %%rsi, %%rax\n\t"
//     : "=a"(result)
//     : "D"(addr)
//     : "rsi", "rdx", "rcx", "memory"
//   );
//   return result;
// }
