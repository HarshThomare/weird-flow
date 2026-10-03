#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
#include <argp.h>
#include "sha1_composed.h"

unsigned tot_trials = 1000;
bool retry = false;

bool _sha1_round1(
    unsigned* input, unsigned w, unsigned* output
) { SHA1_ROUND(input, w, output, 1); }

bool _sha1_round2(
    unsigned* input, unsigned w, unsigned* output
) { SHA1_ROUND(input, w, output, 2); }

bool _sha1_round3(
    unsigned* input, unsigned w, unsigned* output
) { SHA1_ROUND(input, w, output, 3); }

bool _sha1_round4(
    unsigned* input, unsigned w, unsigned* output
) { SHA1_ROUND(input, w, output, 4); }

bool sha1_round(unsigned* input, unsigned w, unsigned* output, unsigned round) {
    switch(round) {
        case 0:
            return _sha1_round1(input, w, output);
        case 1:
            return _sha1_round2(input, w, output);
        case 2:
            return _sha1_round3(input, w, output);
        case 3:
            return _sha1_round4(input, w, output);
    }
    return false;
}

/* Arguments */
static char doc[] = "Test the accuracy and run time of weird machines.";
static char args_doc[] = "";
static struct argp_option options[] = {
    { "retry", 'r', 0, 0, "Retry when an error is detected"},
    { "trial", 't', "TRIAL", 0, "Number of trials"},
    { 0 } 
};
static error_t parse_opt(int key, char *arg, struct argp_state *state) {
    switch (key) {
        case 'r': retry = true; break;
        case 't': tot_trials = atoi(arg); break;
        case ARGP_KEY_ARG: return 0;
        default: return ARGP_ERR_UNKNOWN;
    }   
    return 0;
}
static struct argp argp = { options, parse_opt, args_doc, doc, 0, 0, 0 };

int main(int argc, char* argv[]) {
    argp_parse(&argp, argc, argv, 0, 0, 0);
    srand(time(NULL));
    uint64_t tot_ns = 0;
    unsigned correct = 0, detected = 0, incorrect = 0, w;
    unsigned input[SIZE] = {0}, output[SIZE] = {0}, err_out[SIZE] = {0}, ref_output[SIZE] = {0};
    char votes[SIZE * UNIT_SIZE] = {0};
    bool has_error;

    for (unsigned i = 0; i < tot_trials; ++i) {
        unsigned j = 0;
        for (; j < SIZE; ++j) input[j] = rand();
        w = rand();
        int round = rand()%4;

        // reference implementation (ground truth)
        ref_sha1_round(input, w, ref_output, round);

        // execute SHA1 circuit for the first round
        struct timespec ts_start;
        struct timespec ts_end;
        clock_gettime(CLOCK_MONOTONIC, &ts_start);
        has_error = sha1_round(input, w, output, round);
        clock_gettime(CLOCK_MONOTONIC, &ts_end);
        tot_ns += time_elasped(&ts_start, &ts_end);

        // for (int k = 0; k < SIZE; k++) {
        //     printf("%08x ", output[k]);
        // }
        // printf("\n");
        // for (int k = 0; k < SIZE; k++) {
        //     printf("%08x ", ref_output[k]);
        // }
        // printf("\n");
        // for (int k = 0; k < SIZE; k++) {
        //     printf("%3d bits ", hamming_distance(output[k], ref_output[k]));
        // }
        // printf("\n");
        // printf("\n");

        bool error = false;
        for (j = 0; j < SIZE && output[j] == ref_output[j]; ++j);
        if (has_error) {
            ++detected;
        }
        else if (j < SIZE) {
            ++incorrect;
        }
        else {
            ++correct;
        }
    }

    printf("=== SHA1 Round (Composed)===\n");
    printf("Accuracy: %.5f%%, ", (double)correct / tot_trials * 100);
    printf("Error detected: %.5f%%, ", (double)detected / tot_trials * 100);
    printf("Undetected error: %.5f%%\n", (double)incorrect / tot_trials * 100);
    uint64_t time_per_run = tot_ns / tot_trials;
    printf("Time usage: %lu.%lu (us)\n", time_per_run / 1000, time_per_run % 1000);
    printf("over %d iterations.\n", tot_trials);
    return 0;
}
