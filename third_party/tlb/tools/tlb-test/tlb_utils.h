#pragma once 
#include <stdint.h>
#include <stdbool.h>

#include "tlb_ioctl.h"
#include "util.h"

#define PAGE 4096ULL

void __always_inline _flush_tlb(void *p, unsigned long flush_type) {
	int fd = open(TLB_DEVICE_NAME_FULL, O_RDWR);
	if (fd < 0) {
		perror("Failed to open device");
		exit(1);
	}
	if (ioctl(fd, flush_type, p) == -1) {
		perror("Failed to write TLB");
	}
	close(fd);
}

inline void flush_tlb_addr(void *p) {
	_flush_tlb(p, IOCTL_FLUSH_TLB_INVLPG);
}
inline void flush_tlb_addr_no_pt_caches(void *p) {
	_flush_tlb(p, IOCTL_FLUSH_TLB_ADDR_NO_PT_CACHES);
}
inline void flush_tlb_all() {
	_flush_tlb(NULL, IOCTL_FLUSH_TLB_PT_CACHES);
}

void access_evset(uint64_t **evset, uint64_t n);

inline void access_evset_multiple(uint64_t **evset, uint64_t n, uint64_t times) {
	for (int i = 0; i < times; i++) {
		access_evset(evset, n);
		lfence();
	}
}

void evset_linear_tlb(uintptr_t base, uintptr_t evset[], uint64_t n, uintptr_t victim, uint64_t nr_sets);

void evset_xor_tlb(uintptr_t BASE, uintptr_t evset[], uint64_t n, uintptr_t victim, uint64_t nr_sets);
