# Localization is a symmetry / periodicity problem

µWM trigger/decode localization is the same thing DSP does to a wave. A
weird machine **copies two idioms** (window-open/decode-style n-grams) at a
roughly regular spacing along `.text`. That spacing is a discrete spatial
period, analogous to a sine’s temporal period. You do not need an opcode
pack: the period is a property of **translational symmetry** in the
instruction stream.

## DSP dictionary

| DSP | Here |
| --- | --- |
| Waveform | 1-bit (or log-count) *repeatness* along address: `r[x] = 1` iff insn `x` sits in a repeated n-gram |
| Autocorrelation `R(τ)` | Peak at the DualGate/gadget period (same role as pitch) |
| FFT / periodogram | A line at spatial frequency `1/P` (same role as FFT of a sine; a pulse train also shows harmonics) |
| Cross-correlation of two channels | Stable lag = pairing offset of the two co-located n-gram families |
| Eckmann recurrence | Pulse×pulse lattice: each copy is a dark spot; the grid spacing *is* the period |
| Cross-build key intersection | Matched filter / coherent integration (diffing) |

## ISA-agnostic by construction

Signals are built from `experiment/repeat miner/miner.py` n-grams with:

- `n = 6`
- abstract registers **on**, abstract immediates **off**
- nop-only keys dropped
- a key counts as repeated at `count ≥ 2`

No `clflush` / `rdtsc` / `ret` list is consulted. DualGate and `jmpreg`
symbols are loaded **only to annotate** the figures (gold ticks). The
period, FFT peak, and two-family lag are measured from `r(x)`.

Family A vs B is Jaccard clustering of n-gram *sites* (sliding windows of
one idiom merge; two idioms do not), with a phase-mod-`P` split if a bucket
still looks like one blob. Cross-correlation of the two membership trains
is the pair.

## What the binaries showed

Replica spacing is voted from high-copy, low-CV n-gram keys
(`score = n_copies² · P`). DSP then runs on a Gaussian envelope of **one**
family’s onsets (a Dirac comb). Mixing both families inside a DualGate
makes the first autocorr peak the intra-gate lag instead of `P`.

| Binary | Symbol spacing | Voted `P` | Autocorr `τ` (`R`) | FFT `P` (SNR vs band mean) | Two-family lag (peak) |
| --- | --- | --- | --- | --- | --- |
| Flexo `test.elf` (8 DualGates) | 576 B | 592 B | 585 B (0.38) | 607 B (7.6) | **515 B (0.82)** |
| Flexo `ALU.elf` (12 DualGates) | 656 B | **656 B** | 606 B (0.26) | 712 B (9.5) | **515 B (0.92)** |
| Flexo `sbox.elf` (28 DualGates) | 736 B | 728 B | 732 B (0.44) | **728 B (11.5)** | 522 B (0.93) |
| GITM `and_timing.elf` (19 gates) | 656 B | **656 B** | **658 B (0.36)** | **655 B (22)** | **515 B (1.00)** |
| Flexo-DCache `test.elf` | 576 B | 624 B | 620 B | 683 B (5.0) | no stable pair (one family) |
| Flexo-TLB `test.elf` | 584 B | 784 B | 783 B | 862 B (3.7) | no stable pair |
| Flexo `and.elf` (1 DualGate) | — | none | intra-gate only | — | single copy, no period |
| TAE `gates.elf` (1024 `jmpreg`) | **32 B** | **32 B** | **32 B (R = 1.00)** | **32 B** | **trap** (see below) |
| SIMD saxpy clones | — | 64 B | 64 B (0.83) | 64 B, harmonic series | lag 8 B = n-gram slide of **one** kernel |
| unrolled crypto | — | 16 B | 16 B | messy / 16 B | not a DualGate pair |
| C++ templates | — | none | none | none | no drop-nop repeats |

The **515–522 B** lag on Flexo test / ALU / sbox / GITM is the DualRet nop
sled (~512 one-byte nops) between the decode-load n-gram
(`mov … [REG+REG+0x100] · nop⁵`) and the epilogue n-gram (`nop⁵ · pop`).
That is the pairing gap, measured without naming those mnemonics up front.
GITM is the cleanest spectral line because 19 copies are almost equally
spaced; ALU’s last DualGate is larger, so the FFT of the irregular comb
sits a bit above the median 656 B.

### TAE is the cautionary plot

`jmpreg` is **one** huge clone class: 1024 copies of `jmp REG` plus a
fixed pad, period **exactly 32 B**, autocorrelation a cosine of amplitude
~1, periodogram a Dirac comb at `k/32`. That is a single frequency, and it
looks like a perfect FFT of a wave. It is **not** trigger+decode. The
second “family” at this period has 3 hits vs 1021 and cross-correlation
peak 0.05 — no pair. Two-family lag is what isolates a µWM; a single
clone class of 1024 jmps does not.

### Hard negatives

SIMD is honest repetition: six identical kernels, period 64 B, one idiom,
harmonic series in the FFT, no DualGate-scale pair. Crypto is a short
unroll (16 B), not two co-located motifs. Templates produce no repeated
drop-nop 6-grams under register abstraction with immediates kept.

Diffing (cross-build intersection of repeated keys) is the discrete
matched filter: keys that survive in two views are coherent; a nop sled
that is unique to one build drops out.

## How to state the root cause

Localization works because the weird machine is a **periodic spatial
process** on `.text`. The miner’s n-grams are just a 1-D feature that
makes that periodicity visible. Autocorrelation reads the period,
the FFT makes it a line, two-family cross-correlation reads the
trigger/decode (or decode/epilogue) offset, and the recurrence lattice
is the copies. Opcode catalogs are a special case of “we already know
which two pulses.” The general object is the symmetry.

## Reproduce

```bash
python3 experiment/symmetry/plot_symmetry.py
```

Writes `figures/*.png` + `*.svg` and `measurements.json`. Needs numpy,
matplotlib, capstone, pyelftools (already in `requirements.txt` plus
matplotlib/numpy on this machine). Does not import `src/wf`.

Hero figures: `figures/gitm_and_combined.{png,svg}` (cleanest line),
`figures/flexo_alu_two_family.{png,svg}` (pairing lag),
`figures/tae_jmpreg_trap.{png,svg}` (single-family trap).
