#include "threshold.h"

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
#include <stdbool.h>
#include <sys/ioctl.h>

#include "consts.h"
#include "math_util.h"
#include "mm.h"
#include "tlb_ioctl.h"
#include "tlb_utils.h"
#include "util.h"

#define EVSET_ACCESSES 6
#define TIMER timer
// #define TIMER timer_flexo


// ============= Globals =============================
void *memory = NULL;
void *evictMemory = NULL;

uintptr_t temporary_memory[TEMP_MEMORY_SIZE];
uintptr_t available_temporary_memory;


// ============= Transient Window Helper =============
/**
 * Defines two functions directly within assembly, marked as external to define symbol.
 */
extern void mod_ret_addr_long();
extern void mod_ret_addr_short();
asm (
	".align 16\n"
	".globl mod_ret_addr_long\n"
	"mod_ret_addr_long:\n"
			"mov $2147458702, %rcx\n"
			"mov $3556000898, %rax\n"
			"mov $679256074, %rdx\n"
			".rept 1000\n"
			"div  %ecx\n"
			".endr\n"
			"addq %rdx, (%rsp)\n"
			"ret\n"
);
asm (
	".align 16\n"
	".globl mod_ret_addr_short\n"
	"mod_ret_addr_short:\n"
			"mov $512, %rdx\n"
			"addq %rdx, (%rsp)\n"
			"ret\n"
);

/**
 * Opens a long transient execution window and accesses all four addresses speculatively.
 *
 * Uses mod_ret_addr_long() to corrupt the return address, creating a long transient
 * window via speculative execution. Within the window, addresses a, b, c, and d are
 * accessed, causing TLB entries for them to be loaded. A NOP sled extends the window.
 *
 * @param a  First address to access transiently.
 * @param b  Second address to access transiently.
 * @param c  Third address to access transiently.
 * @param d  Fourth address to access transiently.
 */
int transient_window_addresses_positive(uint64_t *a, uint64_t *b, uint64_t *c, uint64_t *d) {
	mod_ret_addr_long();
	asm volatile(
		"mov %0, %%rax\n\t"
		"mov %1, %%rcx\n\t"
		"mov %2, %%rdx\n\t"
		"mov %3, %%rsi\n\t"
		:
		: "m"(a), "m"(b), "m"(c), "m"(d)
		: "%rax", "%rcx", "%rdx", "%rsi");
	asm volatile(
			"mov (%rax), %rax\n\t"
			"mov (%rcx), %rcx\n\t"
			"mov (%rdx), %rdx\n\t"
			"mov (%rsi), %rsi\n\t"
		);

	asm volatile(
			".rept 512\n\t"
			"nop\n\t"
			".endr");
	return;
}

/**
 * Opens a short transient execution window that does not reach the address accesses.
 *
 * Uses mod_ret_addr_short() to corrupt the return address with a small offset, creating
 * a transient window that is too short to reach the memory accesses. Serves as the
 * negative control case: TLB entries for a, b, c, d should NOT be loaded.
 *
 * @param a  First address (not reached during transient window).
 * @param b  Second address (not reached during transient window).
 * @param c  Third address (not reached during transient window).
 * @param d  Fourth address (not reached during transient window).
 */
int transient_window_addresses_negative(uint64_t *a, uint64_t *b, uint64_t *c, uint64_t *d) {
	mod_ret_addr_short();
	asm volatile(
		"mov %0, %%rax\n\t"
		"mov %1, %%rcx\n\t"
		"mov %2, %%rdx\n\t"
		"mov %3, %%rsi\n\t"
		:
		: "m"(a), "m"(b), "m"(c), "m"(d)
		: "%rax", "%rcx", "%rdx", "%rsi");
	asm volatile(
			"mov (%rax), %rax\n\t"
			"mov (%rcx), %rcx\n\t"
			"mov (%rdx), %rdx\n\t"
			"mov (%rsi), %rsi\n\t"
		);

	asm volatile(
			".rept 512\n\t"
			"nop\n\t"
			".endr");
	return;
}

// ============= TLB Cache Helper ==============
/**
 * Builds L1 and L2 TLB eviction sets for the given address.
 *
 * Selects either a linear or XOR-based eviction set construction strategy
 * depending on the TLB geometry described by `caches`. Results are stored
 * in the caller-provided arrays evset_l1 and evset_l2.
 *
 * @param caches    TLB geometry (set/way counts, linear vs. XOR indexing).
 * @param address   The virtual address for which to build eviction sets.
 * @param evset_l1  Output array of L1 TLB eviction set addresses (caller-allocated,
 *                  must hold at least caches.l1_ways entries).
 * @param evset_l2  Output array of L2 TLB eviction set addresses (caller-allocated,
 *                  must hold at least caches.l2_ways entries).
 */
void _get_evsets(tlb_caches caches, uint64_t *address, uintptr_t evset_l1[], uintptr_t evset_l2) {
	if (caches.l1_linear) {
		evset_linear_tlb(evictMemory, evset_l1, caches.l1_ways, address, caches.l1_sets);
	} else {
		evset_xor_tlb(evictMemory, evset_l1, caches.l1_ways, address, caches.l1_sets);
	}
	if (caches.l2_linear) {
		evset_linear_tlb(evictMemory, evset_l2, caches.l2_ways, address, caches.l2_sets);
	} else {
		evset_xor_tlb(evictMemory, evset_l2, caches.l2_ways, address, caches.l2_sets);
	}
}

/**
 * Measures TLB access timing distribution under controlled eviction conditions.
 *
 * Allocates `iterations` random addresses, builds their eviction sets, then times
 * each access after either evicting via the eviction set or flushing the TLB entry
 * (depending on `evict`). Returns summary statistics useful for determining hit/miss
 * timing boundaries.
 *
 * @param iterations  Number of address samples to measure.
 * @param evict       If true, evict using the eviction set; if false, flush via
 *                    flush_tlb_addr_no_pt_caches().
 * @param caches      TLB geometry used to build eviction sets. Also holds whether to evict l1/l2.
 * @param print       If true, print the timing statistics to stdout.
 * @param prefix      Label string prepended to printed output.
 * @return            Timing summary (min, max, median, rlimit, etc.) over all samples.
 */
arr_info_t _find_threshold_tlb(uint64_t iterations, volatile bool evict, tlb_caches caches, bool print, char *prefix) {
	uint64_t **addresses = calloc(iterations, sizeof(uint64_t *));
	uint64_t ***eviction_sets_l1 = calloc(iterations, sizeof(uint64_t **));
	uint64_t ***eviction_sets_l2 = calloc(iterations, sizeof(uint64_t **));
	uint64_t *times_h = calloc(iterations, sizeof(uint64_t));
	uint64_t *opt = get_temporary_memory();

	for (uint64_t i = 0; i < iterations; i++) {
		addresses[i] = get_temporary_memory();
		eviction_sets_l1[i] = calloc(caches.l1_ways, sizeof(uint64_t*));
		eviction_sets_l2[i] = calloc(caches.l2_ways, sizeof(uint64_t*));
		_get_evsets(caches, addresses[i], eviction_sets_l1[i], eviction_sets_l2[i]);
	}
	mfence();
	lfence();
	flush_tlb_all();

	uint64_t start;
	uint64_t end;
	for (int64_t i = iterations-1; i >= 0; i--) {
		/**
		 * Measure with eviction
		 */
		mfence();
		lfence();
		maccess(opt);
		maccess(addresses[i]);
		if (evict) {
			if (caches.l1_evict) {
				mfence();
				lfence();
				access_evset_multiple(eviction_sets_l1[i], caches.l1_ways, EVSET_ACCESSES);
			}
			if (caches.l2_evict) {
				mfence();
				lfence();
				access_evset_multiple(eviction_sets_l2[i], caches.l2_ways, EVSET_ACCESSES);
			}
		} else {
			mfence();
			lfence();
			flush_tlb_addr_no_pt_caches(addresses[i]);
		}
		mfence();
		lfence();
		times_h[i] = TIMER(addresses[i]);
	}

	arr_info_t info_h = arr_info(iterations, times_h, print, prefix);
	mfence();
	lfence();
	return_temporary_memory(opt);
	for (uint64_t i = 0; i < iterations; i++) {
		return_temporary_memory(addresses[i]);
	}
	free(addresses);
	free(times_h);
	return info_h;
}

/**
 * Evaluates the accuracy of a candidate TLB hit/miss threshold.
 *
 * Tests the threshold across several scenarios:
 *   1. Cold addresses (flushed TLB) — should time > threshold.
 *   2. Addresses accessed in a long transient window — should time <= threshold.
 *   3. Addresses NOT accessed in a short transient window — should time > threshold.
 *   4. L2 TLB hits (L1 evicted) — should time <= threshold.
 *   5. Randomly paired accesses where one is fully evicted — tests hit/miss separation.
 *   6. Neighbouring addresses sharing a page-table entry — tests PT cache effects.
 *
 * @param threshold   Cycle count to test as the hit/miss boundary.
 * @param caches      TLB geometry used to build eviction sets.
 * @param iterations  Number of samples per scenario.
 * @return            Fraction of correctly classified accesses in [0.0, 1.0].
 */
double _test_threshold_acc_tlb(uint64_t threshold, tlb_caches caches, uint64_t iterations) {
	/**
	 * Flush all addresses + maccept each second
	 */
	uint64_t **addresses = calloc(iterations, sizeof(uint64_t *));
	uint64_t *address_a = get_temporary_memory();
	uint64_t *address_b = get_temporary_memory();
	uint64_t *address_c = get_temporary_memory();
	uint64_t *address_d = get_temporary_memory();
	uint64_t ***eviction_sets_l1 = calloc(iterations, sizeof(uint64_t **));
	uint64_t ***eviction_sets_l2 = calloc(iterations, sizeof(uint64_t **));
	uint64_t correct = 0;
	uint64_t incorrect = 0;

	for (uint64_t i = 0; i < iterations; i++) {
		addresses[i] = get_temporary_memory();
		maccess(addresses[i]);
		mfence();
		lfence();
		eviction_sets_l1[i] = calloc(caches.l1_ways, sizeof(uint64_t*));
		eviction_sets_l2[i] = calloc(caches.l2_ways, sizeof(uint64_t*));
		_get_evsets(caches, addresses[i], eviction_sets_l1[i], eviction_sets_l2[i]);
	}
	flush_tlb_all();

	// Nothing in cache
	for (uint64_t i = 0; i < iterations; i++) {
		if (TIMER(addresses[i]) > threshold) {
			correct++;
		} else {
			incorrect++;
		}
	}

	// Transient window large + too small
	flush_tlb_all();
	for (uint64_t i = 0; i < iterations; i++) {
		flush_tlb_addr_no_pt_caches(address_a);
		flush_tlb_addr_no_pt_caches(address_b);
		flush_tlb_addr_no_pt_caches(address_c);
		flush_tlb_addr_no_pt_caches(address_d);
		mfence();
		lfence();
		transient_window_addresses_positive(address_a, address_b, address_c, address_d);
		mfence();
		lfence();
		if (TIMER(address_a) <= threshold &&
			TIMER(address_b) <= threshold &&
			TIMER(address_c) <= threshold &&
			TIMER(address_d) <= threshold
		) {
			correct++;
		} else {
			incorrect+=iterations*2;
		}
		mfence();
		lfence();
		flush_tlb_addr_no_pt_caches(address_a);
		flush_tlb_addr_no_pt_caches(address_b);
		flush_tlb_addr_no_pt_caches(address_c);
		flush_tlb_addr_no_pt_caches(address_d);
		mfence();
		lfence();
		transient_window_addresses_negative(address_a, address_b, address_c, address_d);
		mfence();
		lfence();
		if (TIMER(address_a) > threshold &&
			TIMER(address_b) > threshold &&
			TIMER(address_c) > threshold &&
			TIMER(address_d) > threshold
		) {
			correct++;
		} else {
			incorrect+=iterations*2;
		}
	}
	flush_tlb_all();

	// /**
	//  * L2 Hit below threshold
	//  */
	for (uint64_t i = 0; i < iterations-1; i++) {
		maccess(addresses[i]);
		mfence();
		lfence();
		access_evset_multiple(eviction_sets_l1[i], caches.l1_ways, EVSET_ACCESSES);
		mfence();
		lfence();
		if (TIMER(addresses[i]) <= threshold) {
			correct++;
		} else {
			incorrect++;
		}
		mfence();
		lfence();
	}
	flush_tlb_all();

	// /**
	//  * Select random in pairs of two, one evicted, other not
	//  */
	for (uint64_t i = 0; i < iterations; i+=2) {
		bool t = rand();
		uint64_t acc_i = i+(int)t;
		uint64_t evict_i = i+(int)!t;
		maccess(addresses[acc_i]);
		mfence();
		lfence();
		access_evset_multiple(eviction_sets_l1[evict_i], caches.l1_ways, EVSET_ACCESSES);
		mfence();
		lfence();
		access_evset_multiple(eviction_sets_l2[evict_i], caches.l2_ways, EVSET_ACCESSES);
		mfence();
		lfence();
		if (TIMER(addresses[acc_i]) <= threshold && TIMER(addresses[evict_i]) > threshold) {
			correct+=2;
		} else {
			incorrect+=2;
		}
	}
	flush_tlb_all();

	/**
	 * Use evictMemory that has neighbouring addresses for Page Table caching
	 */
	for (uint64_t i = 0; i < iterations-5; i+=5) {
		maccess((uintptr_t) evictMemory + (i*(4096)));
		maccess((uintptr_t) evictMemory + (i*(4096)));
		maccess((uintptr_t) evictMemory + (i*(4096)));
		maccess((uintptr_t) evictMemory + (i*(4096)));
		mfence();
		lfence();
		maccess((uintptr_t) evictMemory + ((i+1)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+1)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+1)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+1)*(4096)));
		mfence();
		lfence();
		maccess((uintptr_t) evictMemory + ((i+3)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+3)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+3)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+3)*(4096)));
		mfence();
		lfence();
		maccess((uintptr_t) evictMemory + ((i+4)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+4)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+4)*(4096)));
		maccess((uintptr_t) evictMemory + ((i+4)*(4096)));
		mfence();
		lfence();
		if (TIMER((uintptr_t) evictMemory + ((i+2)*(4096))) > threshold &&
			TIMER((uintptr_t) evictMemory + ((i)*(4096))) <= threshold &&
			TIMER((uintptr_t) evictMemory + ((i+1)*(4096))) <= threshold &&
			TIMER((uintptr_t) evictMemory + ((i+3)*(4096))) <= threshold &&
			TIMER((uintptr_t) evictMemory + ((i+4)*(4096))) <= threshold
		) {
			correct+=5;
		} else {
			incorrect+=5;
		}
	}

	flush_tlb_all();
	for (int64_t i = iterations-1; i > 0; i--) {
		return_temporary_memory(addresses[i]);
	}
	free(addresses);
	return (double) correct / (correct + incorrect);
}

/**
 * Entry point: calibrates the TLB hit/miss timing threshold.
 *
 * Sets up shared memory, builds the temporary memory pool, and performs warm-up
 * rounds. Then measures timing distributions for L1 hit, L2 hit, and L2 miss
 * scenarios to derive a candidate threshold range. Finally, runs
 * _test_threshold_acc_tlb() across that range THRESHOLD_TESTS times and reports
 * the most frequently optimal threshold along with its range.
 *
 * @param argc  Argument count (unused).
 * @param argv  Argument vector (unused).
 * @return      0 on success.
 */
int main(int argc, char **argv) {
	srand(time(NULL));

	int fd = createfile(SHAREFILE, PAGE);
	memory = allocate_pages(TEMP_MEMORY_SIZE, fd, PAGE, OFFSET);
	evictMemory = allocate_pages(TEMP_MEMORY_SIZE, fd, PAGE, PAGE);

	random_shuffle(memory, temporary_memory, TEMP_MEMORY_SIZE, PAGE);

	available_temporary_memory = TEMP_MEMORY_SIZE;

	for (int i = 0; i < TEMP_MEMORY_SIZE; i++) {
		uint64_t *page = temporary_memory[i];
		*page = 1;
		*page = 0;
	}

	warm_up(28);
	_find_threshold_tlb(THRESHOLD_ITERATIONS, true, CACHES, false, "");
	arr_info_t hit_l1 = _find_threshold_tlb(THRESHOLD_ITERATIONS, true, CACHES, true, "L1 Hit:  ");
	CACHES.l1_evict = true;
	arr_info_t hit_l2 = _find_threshold_tlb(THRESHOLD_ITERATIONS, true, CACHES, true, "L2 Hit:  ");
	CACHES.l2_evict = true;
	arr_info_t evict_l2 = _find_threshold_tlb(THRESHOLD_ITERATIONS, true, CACHES, true, "L2 Miss: ");
	_find_threshold_tlb(THRESHOLD_ITERATIONS, false, CACHES, true, "Full PTW:");

	uint64_t threshold_start = evict_l2.llimit;
	uint64_t threshold_limit = evict_l2.median;
	printf("Try thresholds between %ld - %ld\n", threshold_start, threshold_limit);

	uint64_t best_thresholds[THRESHOLD_TESTS] = {0};
	for (int i = 0; i< THRESHOLD_TESTS; i++) {
		uint64_t threshold = threshold_start;
		double best_acc = 0.0;
		for (uint64_t t = threshold; t <= threshold_limit; t++) {
			double acc = _test_threshold_acc_tlb(t, CACHES, THRESHOLD_TESTS);
			// printf("%ld: %lf\n", t, acc);
			if (acc > best_acc) {
				best_acc = acc;
				threshold = t;
			}
		}
		best_thresholds[i] = threshold;
		// printf("%ld/%ld\n", i+1, THRESHOLD_TESTS);
	}
	arr_info_t thresholds_info = arr_info(THRESHOLD_TESTS, best_thresholds, false, "");
	uint64_t rec_threshold = most_frequent_elem(best_thresholds, THRESHOLD_TESTS, 0);
	printf("Recommended thresholds TLB: %ld or %ld\n", rec_threshold, most_frequent_elem(best_thresholds, THRESHOLD_TESTS, rec_threshold));
	printf("But also consider finetune this in the range %ld - %ld\n", thresholds_info.min, thresholds_info.max);

end:
	munmap(memory, TEMP_MEMORY_SIZE * PAGE);
	munmap(evictMemory, TEMP_MEMORY_SIZE * PAGE);
	return 0;
}
