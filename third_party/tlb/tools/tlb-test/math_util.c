#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>

#include "math_util.h"


/**
* Math helper
*/
int compare(const void *a, const void *b) {
	return (*(uint64_t*)a - *(uint64_t*)b);
}

uint64_t sort_array(uint64_t n, uint64_t *arr) {
	qsort(arr, n, sizeof(uint64_t), compare);
}

inline double mean(uint64_t n, uint64_t *arr) {
	uint64_t sum = 0;
	for (uint64_t i = 0; i < n; i++) {
		sum += arr[i];
	}
	return (double) sum / n;
}

arr_info_t arr_info(uint64_t n, uint64_t *arr, bool print, char *prefix) {
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
			printf("%s\t", prefix);
		}
		printf("(min mean meanLimited max) (%ld, %lf, %lf, %ld)\t-> (%ld, %ld, %ld)\n",
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

uint64_t most_frequent_elem(uint64_t *arr, uint64_t n, uint64_t ignore) {
	uint64_t maxcount = 0;
	uint64_t res;
	
	for (uint64_t i = 0; i < n; i++) {
		uint64_t count = 0;
		for (uint64_t j = 0; j < n; j++) {
			if (arr[i] == arr[j] && arr[i] != ignore) {
				count++;
			}
		}
			
		// If count is greater or if count 
		// is same but value is bigger.
		if (count > maxcount || (count == maxcount && arr[i] > res)) {
			maxcount = count;
			res = arr[i];
		}
	}

	return res;
}

