#include <assert.h>
#include <fcntl.h>
#include <immintrin.h>
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <x86intrin.h>

#include "math_util.h"
#include "tlb_ioctl.h"
#include "tlb_utils.h"
#include "util.h"


void access_evset(uint64_t **evset, uint64_t n) {
	for (int i = 0; i < n; i++) {
		maccess(evset[i]);
	}
}

void evset_linear_tlb(uintptr_t base, uintptr_t evset[], uint64_t n, uintptr_t victim, uint64_t nr_sets) {
	uint64_t set_bits = 0;
	uint64_t shift = nr_sets;

	// Compute log2(nr_sets)
	while (shift > 1) {
		set_bits++;
		shift >>= 1;
	}

	const uint64_t set_mask    = (1ULL << set_bits) - 1;
	const uint64_t vpn_mask    = ~set_mask;
	const uint64_t base_vpn    = base >> 12;
	const uint64_t victim_vpn  = victim >> 12;
	const uint64_t set_index   = victim_vpn & set_mask;
	const uint64_t page_offset = victim & (PAGE - 1);
	const uint64_t step        = 1ULL << set_bits;

	// Align base_vpn to first candidate with matching set_index
	uint64_t aligned_base_vpn = (base_vpn & vpn_mask) | set_index;
	if (aligned_base_vpn < base_vpn) {
		aligned_base_vpn += step;
	}

	for (uint64_t i = 0; i < n; ++i) {
		// Compute eviction address in same TLB set as victim
		uint64_t candidate_vpn  = aligned_base_vpn + (i * step);
		uint64_t candidate_addr = (candidate_vpn << 12) | page_offset;
		evset[i] = candidate_addr;
	}
}

static inline uint64_t elem_id_l2(uint64_t el, uint64_t xorsize) {
	uint64_t v1 = el % (1 << xorsize);
	uint64_t v2 = (el >> xorsize) % ( 1<< xorsize);
	return v1 ^ v2;
}

void evset_xor_tlb(uintptr_t BASE, uintptr_t evset[], uint64_t n, uintptr_t victim, uint64_t nr_sets) {
	int list_len = 0, i=0;
	uint64_t address;
  uint32_t set_bits = 0;
  int tmp = nr_sets;
  while (tmp >>= 1) { ++set_bits; }; // log2(nr_sets)
  uint64_t target_set = (elem_id_l2(((uint64_t) victim) >> 12, set_bits)) % nr_sets;

	volatile unsigned long left_mask = 0;
	for(i = 0; i < set_bits; i++){
		left_mask |= (0x1 << (i + 12 + set_bits));
	}

	volatile unsigned long base, right_side;
	int len = 0;
	for(i = 0;; i++){
		i++;
  
	base = (((unsigned long)BASE >> (12 + set_bits)) + i) << (12 + set_bits);
	right_side = ((base & left_mask) ^ (target_set << (12 + set_bits))) >> set_bits;

	address = base | right_side;
	if (elem_id_l2(address, set_bits)) {
		evset[len] = address;
		if (++len == n) {
			break;
		}
	}
  }
}

