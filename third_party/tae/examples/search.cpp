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
const int rerun = RERUN;
const int verbose = 0;
const int size = 512 * 1024;
unsigned tot_trials = 1000;

int data[size];
uint16_t delays[4096];

// compute the time difference
uint64_t time_elasped(struct timespec *begin, struct timespec *end)
{
  int64_t output = end->tv_sec - begin->tv_sec;
  output *= 1000000000;
  output += end->tv_nsec - begin->tv_nsec;
  return output;
}

// a weird function that runs the binary search algorithm
int bin_search(int* data, int size, int dependency) {
  int left = 0, right = size - 1, mid, target;
  uint8_t slow = delays[delays[WM::longDelay(dependency, 35)] + 3072];

  // transient execution starts
  WM::createWindow(((char*)&&end) + slow);
  // read from jmpreg
  uint64_t delay = delays[delays[slow + 2048] + 1024];

  // search target is at BTB WR with ID 0 and 1
  asm volatile(
    WR_READ_INIT(target)
    WR_READ_2(1, 0)
    "mov %%eax, %[val]\n"
    : [val]"=r"(target)
    : [target]"r"(delay)
    : "rax", "rbx"
  );

  while (left <= right) {
    mid = left + (right - left) / 2;

    if (data[mid] == target)
      break;
    else if (data[mid] < target)
      left = mid + 1; // Search right half
    else
      right = mid - 1; // Search left half
  }

  // write output at BTB WR with ID 2 and 3
  uint8_t* tblPtr = (uint8_t*)decode_table;
  WR_WRITE(2, tblPtr + (mid & 0xFFFF) * TBL_STRIDE);
  WR_WRITE(3, tblPtr + (mid >> 16) * TBL_STRIDE);
  WM::nopDelay(65536);

  // transient execution ends
  end: asm volatile("nop");
  return slow;
}

// write inputs to BTB, run the weird function, and read outputs from BTB
void wm_bin_search(int* data, int size, int target, uint8_t* output) {
  unsigned got = 0;
  // flush the cache to create delay for transient execution
  _mm_clflush(&delays[0]);
  _mm_clflush(&delays[1024]);
  _mm_clflush(&delays[2048]);
  _mm_clflush(&delays[3072]);

  // write the target value to BTB weird memory
  got = WM::randHistory();
  got += WM::write(0, target & 0xFFFF);
  got += WM::randHistory();
  got += WM::write(1, target >> 16);
  WM::fence();
  WM::nopDelay(65536);
  WM::fence();

  // run the weird machine binary search
  got += WM::randHistory();
  int delay = WM::longDelay(got, 3);
  delay = bin_search(data, size, delay);
  WM::fence();
  WM::nopDelay(10000);
  WM::fence();

  // read the result from BTB weird memory
  int readIdx = WM::longDelay(delay, 2) + 2;
  got = WM::read(readIdx, 9);
  output[0] = got & 0xFF;
  output[1] = (got >> 8) & 0xFF;
  got = WM::read(readIdx + 1, 9);
  output[2] = got & 0xFF;
  output[3] = (got >> 8) & 0xFF;
}

// rerun the weird program and run majority voting (when `count` > 1)
int rerun_bin_search(int* data, int size, int target, int count) {
  const int bytes = 4;
  uint8_t votes[bytes * 8] = {0};
  uint8_t single_output[bytes] = {0};
  uint8_t all_output[bytes * rerun];
  uint8_t output[bytes] = {0};

  for (int i = 0; i < count; i++) {
    wm_bin_search(data, size, target, single_output);
    for (int bit = 0; bit < bytes * 8; bit++) {
      if (single_output[bit / 8] & (1 << (bit % 8)) && votes[bit] < 255) {
        votes[bit]++;
      }
    }
    if (verbose) {
      for (int j = 0; j < bytes; j++) {
        all_output[i * bytes + j] = single_output[j];
      }
    }
  }

  int threshold = count / 2;
  for (int bit = 0; bit < bytes * 8; bit++) {
    if (votes[bit] > threshold) {
      output[bit / 8] |= (1 << (bit % 8));
    } else {
      output[bit / 8] &= ~(1 << (bit % 8));
    }
  }

  int ret = 0;
  for (int i = 0; i < bytes; i++) ret += output[i] << (i * 8);

  if (verbose) {
    for (int i = 0; i < count; i++) {
      printf("Run %011d: ", i + 1);
      for (int j = 0; j < bytes; j++) {
        printf("%02x ", all_output[i * bytes + j]);
      }
      printf("\n");
    }
    printf("Final output:    ");
    for (int j = 0; j < bytes; j++) {
      printf("%02x ", output[j]);
    }
    printf("\n");
  }
  return ret;
}

// choose a random target from data and check the output
unsigned test_search(unsigned in) {
  int answer = rand() % size, target = data[answer];

  int got = rerun_bin_search(data, size, target, rerun);

  if (verbose) {
    printf("Expected output: %02x\n\n", answer);
  }

  return answer != got;
}

// init data with random ascending values
void init() {
  const int stride = 128;
  for (int i = 0; i < size; i++) {
    data[i] = i * stride + rand() % stride;
  }
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

  init();
  test_acc("Binary Search", 4, test_search);

  WM::cleanup();
}
