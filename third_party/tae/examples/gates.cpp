#include <stdio.h>
#include <time.h>
#include "WeirdMachine.h"

/* Config */
const bool verbose = false;
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

// write to one WR and read the value
unsigned test_basic_read(unsigned in)
{
  unsigned result, output = 0, error;
  int input = in & 0xFFFF;
  unsigned got = WM::write(0, input);
  WM::nopDelay(512);

  // read after write has returned
  output = WM::read(0 + WM::longDelay(got, 2), 7);
  error = output >> 16;
  output &= 0xFFFF;
  if (verbose)
  {
    printf("Input: %x, Output: %x, Error: %x\n", input, output, error);
  }
  result = (error > 0) << 1;
  result |= input != output;
  return result;
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

int main(int argc, char *argv[])
{
  srand(time(NULL));
  WM::init();

  test_acc("basic read", 4, test_basic_read);

  WM::cleanup();
}
