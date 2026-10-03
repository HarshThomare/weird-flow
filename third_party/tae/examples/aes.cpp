#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <argp.h>
#include <time.h>
#include <vector>
#include <x86intrin.h>
#include "WeirdMachine.h"

#ifndef RERUN
#define RERUN 1
#endif

/* Config */
const int verbose = 0;
const int rerun = RERUN;
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

// asm macro for AES round key generation
asm(
  ".macro round_key RCON\n"
  "  aeskeygenassist \\RCON, %xmm0, %xmm1\n"
  "  pshufd $0b11111111, %xmm1, %xmm1\n"
  "  shufps $0b00010000, %xmm0, %xmm2\n"
  "  pxor %xmm2, %xmm0\n"
  "  shufps $0b10001100, %xmm0, %xmm2\n"
  "  pxor %xmm2, %xmm0\n"
  "  pxor %xmm1, %xmm0\n"
  ".endm\n"
);

// macro for an AES round
#define AES_ROUND(rcon) "round_key $" #rcon "\naesenc %%xmm0,  %%xmm3\n"
#define AES_LAST_ROUND(rcon) "round_key $" #rcon "\naesenclast %%xmm0,  %%xmm3\n"

// reference AES encryption (128-bit block)
void ref_aes_encrypt(const uint8_t* input, const uint8_t* key, uint8_t* output) {
  asm volatile(
    "movaps (%[key]), %%xmm0\n"
    "movaps (%[input]), %%xmm3\n"
    "pxor %%xmm2, %%xmm2\n"
    "pxor %%xmm0, %%xmm3\n"
    AES_ROUND(1)
    AES_ROUND(2)
    AES_ROUND(4)
    AES_ROUND(8)
    AES_ROUND(16)
    AES_ROUND(32)
    AES_ROUND(64)
    AES_ROUND(128)
    AES_ROUND(27)
    AES_LAST_ROUND(54)
    "movaps %%xmm3, (%[output])\n"
    :: [key]"r"(key), [input]"r"(input), [output]"r"(output) : "xmm0", "xmm1", "xmm2", "xmm3"
  );
}

// a weird function that encrypts one AES block using AES-NI
int aes_encrypt(int dependency) {
  uint8_t slow = delays[delays[WM::longDelay(dependency, 35)] + 3072];
  uint64_t val0, val1;

  // transient execution starts
  WM::createWindow(((char*)&&end) + slow);
  // read from jmpreg
  uint64_t delay = delays[delays[slow + 2048] + 1024];

  asm volatile(
    WR_READ_INIT(target)
    // mov input to xmm3
    WR_READ_4(3, 2, 1, 0)
    "vmovq %%rax, %%xmm3\n"
    WR_READ_4(7, 6, 5, 4)
    "pinsrq $1, %%rax, %%xmm3\n"
    // mov key to xmm0
    WR_READ_4(11, 10, 9, 8)
    "vmovq %%rax, %%xmm0\n"
    WR_READ_4(15, 14, 13, 12)
    "pinsrq $1, %%rax, %%xmm0\n"
    "pxor %%xmm2, %%xmm2\n"
    "pxor %%xmm0, %%xmm3\n"
    AES_ROUND(1)
    AES_ROUND(2)
    AES_ROUND(4)
    AES_ROUND(8)
    AES_ROUND(16)
    AES_ROUND(32)
    AES_ROUND(64)
    AES_ROUND(128)
    AES_ROUND(27)
    AES_LAST_ROUND(54)
    "movq %%xmm3, %[val0]\n"
    "movhlps %%xmm3, %%xmm3\n"
    "movq %%xmm3, %[val1]\n"
    : [val0]"=r"(val0), [val1]"=r"(val1) : [target]"r"(delay) : "rax", "rbx", "xmm0", "xmm1", "xmm2", "xmm3"
  );
  uint8_t* tblPtr = (uint8_t*)decode_table;
  WR_WRITE(16, tblPtr + (val0 & 0xFFFF) * TBL_STRIDE);
  WR_WRITE(17, tblPtr + ((val0 >> 16) & 0xFFFF) * TBL_STRIDE);
  WR_WRITE(18, tblPtr + ((val0 >> 32) & 0xFFFF) * TBL_STRIDE);
  WR_WRITE(19, tblPtr + ((val0 >> 48) & 0xFFFF) * TBL_STRIDE);
  WR_WRITE(20, tblPtr + (val1 & 0xFFFF) * TBL_STRIDE);
  WR_WRITE(21, tblPtr + ((val1 >> 16) & 0xFFFF) * TBL_STRIDE);
  WR_WRITE(22, tblPtr + ((val1 >> 32) & 0xFFFF) * TBL_STRIDE);
  WR_WRITE(23, tblPtr + ((val1 >> 48) & 0xFFFF) * TBL_STRIDE);
  WM::nopDelay(65536);

  // transient execution ends
  end: asm volatile("nop");
  return slow;
}

// write inputs to BTB, run the weird function, and read outputs from BTB
void wm_aes_encrypt(uint8_t* input, uint8_t* key, uint8_t* output) {
  unsigned got = 0;
  // flush the cache to create delay for transient execution
  _mm_clflush(&delays[0]);
  _mm_clflush(&delays[1024]);
  _mm_clflush(&delays[2048]);
  _mm_clflush(&delays[3072]);

  // write input and key to BTB
  for (int i = 0; i < 8; i++) {
    got += WM::randHistory();
    i += WM::longDelay(got, 3);
    got = WM::write(i, input[2 * i] + (input[2 * i + 1] << 8));
    got += WM::randHistory();
    got = WM::write(i + 8, key[2 * i] + (key[2 * i + 1] << 8));
  }
  WM::fence();
  WM::nopDelay(65536);
  WM::fence();

  // run AES encryption
  got += WM::randHistory();
  int delay = WM::longDelay(got, 3);
  delay = aes_encrypt(delay);
  WM::fence();
  WM::nopDelay(10000);
  WM::fence();

  for (int i = 0; i < 8; i++) {
    int readIdx = WM::longDelay(delay + i, 2) + i + 16;
    got = WM::read(readIdx, 9);
    output[i*2] = got & 0xFF;
    output[i*2 + 1] = (got >> 8) & 0xFF;
  }
}

// rerun the weird program and run majority voting (when `count` > 1)
void rerun_aes(uint8_t* input, uint8_t* key, uint8_t* output, int count) {
  uint8_t votes[128] = {0};
  uint8_t single_output[16] = {0};
  uint8_t all_output[16 * rerun];
  for (int i = 0; i < count; i++) {
    wm_aes_encrypt(input, key, single_output);
    for (int bit = 0; bit < 128; bit++) {
      if (single_output[bit / 8] & (1 << (bit % 8)) && votes[bit] < 255) {
        votes[bit]++;
      }
    }
    if (verbose) {
      for (int j = 0; j < 16; j++) {
        all_output[i * 16 + j] = single_output[j];
      }
    }
    WM::fence();
    WM::nopDelay(10);
    WM::fence();
  }

  int threshold = count / 2;
  for (int bit = 0; bit < 128; bit++) {
    if (votes[bit] > threshold) {
      output[bit / 8] |= (1 << (bit % 8));
    } else {
      output[bit / 8] &= ~(1 << (bit % 8));
    }
  }
  if (!verbose) return;
  for (int i = 0; i < count; i++) {
    printf("Run %011d: ", i + 1);
    for (int j = 0; j < 16; j++) {
      printf("%02x ", all_output[i * 16 + j]);
    }
    printf("\n");
  }
  printf("Final output:    ");
  for (int j = 0; j < 16; j++) {
    printf("%02x ", output[j]);
  }
  printf("\n");
}

// run both normal and weird AES and compare outputs
unsigned test_aes(unsigned in) {
  uint8_t key[16], input[16];
  uint8_t ref_output[16] = {0};
  uint8_t wm_output[16] = {0};

  // init AES key and input with random
  for (int i = 0; i < 4; i++) {
    ((unsigned*)key)[i] = rand();
    ((unsigned*)input)[i] = rand();
  }

  ref_aes_encrypt(input, key, ref_output);
  rerun_aes(input, key, wm_output, rerun);

  if (verbose) {
    printf("Expected output: ");
    for (int j = 0; j < 16; j++) {
      printf("%02x ", ref_output[j]);
    }
    printf("\n\n");
  }

  for (int i = 0; i < 16; i++) {
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

  test_acc("AES", 4, test_aes);

  WM::cleanup();
}
