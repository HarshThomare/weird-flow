#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <argp.h>
#include <time.h>
#include <vector>

#define THRESHOLD 2
#ifndef SIZE
#define SIZE 10
#endif
#define SIZE_TYPE uint64_t

typedef unsigned char byte;

#define ROL(x, k, n) (((x) << (n)) | ((x) >> (k - (n))))

#define RUN_WEIRD_WITH_ERROR(output, err_out, votes, size, unit_size, f, ...) \
    do { \
        has_error = f(__VA_ARGS__, output, err_out); \
        if (update_votes_general(size, unit_size, output, err_out, votes)) has_error = false; \
    } while (retry && has_error); \
    merge_output_general(size, unit_size, output, votes);

bool update_votes_general(unsigned _SIZE, unsigned _UNIT_SIZE, SIZE_TYPE* output, byte* error_output, char* votes) {
    bool all_done = true;
    for (int j = 0; j < _SIZE * _UNIT_SIZE; ++j) {
        bool out_bit = (output[j / _UNIT_SIZE] >> (j % _UNIT_SIZE)) & 1;
        bool err_bit = (error_output[j / _UNIT_SIZE] >> (j % _UNIT_SIZE)) & 1;

        if (!err_bit) {
            if (out_bit && votes[j] < 126) ++votes[j];
            else if (!out_bit && votes[j] > -126) --votes[j];
        }
        if (votes[j] < THRESHOLD && votes[j] > -THRESHOLD) all_done = false;
    }
    return all_done;
}

void merge_output_general(unsigned _SIZE, unsigned _UNIT_SIZE, SIZE_TYPE* output, char* votes) {
    for (unsigned j = 0; j < _SIZE * _UNIT_SIZE; ++j) {
        if (votes[j] >= THRESHOLD) {
            output[j / _UNIT_SIZE] |= 1 << (j % _UNIT_SIZE);
        }
        else if (votes[j] <= -THRESHOLD) {
            output[j / _UNIT_SIZE] &= ~(1 << (j % _UNIT_SIZE));
        }
        votes[j] = 0;
    }
}

/* Config */
unsigned tot_trials = 1000000;
bool retry = false;

uint64_t time_elapsed(struct timespec* begin, struct timespec* end) {
    int64_t output = end->tv_sec - begin->tv_sec;
    output *= 1000000000;
    output += end->tv_nsec - begin->tv_nsec;
    return output;
}

// reference ALU as ground truth
// x, y: 4 bits
// control: 6 bits - zx, nx, zy, ny, f, no
// out: 6 bits - out1, out2, out3, out4, zr, ng
void ref_alu(SIZE_TYPE x, SIZE_TYPE y, byte control, SIZE_TYPE *out) {
    x &= (1ULL << SIZE) - 1;
    y &= (1ULL << SIZE) - 1;
    switch (control) {
        case 1:
            *out = x + y;
            break;
        case 1<<1:
            *out = x - y;
            break;
        case 1<<2:
            *out = x & y;
            break;
        case 1<<3:
            *out = x | y;
            break;
        case 1<<4:
            *out = x ^ y;
            break;
        case 1<<5:
            *out = x << y;
            break;
        case 1<<6:
            *out = x >> y;
            break;
        case 1<<7:
            *out = ~x;
            break;
        default:
            *out = 0;
            break;
    }

    // *out = 0;
    // if (control & (1<<0)) *out |= (x + y);     // ADD
    // if (control & (1<<1)) *out |= (x - y);     // SUB
    // if (control & (1<<2)) *out |= (x & y);     // AND
    // if (control & (1<<3)) *out |= (x | y);     // OR
    // if (control & (1<<4)) *out |= (x ^ y);     // XOR
    // if (control & (1<<5)) *out |= (x << y);    // SHL
    // if (control & (1<<6)) *out |= (x >> y);    // SHR
    // if (control & (1<<7)) *out |= (~x);        // NOT
    *out &= (1ULL << SIZE) - 1;
}

bool __weird__alu(
    SIZE_TYPE x, SIZE_TYPE y, byte control, SIZE_TYPE* out, byte* error_out
) { return false; }

/* Test accuracy and time usage */
void test_acc(
    bool (*gate_fn)(SIZE_TYPE, SIZE_TYPE, byte, SIZE_TYPE*, byte*)
) {
    unsigned tot_correct_counts = 0, tot_detected_counts = 0, tot_error_counts = 0;
    uint64_t tot_ns = 0;

    for (unsigned seed = 0; seed < tot_trials; seed++) {
        // inputs and outputs
        SIZE_TYPE x, y, out = 0;
				byte control, control_ref;
        byte err_out[SIZE] = {0};
        char votes[SIZE] = {0};
        SIZE_TYPE x_ref, y_ref, out_ref = 0;
        bool has_error;

        x_ref = x = rand();
        y_ref = y = rand();
        control_ref = control = 1 << (seed % 7);

        // execute the circuit
        struct timespec ts_start;
        struct timespec ts_end;
        clock_gettime(CLOCK_MONOTONIC, &ts_start);
        RUN_WEIRD_WITH_ERROR(&out, err_out, votes, 1, SIZE, gate_fn, x, y, control);
        clock_gettime(CLOCK_MONOTONIC, &ts_end);
        tot_ns += time_elapsed(&ts_start, &ts_end);

        // execute the reference ALU
        ref_alu(x_ref, y_ref, control_ref, &out_ref);
        // printf("%2x, %2x\n", out_ref, out);

        if (has_error) {
            ++tot_detected_counts;
        }
        else if (out == out_ref) {
            ++tot_correct_counts;
        }
        else {
            ++tot_error_counts;
        }
    }

    uint64_t time_per_run = tot_ns / tot_trials;

    printf("=== ALU%d ===\n", SIZE);
    printf("Accuracy: %.5f%%, ", (double)tot_correct_counts / tot_trials * 100);
    printf("Error detected: %.5f%%, ", (double)tot_detected_counts / tot_trials * 100);
    printf("Undetected error: %.5f%%\n", (double)tot_error_counts / tot_trials * 100);
    printf("Time usage: %lu.%lu (us)\n", time_per_run / 1000, time_per_run % 1000);
    printf("over %d iterations.\n", tot_trials);
}

/* Arguments */
static char doc[] = "Test the accuracy and run time of weird machines.";
static char args_doc[] = "";
static struct argp_option options[] = {
    { "retry", 'r', 0, 0, "Retry when an error is detected"},
    { "trial", 't', "TRIAL", 0, "Number of trials."},
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
    test_acc(__weird__alu);
}
