#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <argp.h>
#include <time.h>
#include <vector>
#include <x86intrin.h>
#include "WeirdMachine.h"
#include "simon.h"

#ifndef RERUN
#define RERUN 1
#endif

/* Config */
const int rerun = RERUN;
const int verbose = 0;
const bool random_key = 1;
unsigned tot_trials = 1000;

uint16_t delays[4096];

// compute the time difference
uint64_t time_elasped(struct timespec *begin, struct timespec *end)
{
  int64_t output = end->tv_sec - begin->tv_sec;
  output *= 1000000000;
  output += end->tv_nsec - begin->tv_nsec;
  return output;
}

// reference Simon encryption
void ref_simon_encrypt(const uint8_t* input, const uint8_t* key, uint8_t* output) {
  uint16_t x = input[1] | (input[0] << 8);
  uint16_t y = input[3] | (input[2] << 8);
  uint16_t keys[ROUNDS];
  uint16_t tmp;

  for (int i = 0; i < 4; ++i) {
    keys[3 - i] = key[i * 2 + 1] | (key[i * 2] << 8);
  }
  for (int i = 4; i < ROUNDS; ++i) {
    tmp = ROR(keys[i - 1], 3);
    tmp ^= keys[i - 3];
    tmp ^= ROR(tmp, 1);
    keys[i] = ~keys[i - 4] ^ tmp ^ 3 ^ ((z0 >> (i - 4)) & 1);
  }
  for (int i = 0; i < ROUNDS; ++i) {
    SIMON_ROUND(x, y, keys[i]);
  }
  output[0] = x >> 8;
  output[1] = x;
  output[2] = y >> 8;
  output[3] = y;
}

/* 
  Simon encryption weird functions
  Each weird function encrypts four rounds
*/
int simon_encrypt1(int dependency) {
  GATE_PROLOGUE;
  LOAD_INPUT(0, 1, 2, 3, 4, 5);

  SIMON_ROUND(x, y, k0);
  SIMON_ROUND(x, y, k1);
  SIMON_ROUND(x, y, k2);
  SIMON_ROUND(x, y, k3);

  WRITE_OUTPUT(6, 7, 8, 9, 10, 11);
  GATE_EPILOGUE;
}

int simon_encrypt2(int dependency) {
  GATE_PROLOGUE;
  LOAD_INPUT(6, 7, 8, 9, 10, 11);
  SIMON_FOUR_ROUNDS(4);
  WRITE_OUTPUT(12, 13, 14, 15, 16, 17);
  GATE_EPILOGUE;
}

int simon_encrypt3(int dependency) {
  GATE_PROLOGUE;
  LOAD_INPUT(12, 13, 14, 15, 16, 17);
  SIMON_FOUR_ROUNDS(8);
  WRITE_OUTPUT(18, 19, 20, 21, 22, 23);
  GATE_EPILOGUE;
}

int simon_encrypt4(int dependency) {
  GATE_PROLOGUE;
  LOAD_INPUT(18, 19, 20, 21, 22, 23);
  SIMON_FOUR_ROUNDS(12);
  WRITE_OUTPUT(24, 25, 26, 27, 28, 29);
  GATE_EPILOGUE;
}

int simon_encrypt5(int dependency) {
  GATE_PROLOGUE;
  LOAD_INPUT(24, 25, 26, 27, 28, 29);
  SIMON_FOUR_ROUNDS(16);
  WRITE_OUTPUT(30, 31, 32, 33, 34, 35);
  GATE_EPILOGUE;
}

int simon_encrypt6(int dependency) {
  GATE_PROLOGUE;
  LOAD_INPUT(30, 31, 32, 33, 34, 35);
  SIMON_FOUR_ROUNDS(20);
  WRITE_OUTPUT(36, 37, 38, 39, 40, 41);
  GATE_EPILOGUE;
}

int simon_encrypt7(int dependency) {
  GATE_PROLOGUE;
  LOAD_INPUT(36, 37, 38, 39, 40, 41);
  SIMON_FOUR_ROUNDS(24);
  WRITE_OUTPUT(42, 43, 44, 45, 46, 47);
  GATE_EPILOGUE;
}

int simon_encrypt8(int dependency) {
  GATE_PROLOGUE;
  LOAD_INPUT(42, 43, 44, 45, 46, 47);
  SIMON_FOUR_ROUNDS(28);
  uint8_t* tblPtr = (uint8_t*)decode_table;
  WR_WRITE(48, tblPtr + x * TBL_STRIDE);
  WM::nopDelay(4);
  WR_WRITE(49, tblPtr + y * TBL_STRIDE);
  GATE_EPILOGUE;
}

// write inputs to BTB, run the weird functions, and read outputs from BTB
unsigned wm_simon_encrypt(const uint8_t* input, const uint8_t* key, uint8_t* output) {
  unsigned got;
  // write input and key to BTB
  got = WM::randHistory();
  got = WM::write(0, input[1] + (input[0] << 8));
  got = WM::write(1, input[3] + (input[2] << 8));
  for (int i = 0; i < 4; i++) {
    got = WM::randHistory();
    i += WM::longDelay(got, 3);
    got = WM::write(i + 2, key[2 * i + 1] + (key[2 * i] << 8));
  }
  WM::fence();
  WM::nopDelay(65536);
  WM::fence();

  // flush the cache to create delay for transient execution
  for (int i = 0; i < ROUNDS / 4; i++) {
    _mm_clflush(&delays[0]);
    _mm_clflush(&delays[1024]);
    _mm_clflush(&delays[2048]);
    _mm_clflush(&delays[3072]);
    WM::fence();

    got += WM::randHistory();
    WM::nopDelay(16384);

    if (i == 0) got = simon_encrypt1(got);
    else if (i == 1) got = simon_encrypt2(got);
    else if (i == 2) got = simon_encrypt3(got);
    else if (i == 3) got = simon_encrypt4(got);
    else if (i == 4) got = simon_encrypt5(got);
    else if (i == 5) got = simon_encrypt6(got);
    else if (i == 6) got = simon_encrypt7(got);
    else got = simon_encrypt8(got);

    WM::fence();
  }

  WM::nopDelay(10000);
  WM::fence();
  // read output from BTB
  for (int i = 0; i < 2; i++) {
    int readIdx = WM::longDelay(got + i, 3) + i + 48;
    got = WM::read(readIdx, 9);
    output[2 * i + 1] = got & 0xFF;
    output[2 * i] = (got >> 8) & 0xFF;
  }
  return got;
}

// rerun the weird program and run majority voting (when `count` > 1)
void rerun_simon(uint8_t* input, uint8_t* key, uint8_t* output, int count) {
  uint8_t votes[32] = {0};
  uint8_t single_output[4] = {0};
  uint8_t all_output[4 * rerun];
  for (int i = 0; i < count; i++) {
    wm_simon_encrypt(input, key, single_output);
    for (int bit = 0; bit < 32; bit++) {
      if (single_output[bit / 8] & (1 << (bit % 8)) && votes[bit] < 255) {
        votes[bit]++;
      }
    }
    if (verbose) {
      for (int j = 0; j < 4; j++) {
        all_output[i * 4 + j] = single_output[j];
      }
    }
  }

  int threshold = count / 2;
  for (int bit = 0; bit < 32; bit++) {
    if (votes[bit] > threshold) {
      output[bit / 8] |= (1 << (bit % 8));
    } else {
      output[bit / 8] &= ~(1 << (bit % 8));
    }
  }
  if (!verbose) return;
  for (int i = 0; i < count; i++) {
    printf("Run %011d: ", i + 1);
    for (int j = 0; j < 4; j++) {
      printf("%02x ", all_output[i * 4 + j]);
    }
    printf("\n");
  }
  printf("Final output:    ");
  for (int j = 0; j < 4; j++) {
    printf("%02x ", output[j]);
  }
  printf("\n");
}

// run both normal and weird Simon and compare outputs
unsigned test_simon(unsigned in) {
  uint8_t key[8], input[4];
  uint8_t ref_output[4] = {0};
  uint8_t wm_output[4] = {0};

  // init Simon key and input with random values
  if (random_key) {
    ((unsigned*)key)[0] = rand();
    ((unsigned*)key)[1] = rand();
    ((unsigned*)input)[0] = rand();
  } else {
    ((unsigned*)key)[0] = 0xdeadbeef;
    ((unsigned*)key)[1] = 0xfaceb00c;
    ((unsigned*)input)[0] = 0x12345678;
  }

  ref_simon_encrypt(input, key, ref_output);
  rerun_simon(input, key, wm_output, rerun);

  if (verbose) {
    printf("Expected output: ");
    for (int j = 0; j < 4; j++) {
      printf("%02x ", ref_output[j]);
    }
    printf("\n\n");
  }

  for (int i = 0; i < 4; i++) {
    if (ref_output[i] != wm_output[i]) return 1;
  }
  return 0;
}

/* Test the accuracy and time usage of a gate */
void test_acc(
  const char *name,
  unsigned input_size,
  unsigned (*gate_fn)(unsigned))
{
  const unsigned in_space = 1 << input_size;
  unsigned tot_correct_counts = 0, tot_detected_counts = 0, tot_error_counts = 0;
  unsigned all0_errors = 0, all1_errors = 0;
  struct timespec ts_start;
  struct timespec ts_end;
  clock_gettime(CLOCK_MONOTONIC, &ts_start);

  for (unsigned seed = 0; seed < tot_trials; seed++)
  {
    unsigned result = gate_fn(rand());

    if (result == 0)
    {
      ++tot_correct_counts;
    }
    else if (result & 2)
    {
      ++tot_detected_counts;
    }
    else
    {
      ++tot_error_counts;
    }
  }

  clock_gettime(CLOCK_MONOTONIC, &ts_end);
  uint64_t tot_ns = time_elasped(&ts_start, &ts_end);

  printf("=== %s ===\n", name);
  printf("Accuracy: %.5f%%, ", (double)tot_correct_counts / tot_trials * 100);
  printf("Error detected: %.5f%%, ", (double)tot_detected_counts / tot_trials * 100);
  printf("Undetected error: %.5f%%\n", (double)tot_error_counts / tot_trials * 100);
  uint64_t time_per_run = tot_ns / tot_trials;
  printf("Time usage: %lu.%lu (us)\n", time_per_run / 1000, time_per_run % 1000);
  printf("over %d iterations.\n", tot_trials);
}

/* Arguments */
static char doc[] = "Test the accuracy and run time of weird machines.";
static char args_doc[] = "";
static struct argp_option options[] = {
  {"verbose", 'v', 0, 0, "Produce verbose output"},
  {"trial", 't', "TRIAL", 0, "Number of trials (default: 100000)."},
  {0}
};
static error_t parse_opt(int key, char *arg, struct argp_state *state)
{
  switch (key)
  {
  // case 'v': verbose = true; break;
  case 't':
    tot_trials = atoi(arg);
    break;
  case ARGP_KEY_ARG:
    return 0;
  default:
    return ARGP_ERR_UNKNOWN;
  }
  return 0;
}
static struct argp argp = {options, parse_opt, args_doc, doc, 0, 0, 0};

int main(int argc, char *argv[])
{
  argp_parse(&argp, argc, argv, 0, 0, 0);
  srand(time(NULL));
  WM::init();
  delays[63] = 1;
  for (int i = 0; i < 0xFFFF; i++) {
    WM::write(1, i);
  }

  test_acc("SIMON", 4, test_simon);

  WM::cleanup();
}
