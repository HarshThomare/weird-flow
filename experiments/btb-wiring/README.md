# BTB cross-function wiring kill test

Smallest check of the workshop claim that is not another Flexo decompiler: on one Transient Architectural Execution (TAE) style program, a value written into a branch-target-buffer slot in one function can be recovered as a read of that same slot in another function.

The substrate is the one already in `third_party/tae` (`jmpregN: jmp *%rbx`, `decode_table` entries of `movw $imm, %ax; ret`). See `RESULTS.md` for the verdict.

## Run

```bash
python3 experiments/btb-wiring/run.py
```

Needs `gcc`, `g++`, `objdump`, `strip`, and the repo's `capstone` and `pyelftools` packages.

The script rebuilds two ELFs under `build/`, writes `logs/`, and rewrites `RESULTS.md`.

## What it builds

| file | role |
| --- | --- |
| `fixture/substrate.S` | 16 BTB slots and a 256-entry decode table |
| `fixture/wiring.S` | scheduled driver/weird program, executed by the software oracle |
| `fixture/wiring.cc` | g++ -O2 program using the real `WM::write` / `WR_READ` / `WR_WRITE` macros |
| `recover.py` | static write/read sites and cross-function edges |
| `oracle.py` | non-destructive BTB model plus the ret-hijack window |
| `run.py` | build, checks, logs, verdict |

`driver_neg` writes slot 0 and `weird_neg` reads slot 7. That pair must not become an edge. `driver_opaque` reads `opaque_zero()+5` and must stay a partial slot, not a guessed concrete id.

No CPU BTB experiment is run. WeMu is not in this tree.
