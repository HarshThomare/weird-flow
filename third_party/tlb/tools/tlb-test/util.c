#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <cpuid.h>

#include "util.h"

int createfile(const char *fn, const uint64_t size) {
	int fd;
	struct stat sb;
	char sharebuf[size];
	if (stat(fn, &sb) != 0 || sb.st_size != size) {
		fd = open(fn, O_RDWR | O_CREAT | O_TRUNC, 0644);
		if (fd < 0) {
			perror("open");
			fprintf(stderr, "createfile: couldn't create shared file %s\n", fn);
			exit(1);
		}
		if (write(fd, sharebuf, size) != size) {
			fprintf(stderr, "createfile: couldn't write shared file\n");
			exit(1);
		}
		return fd;
	}

	assert(sb.st_size == size);

	fd = open(fn, O_RDWR, 0644);
	if (fd < 0) {
		perror(fn);
		fprintf(stderr, "createfile: couldn't open shared file\n");
		exit(1);
	}
	return fd;
}

uint64_t warm_up(uint64_t scale) {
	#define END (1ULL << scale)
	uint64_t i = 0;
	for (; i < END; i++) {
		i += 2*i - i/2 - (1.5*i);
	}
	return i - END;
}
