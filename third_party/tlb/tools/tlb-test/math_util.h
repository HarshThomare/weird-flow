#pragma once
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>

/**
* Math helper
*/

typedef struct {
	uint64_t	min;
	uint64_t	max;
	uint64_t	llimit;
	uint64_t	rlimit;
	uint64_t	median;
	double		mean;
	double		meanLimited;
} arr_info_t;

arr_info_t arr_info(uint64_t n, uint64_t *arr, bool print, char * prefix);

uint64_t most_frequent_elem(uint64_t *arr, uint64_t n, uint64_t ignore);
