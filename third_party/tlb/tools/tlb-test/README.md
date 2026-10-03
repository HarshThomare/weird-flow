# TLB Test Tools

> **Requires the kernel module** (`../../kernel/`) to be loaded before use.

| Tool | Description |
|---|---|
| `threshold` | Measures TLB translation stage timings and recommends a hit/miss threshold |
| `test_window` | Measures Page Table Walk completions inside a transient window |

## threshold

Measures the timing for each TLB translation stage (L1 hit, L2 hit, L2 miss, full PTW) and suggests a good threshold value to distinguish TLB hits from misses.

Configure the number of sets and ways for your CPU in `threshold.h` before building.

```bash
make threshold
taskset -c <CPU> ./threshold.elf
```

Example output:

```
L1 Hit:         (min mean meanLimited max) (84, 96.865220, 97.815311, 664)      -> (90, 96, 102)
L2 Hit:         (min mean meanLimited max) (84, 125.101960, 127.956756, 520)    -> (108, 130, 140)
L2 Miss:        (min mean meanLimited max) (110, 151.121980, 154.580578, 646)   -> (126, 142, 178)
Full PTW:       (min mean meanLimited max) (156, 198.656400, 201.009733, 13532) -> (182, 204, 210)
Try thresholds between 126 - 142
Recommended thresholds TLB: 138 or 139
But also consider finetune this in the range 136 - 141
```

## test_window

Measures how many Page Table Walks complete within a transient window of a given size. Sweeps over window sizes and instruction types (DIV/MUL/ADD) and writes results to `.csv` files.

The instruction chain that opens the transient window is defined in `window_call_ret.S`. Use `generate_asm.py` to regenerate it with a different instruction count (configured in its `main` function).

```bash
python3 test_window.py <CPU> <THRESHOLD> <ITERATIONS> <SUFFIX> [NR_TARGET_LOADS]
```

| Argument | Description |
|---|---|
| `CPU` | CPU core to pin to, e.g. `6` |
| `THRESHOLD` | Timing threshold to distinguish TLB hit from miss (see `threshold` above) |
| `ITERATIONS` | Number of iterations per instruction type per window size |
| `SUFFIX` | Suffix appended to output `.csv` / numpy data files |
| `NR_TARGET_LOADS` | *(Optional)* Target number of loads to complete inside the window; switches mode from data collection to window-length tuning |
