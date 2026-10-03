#include <stdint.h>
#include <stdbool.h>

typedef struct {
	uint64_t l1_sets;
	uint64_t l1_ways;
	bool l1_linear;
	bool l1_evict;
	uint64_t l2_sets;
	uint64_t l2_ways;
	bool l2_linear;
	bool l2_evict;
} tlb_caches;

// ####### Configuration ##########

tlb_caches CACHES = {
	.l1_linear = true,
	.l1_sets = 16,
	.l1_ways = 6,
	.l1_evict = false,
	.l2_linear = false,
	.l2_sets = 128,
	.l2_ways = 16,
	.l2_evict = false,
};

#define THRESHOLD_ITERATIONS 100000
#define THRESHOLD_TESTS 100
