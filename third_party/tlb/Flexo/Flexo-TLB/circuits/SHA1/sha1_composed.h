#pragma once
#include <stdint.h>
#include <stdbool.h>

#define ROL(x, n) (((x) << (n)) | ((x) >> (32 - (n))))
#define THRESHOLD 2
#define SIZE 5
#define UNIT_SIZE 32

#define F1 (b & c) | ((~b) & d)
#define F2 b ^ c ^ d
#define F3 (b & c) | (b & d) | (c & d)
#define F4 b ^ c ^ d
#define C1 0x5A827999
#define C2 0x6ED9EBA1
#define C3 0x8F1BBCDC
#define C4 0xCA62C1D6

bool __weird__sha1_f1(unsigned* b, unsigned* c, unsigned* d, unsigned *output, unsigned* error_output) {
    *output = (*b & *c) | ((~*b) & *d);
    error_output[0] = *b;
    return *error_output;
}
bool __weird__sha1_f2(unsigned* b, unsigned* c, unsigned* d, unsigned *output, unsigned* error_output) {
    *output = *b ^ *c ^ *d;
    error_output[0] = *output;
    return *error_output;
}
bool __weird__sha1_f3(unsigned* b, unsigned* c, unsigned* d, unsigned *output, unsigned* error_output) {
    *output = (*b & *c) | (*b & *d) | (*c & *d);
    error_output[0] = *output;
    return *error_output;
}
bool __weird__sha1_f4(unsigned* b, unsigned* c, unsigned* d, unsigned *output, unsigned* error_output) {
    *output = *b ^ *c ^ *d;
    error_output[0] = *output;
    return *error_output;
}
#define WEIRD_SHA1_F(r) __weird__sha1_f##r

#define _SHA1_OUT0_AEC(r) \
    *output = ROL(a, 5) + C##r + e; \
    error_output[0] = a; \
    return a & 1;
bool __weird__sha1_out0_aec1(unsigned a, unsigned e, unsigned* output, unsigned* error_output
) {_SHA1_OUT0_AEC(1);}
bool __weird__sha1_out0_aec2(unsigned a, unsigned e, unsigned* output, unsigned* error_output
) {_SHA1_OUT0_AEC(2);}
bool __weird__sha1_out0_aec3(unsigned a, unsigned e, unsigned* output, unsigned* error_output
) {_SHA1_OUT0_AEC(3);}
bool __weird__sha1_out0_aec4(unsigned a, unsigned e, unsigned* output, unsigned* error_output
) {_SHA1_OUT0_AEC(4);}

bool __weird__sha1_out0_fw(unsigned in, unsigned f, unsigned w, unsigned* output, unsigned* error_output
) {
    *output = in + f + w;
    error_output[0] = in;
    return f & 1;
}

bool __weird__sha1_out1234(unsigned* input, unsigned* output, unsigned* error_output
) {
    unsigned a = input[0];
    unsigned b = input[1];
    unsigned c = input[2];
    unsigned d = input[3];
    unsigned e = input[4];
    output[0] = 0;
    output[1] = a;
    output[2] = ROL(b, 30);
    output[3] = c;
    output[4] = d;
    error_output[0] = a;
    return a & 1;
}

#define SHA1_ROUND(input, w, output, r) \
    bool has_error; \
    unsigned err_out[SIZE] = {0}; \
    unsigned err_out_f[1] = {0}; \
    unsigned err_out0_ace[1] = {0}; \
    unsigned err_out0_fw[1] = {0}; \
\
    char votes[SIZE * UNIT_SIZE] = {0}; \
    char votes_f[UNIT_SIZE] = {0}; \
    char votes_out0_ace[UNIT_SIZE] = {0}; \
    char votes_out0_fw[UNIT_SIZE] = {0}; \
\
    unsigned a = input[0]; \
    unsigned b = input[1]; \
    unsigned c = input[2]; \
    unsigned d = input[3]; \
    unsigned e = input[4]; \
    unsigned f; \
    unsigned temp; \
    RUN_WEIRD_WITH_ERROR(&f, err_out_f, votes_f, 1, UNIT_SIZE, __weird__sha1_f##r, &b, &c, &d); \
 \
    RUN_WEIRD_WITH_ERROR(output, err_out, votes, SIZE, UNIT_SIZE, __weird__sha1_out1234, input); \
    RUN_WEIRD_WITH_ERROR(&temp, err_out0_ace, votes_out0_ace, 1, UNIT_SIZE, __weird__sha1_out0_aec##r, a, e); \
    RUN_WEIRD_WITH_ERROR(output, err_out0_fw, votes_out0_fw, 1, UNIT_SIZE, __weird__sha1_out0_fw, temp, f, w); \
    return has_error;

#define RUN_SHA1_ROUND(r, w) \
    sha1_round(states, w, new_states, r);

#define RUN_WEIRD_WITH_ERROR(output, err_out, votes, size, unit_size, f, ...) \
    do { \
        has_error = f(__VA_ARGS__, output, err_out); \
        /*if (has_error) printf("#");*/ \
        if (update_votes_general(size, unit_size, output, err_out, votes)) has_error = false; \
    } while (retry && has_error); \
    /*printf("\n");*/ \
    merge_output_general(size, unit_size, output, votes);

uint64_t time_elasped(struct timespec* begin, struct timespec* end) {
    int64_t output = end->tv_sec - begin->tv_sec;
    output *= 1000000000;
    output += end->tv_nsec - begin->tv_nsec;
    return output;
}

void ref_sha1_round(unsigned* inputs, unsigned w, unsigned* outputs, unsigned round) {
    unsigned a = inputs[0];
    unsigned b = inputs[1];
    unsigned c = inputs[2];
    unsigned d = inputs[3];
    unsigned e = inputs[4];
    const unsigned constants[4] = {C1, C2, C3, C4};

    unsigned f;
    switch(round) {
        case 0:
            f = (b & c) | ((~b) & d);
            break;
        case 1:
            f = b ^ c ^ d;
            break;
        case 2:
            f = (b & c) | (b & d) | (c & d);
            break;
        case 3:
        default:
            f = b ^ c ^ d;
            break;
    }
    unsigned temp = ROL(a, 5) + f + e + w + constants[round];

    outputs[0] = temp;
    outputs[1] = a;
    outputs[2] = ROL(b, 30);
    outputs[3] = c;
    outputs[4] = d;
}


bool update_votes_general(unsigned _SIZE, unsigned _UNIT_SIZE, unsigned* output, unsigned* error_output, char* votes) {
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

void merge_output_general(unsigned _SIZE, unsigned _UNIT_SIZE, unsigned* output, char* votes) {
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

bool update_votes(unsigned* output, unsigned* error_output, char* votes) {
    bool all_done = true;
    for (int j = 0; j < SIZE * UNIT_SIZE; ++j) {
        bool out_bit = (output[j / UNIT_SIZE] >> (j % UNIT_SIZE)) & 1;
        bool err_bit = (error_output[j / UNIT_SIZE] >> (j % UNIT_SIZE)) & 1;

        if (!err_bit) {
            if (out_bit && votes[j] < 126) ++votes[j];
            else if (!out_bit && votes[j] > -126) --votes[j];
        }
        if (votes[j] < THRESHOLD && votes[j] > -THRESHOLD) all_done = false;
    }
    return all_done;
}

void merge_output(unsigned* output, char* votes) {
    for (unsigned j = 0; j < SIZE * UNIT_SIZE; ++j) {
        if (votes[j] >= THRESHOLD) {
            output[j / UNIT_SIZE] |= 1 << (j % UNIT_SIZE);
        }
        else if (votes[j] <= -THRESHOLD) {
            output[j / UNIT_SIZE] &= ~(1 << (j % UNIT_SIZE));
        }
        votes[j] = 0;
    }
}
