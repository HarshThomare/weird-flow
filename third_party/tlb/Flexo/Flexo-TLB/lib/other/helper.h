#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>


typedef struct {
	uint64_t	min;
	uint64_t	max;
	uint64_t	llimit;
	uint64_t	rlimit;
	uint64_t	median;
	double		mean;
	double		meanLimited;
} arr_info_t;

// void set_tlb_threshold(uint64_t iterations);

uint64_t timer(uint64_t *addr);
