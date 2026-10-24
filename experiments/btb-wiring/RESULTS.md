# BTB weird-register wiring: kill test

**Verdict: PASS**

Kill question: can cross-function dataflow through a non-destructive BTB slot be recovered on one TAE-style program, and does a software model of that slot actually carry the value after architectural state is cleared?

This does not re-run Flexo netlist recovery. The existing n-gram diff locator in `src/wf/mine.py` is a different analysis and is not the oracle here.

## Method

The substrate is the TAE indirect-jump register from `third_party/tae/include/WeirdStates/IndirectJmp.h` and `src/WeirdStates/IndirectJmp.cpp`: `jmpregN` is `jmp *%rbx` on a 32-byte stride, and `decode_table` is `movw $value, %ax; ret` on a 5-byte stride. A write calls the slot with `rbx` pointing at a table entry. A read calls the same slot with `rbx` pointing elsewhere. The ret-hijack window is `create_window` from `TransientWindows/RetBased.cpp`.

Two fixtures share that substrate:

- `fixture/wiring.S` is a scheduled two-function program. `driver` writes slots 0 and 1, zeroes every general register and `arch_channel`, calls `weird`, then reads slots 2 and 4. `weird` reads slot 0 twice and slot 1 inside the window and writes the sum and the echoed input. `driver_neg` / `weird_neg` write slot 0 and read slot 7.
- `fixture/wiring.cc` is the same shape compiled with g++ -O2, calling the real `WM::write`, `WM::readTransient`, `WR_READ`, and `WR_WRITE` macros. `driver_opaque` reads slot `opaque_zero()+5`.

Recovery is a forward register slice inside each function, then a one-level call-graph join: a write reaches a read of the same slot in a callee entered before the next write, and a callee's last write reaches a read after the call returns. The oracle executes the assembly fixture under that contract. Ablations turn off transient BTB updates and BTB reads separately.

Host CPU: Intel(R) Xeon(R) Processor. WeMu path `/u/hthomare/weird-machines/artifacts/WeMu` present: False. Native TAE was not run. The TAE sources say results on an unsupported processor are not evidence, and this oracle does not claim silicon BTB persistence.

## Checks

| check | result | detail |
| --- | --- | --- |
| substrate | PASS | slots=16 at 0x402000, entries=256 at 0x403000, via symbols |
| asm cross-function pairs | PASS | got [('driver', 'weird', 0), ('driver', 'weird', 1), ('weird', 'driver', 2), ('weird', 'driver', 4)] |
| asm unknown mnemonics | PASS | none |
| stripped edges keep the same pcs | PASS | stripped via call-targets, pcs match=True |
| oracle returns the sum | PASS | eax=0x33 |
| probe has no architectural copy of the inputs | PASS | leaked=none, arch_channel=0, store_hit=True |
| window resume squashes the transient sum | PASS | resumes=1 rax=0 r12=0 |
| non-destructive double read of slot 0 | PASS | reads=2 slot0=17 slot4=17 |
| oracle transfers match recovered edges | PASS | transfers=[('driver', 'weird', 0), ('driver', 'weird', 1), ('weird', 'driver', 2), ('weird', 'driver', 4)] slot2=51 |
| ablation: transient BTB writes discarded | PASS | eax=0xffff |
| ablation: BTB reads disabled | PASS | eax=0xffff |
| mismatched slots do not transfer | PASS | eax=0xffff, negative pairs=[] |
| compiler -O2 cross-function pairs | PASS | got [('driver_c', 'weird_c', 0), ('driver_c', 'weird_c', 1), ('weird_c', 'driver_c', 2)] |
| compiler unknown mnemonics | PASS | none |
| opaque index stays partial at base 5 | PASS | partials=1 slot5_writes=1 concrete_reads=0 dyn=['opaque_zero'] |
| compiler negative pair is not wired | PASS | bad=[] |

## What the edges are

Assembly cross-function edges:

- `driver` `0x401013` writes btb[0] → `weird` `0x4010a1` reads it
- `driver` `0x401013` writes btb[0] → `weird` `0x4010b2` reads it
- `driver` `0x40102b` writes btb[1] → `weird` `0x4010c3` reads it
- `weird` `0x4010e2` writes btb[2] → `driver` `0x401072` reads it
- `weird` `0x4010fb` writes btb[4] → `driver` `0x401083` reads it

Compiler cross-function edges:

- `driver_c` `0x40107d` writes btb[0] → `weird_c` `0x401019` reads it
- `driver_c` `0x40107d` writes btb[0] → `weird_c` `0x401026` reads it
- `driver_c` `0x401099` writes btb[1] → `weird_c` `0x401033` reads it
- `weird_c` `0x40104c` writes btb[2] → `driver_c` `0x4010b4` reads it
- `weird_c` `0x40104c` writes btb[2] → `driver_c` `0x4010be` reads it

## Diff-miner baseline

`mine_path` on the assembly fixture: {"available": true, "n_pairs": 0, "note": "n-gram diff pairs are not BTB slot edges"}.

The diff miner clusters repeated instruction n-grams. On this fixture it emitted no pairs, so the slot edges above are outside that analysis. TAE in the existing pipeline stays a localization result for the same reason.

## Hardware gap

The output edge is only live in the oracle when transient writes to the BTB are kept and reads consult the BTB instead of `rbx`. That is the weird-register contract. It is not a measurement on this Xeon. A workshop follow-up on a CPU where the TAE `gates` / `search` binaries are known to be accurate would compare `WM::read` of the recovered slots with the oracle's values.

Constant slot ids in `WR_READ` / `WR_WRITE` and inlined `WM::write(constant, ...)` are concrete. `driver_opaque` is the `readIdx = opaque()+k` shape used by `examples/search.cpp` (`longDelay(...) + 2`). The constant 5 survives; `opaque_zero` does not fold. Proving the delay returns 0 is future work, not this kill test.

## Next steps

- Re-run the recovered search/AES edges on a supported TAE CPU and compare them to `WM::read` output.
- Add a delay analysis that shows `longDelay` is architecturally 0 so the search driver's output slots collapse from `base+opaque` to a concrete id.
- The cache-timing half of `WM::read` is a separate channel. This test only recovers the BTB operand of that read.

## Reproduce

```
python3 experiments/btb-wiring/run.py
```

Requires gcc, g++, binutils, capstone, and pyelftools. Raw logs are in `experiments/btb-wiring/logs/`.

