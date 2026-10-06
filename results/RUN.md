# Weird Flow corpus runs

**Commits:** `a747bfa` (torch 2.6.0+cu124 pin) · `88b804b` (symmetry locator + stage dumps) · `a975449` (cap family merge; CPU live LLM fallback)

**pytest:** 19 passed, 1 skipped (`test_live_qwen_flexo_judge_decompile` without `WF_LIVE_LLM` in that invocation). Live Qwen did run on Flexo/GITM/TLB in the corpus.

**Torch / CUDA:** wheel `2.6.0+cu124`, `torch.version.cuda=12.4`. Sanity with `CUDA_VISIBLE_DEVICES=2`: `is_available()=True`. During the corpus, GPU 2 had ~5 GiB free (ali `serve_policy`), GPU 0/1 held `mp_train` plus another Qwen job, so live Qwen used **CPU** (`CUDA_VISIBLE_DEVICES=""`) rather than crowding those jobs. Driver 550.144.03.

**Run B:** **yes**. `experiment/symmetry` shows Flexo test/ALU/sbox and GITM `and_timing` DualGate-scale period + FFT line + ~515 B two-family lag. Plots copied to `results/run-symmetry/plots/`.

**Corpus:** 100 ELFs, 0 failures. Intermediates: `results/run-diffing/<elf-id>/` and `results/run-symmetry/<elf-id>/` (load, mine, n-gram keys, pairs, family/r signals, judge JSON, C, native skip, timing, stdout/stderr).

**Pair / recall highlights (eval DualGate symbols only):**
- Diffing Flexo `test.elf`: 7 pairs, recall **7/8**. ALU `12/12`. Single-gate `and.elf`: 0 pairs.
- Diffing DualGate micro-recall: flexo 697/708, dcache 1102/1103, tlb 595/596. TAE clone class not treated as pairs on `gates.elf` (0 pairs / 1024 jmpreg).
- Symmetry Flexo `test.elf`: 7 pairs, **7/8**. ALU `12/12`. GITM `and_timing.elf`: **19 pairs**. TLB/DCache `test.elf`: 0 pairs (matches the experiment “no stable two-family lag”). TAE `gates.elf`: 0 (single-family trap).
- Negatives (simd, crypto, templates, inlined libc): **0 pairs** both runs.

**Live LLM:** Qwen3-8B on Flexo `test.elf`, GITM `main_and.elf`, Flexo-TLB `test.elf` (`WF_LIVE_MAX_PAIRS=2`). MockLLM for the other 97 ELFs.

- torch: `2.6.0+cu124`
- CUDA: `12.4` (wheel); live path hid GPUs so `torch.cuda.is_available()` was False for Qwen
- GPU: `cpu` (no GPU with >=22000 MiB free; others occupy leftover)
- live LLM policy: Live local Qwen3-8B on Flexo test.elf + GITM main_and.elf + Flexo-TLB test.elf (WF_LIVE_MAX_PAIRS=2); MockLLM for every other ELF.
- symmetry run: **yes**

## ELF counts

- dcache: 24
- flexo: 29
- gitm: 9
- neg: 4
- tae: 8
- tlb: 26

## Run A (diffing)

| elf-id | family | pairs | DualGate recall | live | s | ok |
|---|---|---:|---:|---|---:|---|
| `flexo.circuits.gates.test.elf` | flexo | 7 | 0.88 (7/8) | True | 662.3 | True |
| `tlb.Flexo.Flexo-TLB.circuits.gates.test.elf` | tlb | 8 | 0.89 (8/9) | True | 449.2 | True |
| `gitm.fixtures.main_and.elf` | gitm | 12 |  | True | 484.3 | True |
| `flexo.circuits.AES.aes_block.elf` | flexo | 2917 | 1.00 (36/36) | False | 90.1 | True |
| `flexo.circuits.AES.aes_round.elf` | flexo | 821 | 1.00 (30/30) | False | 8.2 | True |
| `flexo.circuits.AES.sbox.elf` | flexo | 62 | 1.00 (28/28) | False | 0.4 | True |
| `flexo.circuits.ALU.ALU.elf` | flexo | 12 | 1.00 (12/12) | False | 0.1 | True |
| `flexo.circuits.SHA1.sha1_2blocks.elf` | flexo | 1450 | 1.00 (65/65) | False | 10.2 | True |
| `flexo.circuits.SHA1.sha1_round.elf` | flexo | 362 | 1.00 (41/41) | False | 1.3 | True |
| `flexo.circuits.Simon.simon25.elf` | flexo | 959 | 1.00 (15/15) | False | 10.8 | True |
| `flexo.circuits.Simon.simon32.elf` | flexo | 1242 | 1.00 (16/16) | False | 17.1 | True |
| `flexo.circuits.arithmetic.adder.elf` | flexo | 225 | 1.00 (19/19) | False | 0.6 | True |
| `flexo.circuits.arithmetic.mul.elf` | flexo | 3230 | 1.00 (105/105) | False | 83.9 | True |
| `flexo.circuits.gates.and.elf` | flexo | 0 | 0.00 (0/1) | False | 0.0 | True |
| `tlb.Flexo.Flexo-DCache.circuits.AES.aes_block.elf` | dcache | 2958 | 1.00 (36/36) | False | 94.1 | True |
| `tlb.Flexo.Flexo-DCache.circuits.AES.aes_round.elf` | dcache | 828 | 1.00 (30/30) | False | 8.3 | True |
| `tlb.Flexo.Flexo-DCache.circuits.AES.sbox.elf` | dcache | 62 | 1.00 (28/28) | False | 0.4 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU.elf` | dcache | 14 | 1.00 (12/12) | False | 0.1 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU10.elf` | dcache | 167 | 1.00 (53/53) | False | 0.9 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU11.elf` | dcache | 192 | 1.00 (52/52) | False | 1.0 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU12.elf` | dcache | 236 | 1.00 (52/52) | False | 1.2 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU14.elf` | dcache | 262 | 1.00 (52/52) | False | 1.3 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU16.elf` | dcache | 313 | 1.00 (54/54) | False | 1.6 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU24.elf` | dcache | 509 | 1.00 (62/62) | False | 2.7 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU32.elf` | dcache | 552 | 1.00 (59/59) | False | 3.8 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU34.elf` | dcache | 664 | 1.00 (58/58) | False | 4.4 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU36.elf` | dcache | 778 | 1.00 (60/60) | False | 5.0 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU40.elf` | dcache | 819 | 1.00 (60/60) | False | 5.9 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU48.elf` | dcache | 882 | 1.00 (60/60) | False | 7.8 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU8.elf` | dcache | 188 | 1.00 (54/54) | False | 0.9 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU9.elf` | dcache | 166 | 1.00 (52/52) | False | 0.9 | True |
| `tlb.Flexo.Flexo-DCache.circuits.SHA1.sha1_2blocks.elf` | dcache | 1467 | 1.00 (65/65) | False | 10.5 | True |
| `tlb.Flexo.Flexo-DCache.circuits.SHA1.sha1_round.elf` | dcache | 362 | 1.00 (41/41) | False | 1.5 | True |
| `tlb.Flexo.Flexo-DCache.circuits.Simon.simon25.elf` | dcache | 958 | 1.00 (15/15) | False | 11.0 | True |
| `tlb.Flexo.Flexo-DCache.circuits.Simon.simon32.elf` | dcache | 1248 | 1.00 (16/16) | False | 17.5 | True |
| `tlb.Flexo.Flexo-DCache.circuits.arithmetic.adder.elf` | dcache | 228 | 1.00 (19/19) | False | 0.7 | True |
| `tlb.Flexo.Flexo-DCache.circuits.arithmetic.mul.elf` | dcache | 3353 | 1.00 (105/105) | False | 87.0 | True |
| `tlb.Flexo.Flexo-DCache.circuits.gates.test.elf` | dcache | 7 | 0.88 (7/8) | False | 0.1 | True |
| `tlb.Flexo.Flexo-TLB.circuits.AES.aes_block.elf` | tlb | 7856 | 1.00 (17/17) | False | 259.3 | True |
| `tlb.Flexo.Flexo-TLB.circuits.AES.aes_round.elf` | tlb | 2344 | 1.00 (16/16) | False | 22.5 | True |
| `tlb.Flexo.Flexo-TLB.circuits.AES.sbox.elf` | tlb | 122 | 1.00 (16/16) | False | 2.0 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU.elf` | tlb | 43 | 1.00 (15/15) | False | 1.8 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU10.elf` | tlb | 363 | 1.00 (30/30) | False | 2.6 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU11.elf` | tlb | 391 | 1.00 (31/31) | False | 2.9 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU12.elf` | tlb | 427 | 1.00 (33/33) | False | 2.9 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU14.elf` | tlb | 497 | 1.00 (33/33) | False | 3.3 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU16.elf` | tlb | 566 | 1.00 (33/33) | False | 3.8 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU24.elf` | tlb | 840 | 1.00 (31/31) | False | 5.5 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU32.elf` | tlb | 1158 | 1.00 (31/31) | False | 8.0 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU34.elf` | tlb | 1282 | 1.00 (31/31) | False | 8.7 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU36.elf` | tlb | 1343 | 1.00 (31/31) | False | 9.0 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU40.elf` | tlb | 1494 | 1.00 (31/31) | False | 10.9 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU48.elf` | tlb | 1827 | 1.00 (31/31) | False | 14.7 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU8.elf` | tlb | 285 | 1.00 (31/31) | False | 2.4 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU9.elf` | tlb | 332 | 1.00 (32/32) | False | 2.7 | True |
| `tlb.Flexo.Flexo-TLB.circuits.SHA1.sha1_2blocks_composed.elf` | tlb | 1995 | 1.00 (24/24) | False | 12.7 | True |
| `tlb.Flexo.Flexo-TLB.circuits.SHA1.sha1_round_composed.elf` | tlb | 1995 | 1.00 (24/24) | False | 11.4 | True |
| `tlb.Flexo.Flexo-TLB.circuits.Simon.simon25.elf` | tlb | 1932 | 1.00 (10/10) | False | 17.8 | True |
| `tlb.Flexo.Flexo-TLB.circuits.Simon.simon32.elf` | tlb | 2490 | 1.00 (10/10) | False | 30.3 | True |
| `tlb.Flexo.Flexo-TLB.circuits.arithmetic.adder.elf` | tlb | 269 | 1.00 (11/11) | False | 2.6 | True |
| `tlb.Flexo.Flexo-TLB.circuits.arithmetic.mul.elf` | tlb | 4151 | 1.00 (35/35) | False | 165.5 | True |
| `tlb.tools.tlb-test.test_window.elf` | tlb | 2 | 0.00 (0/0) | False | 2.5 | True |
| `tlb.tools.tlb-test.threshold.elf` | tlb | 12 | 0.00 (0/0) | False | 2.3 | True |
| `tae.elf.rerun1.aes.elf` | tae | 2 | 0.00 (0/1024) | False | 2.7 | True |
| `tae.elf.rerun1.gates.elf` | tae | 0 | 0.00 (0/1024) | False | 2.0 | True |
| `tae.elf.rerun1.search.elf` | tae | 5 | 0.00 (0/1024) | False | 2.6 | True |
| `tae.elf.rerun1.simon.elf` | tae | 3 | 0.00 (0/1024) | False | 2.1 | True |
| `tae.elf.rerun3.aes.elf` | tae | 2 | 0.00 (0/1024) | False | 2.5 | True |
| `tae.elf.rerun3.gates.elf` | tae | 0 | 0.00 (0/1024) | False | 2.4 | True |
| `tae.elf.rerun3.search.elf` | tae | 5 | 0.00 (0/1024) | False | 2.0 | True |
| `tae.elf.rerun3.simon.elf` | tae | 2 | 0.00 (0/1024) | False | 2.5 | True |
| `wemu.src.gates.flexo.aes.aes_block-10.elf` | flexo | 2947 | 1.00 (36/36) | False | 140.9 | True |
| `wemu.src.gates.flexo.aes.aes_round-16.elf` | flexo | 821 | 1.00 (30/30) | False | 10.3 | True |
| `wemu.src.gates.flexo.alu.ALU-2.elf` | flexo | 12 | 1.00 (12/12) | False | 0.3 | True |
| `wemu.src.gates.flexo.arithmetic.adder.elf` | flexo | 226 | 1.00 (19/19) | False | 0.8 | True |
| `wemu.src.gates.flexo.gates.gate_and.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.gate_mux.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.gate_nand.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.gate_not.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.gate_or.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.gate_xor.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.gate_xor3.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.gate_xor4.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.elf` | flexo | 7 | 0.88 (7/8) | False | 0.3 | True |
| `wemu.src.gates.flexo.sha1.sha1_2blocks-6.elf` | flexo | 1450 | 1.00 (65/65) | False | 12.7 | True |
| `wemu.src.gates.flexo.sha1.sha1_round.elf` | flexo | 362 | 1.00 (41/41) | False | 1.8 | True |
| `wemu.src.gates.flexo.sha1.sha1_round_broken.elf` | flexo | 362 | 1.00 (41/41) | False | 1.7 | True |
| `wemu.src.gates.flexo.simon.simon32-14.elf` | flexo | 1242 | 1.00 (16/16) | False | 23.5 | True |
| `wemu.src.gates.gitm.and_timing.elf` | gitm | 226 |  | False | 0.7 | True |
| `wemu.src.gates.gitm.main_and.elf` | gitm | 12 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_assign.elf` | gitm | 13 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_mux.elf` | gitm | 8 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_nand.elf` | gitm | 10 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_not.elf` | gitm | 9 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_or.elf` | gitm | 12 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_xor.elf` | gitm | 8 |  | False | 0.1 | True |
| `neg.simd.o` | neg | 0 |  | False | 0.0 | True |
| `neg.crypto.o` | neg | 0 |  | False | 0.0 | True |
| `neg.templates.o` | neg | 0 |  | False | 0.0 | True |
| `neg.inlined_libc.o` | neg | 0 |  | False | 0.0 | True |

## Run B (symmetry)

| elf-id | family | pairs | DualGate recall | live | s | ok |
|---|---|---:|---:|---|---:|---|
| `flexo.circuits.gates.test.elf` | flexo | 7 | 0.88 (7/8) | True | 706.7 | True |
| `tlb.Flexo.Flexo-TLB.circuits.gates.test.elf` | tlb | 0 | 0.00 (0/9) | True | 69.4 | True |
| `gitm.fixtures.main_and.elf` | gitm | 0 |  | True | 68.9 | True |
| `flexo.circuits.AES.aes_block.elf` | flexo | 37 | 0.00 (0/36) | False | 14.4 | True |
| `flexo.circuits.AES.aes_round.elf` | flexo | 8 | 0.00 (0/30) | False | 3.6 | True |
| `flexo.circuits.AES.sbox.elf` | flexo | 28 | 1.00 (28/28) | False | 0.5 | True |
| `flexo.circuits.ALU.ALU.elf` | flexo | 12 | 1.00 (12/12) | False | 0.2 | True |
| `flexo.circuits.SHA1.sha1_2blocks.elf` | flexo | 58 | 0.97 (63/65) | False | 5.5 | True |
| `flexo.circuits.SHA1.sha1_round.elf` | flexo | 0 | 0.00 (0/41) | False | 1.2 | True |
| `flexo.circuits.Simon.simon25.elf` | flexo | 0 | 0.00 (0/15) | False | 5.2 | True |
| `flexo.circuits.Simon.simon32.elf` | flexo | 0 | 0.00 (0/16) | False | 7.4 | True |
| `flexo.circuits.arithmetic.adder.elf` | flexo | 19 | 1.00 (19/19) | False | 0.9 | True |
| `flexo.circuits.arithmetic.mul.elf` | flexo | 97 | 0.99 (104/105) | False | 16.9 | True |
| `flexo.circuits.gates.and.elf` | flexo | 0 | 0.00 (0/1) | False | 0.0 | True |
| `tlb.Flexo.Flexo-DCache.circuits.AES.aes_block.elf` | dcache | 32 | 0.00 (0/36) | False | 14.1 | True |
| `tlb.Flexo.Flexo-DCache.circuits.AES.aes_round.elf` | dcache | 8 | 0.00 (0/30) | False | 3.7 | True |
| `tlb.Flexo.Flexo-DCache.circuits.AES.sbox.elf` | dcache | 28 | 1.00 (28/28) | False | 0.7 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU.elf` | dcache | 12 | 1.00 (12/12) | False | 0.2 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU10.elf` | dcache | 46 | 0.94 (50/53) | False | 1.2 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU11.elf` | dcache | 45 | 0.96 (50/52) | False | 1.3 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU12.elf` | dcache | 45 | 0.94 (49/52) | False | 1.7 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU14.elf` | dcache | 45 | 0.96 (50/52) | False | 1.6 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU16.elf` | dcache | 47 | 0.96 (52/54) | False | 1.9 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU24.elf` | dcache | 56 | 0.98 (61/62) | False | 2.4 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU32.elf` | dcache | 53 | 0.98 (58/59) | False | 3.1 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU34.elf` | dcache | 51 | 0.97 (56/58) | False | 3.4 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU36.elf` | dcache | 53 | 0.97 (58/60) | False | 3.2 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU40.elf` | dcache | 53 | 0.97 (58/60) | False | 3.9 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU48.elf` | dcache | 53 | 0.97 (58/60) | False | 4.1 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU8.elf` | dcache | 47 | 0.96 (52/54) | False | 1.3 | True |
| `tlb.Flexo.Flexo-DCache.circuits.ALU.ALU9.elf` | dcache | 45 | 0.96 (50/52) | False | 1.2 | True |
| `tlb.Flexo.Flexo-DCache.circuits.SHA1.sha1_2blocks.elf` | dcache | 58 | 0.97 (63/65) | False | 5.0 | True |
| `tlb.Flexo.Flexo-DCache.circuits.SHA1.sha1_round.elf` | dcache | 0 | 0.00 (0/41) | False | 1.6 | True |
| `tlb.Flexo.Flexo-DCache.circuits.Simon.simon25.elf` | dcache | 0 | 0.00 (0/15) | False | 5.7 | True |
| `tlb.Flexo.Flexo-DCache.circuits.Simon.simon32.elf` | dcache | 0 | 0.00 (0/16) | False | 6.8 | True |
| `tlb.Flexo.Flexo-DCache.circuits.arithmetic.adder.elf` | dcache | 19 | 1.00 (19/19) | False | 0.8 | True |
| `tlb.Flexo.Flexo-DCache.circuits.arithmetic.mul.elf` | dcache | 97 | 0.99 (104/105) | False | 16.4 | True |
| `tlb.Flexo.Flexo-DCache.circuits.gates.test.elf` | dcache | 0 | 0.00 (0/8) | False | 0.2 | True |
| `tlb.Flexo.Flexo-TLB.circuits.AES.aes_block.elf` | tlb | 0 | 0.00 (0/17) | False | 16.5 | True |
| `tlb.Flexo.Flexo-TLB.circuits.AES.aes_round.elf` | tlb | 0 | 0.00 (0/16) | False | 5.6 | True |
| `tlb.Flexo.Flexo-TLB.circuits.AES.sbox.elf` | tlb | 16 | 1.00 (16/16) | False | 0.3 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU.elf` | tlb | 15 | 1.00 (15/15) | False | 0.2 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU10.elf` | tlb | 24 | 0.97 (29/30) | False | 1.1 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU11.elf` | tlb | 25 | 0.97 (30/31) | False | 1.1 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU12.elf` | tlb | 0 | 0.00 (0/33) | False | 1.1 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU14.elf` | tlb | 27 | 0.97 (32/33) | False | 1.2 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU16.elf` | tlb | 0 | 0.00 (0/33) | False | 1.3 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU24.elf` | tlb | 26 | 0.97 (30/31) | False | 1.9 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU32.elf` | tlb | 26 | 0.97 (30/31) | False | 2.5 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU34.elf` | tlb | 0 | 0.00 (0/31) | False | 3.0 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU36.elf` | tlb | 0 | 0.00 (0/31) | False | 3.2 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU40.elf` | tlb | 0 | 0.00 (0/31) | False | 3.6 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU48.elf` | tlb | 0 | 0.00 (0/31) | False | 3.8 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU8.elf` | tlb | 25 | 0.94 (29/31) | False | 0.6 | True |
| `tlb.Flexo.Flexo-TLB.circuits.ALU.ALU9.elf` | tlb | 26 | 0.97 (31/32) | False | 0.8 | True |
| `tlb.Flexo.Flexo-TLB.circuits.SHA1.sha1_2blocks_composed.elf` | tlb | 0 | 0.00 (0/24) | False | 24.5 | True |
| `tlb.Flexo.Flexo-TLB.circuits.SHA1.sha1_round_composed.elf` | tlb | 0 | 0.00 (0/24) | False | 29.7 | True |
| `tlb.Flexo.Flexo-TLB.circuits.Simon.simon25.elf` | tlb | 10 | 1.00 (10/10) | False | 4.5 | True |
| `tlb.Flexo.Flexo-TLB.circuits.Simon.simon32.elf` | tlb | 0 | 0.00 (0/10) | False | 6.1 | True |
| `tlb.Flexo.Flexo-TLB.circuits.arithmetic.adder.elf` | tlb | 0 | 0.00 (0/11) | False | 0.6 | True |
| `tlb.Flexo.Flexo-TLB.circuits.arithmetic.mul.elf` | tlb | 0 | 0.00 (0/35) | False | 14.3 | True |
| `tlb.tools.tlb-test.test_window.elf` | tlb | 0 | 0.00 (0/0) | False | 4.3 | True |
| `tlb.tools.tlb-test.threshold.elf` | tlb | 0 | 0.00 (0/0) | False | 2.9 | True |
| `tae.elf.rerun1.aes.elf` | tae | 0 | 0.00 (0/1024) | False | 3.0 | True |
| `tae.elf.rerun1.gates.elf` | tae | 0 | 0.00 (0/1024) | False | 2.8 | True |
| `tae.elf.rerun1.search.elf` | tae | 0 | 0.00 (0/1024) | False | 2.4 | True |
| `tae.elf.rerun1.simon.elf` | tae | 0 | 0.00 (0/1024) | False | 3.1 | True |
| `tae.elf.rerun3.aes.elf` | tae | 0 | 0.00 (0/1024) | False | 2.4 | True |
| `tae.elf.rerun3.gates.elf` | tae | 0 | 0.00 (0/1024) | False | 3.2 | True |
| `tae.elf.rerun3.search.elf` | tae | 0 | 0.00 (0/1024) | False | 2.5 | True |
| `tae.elf.rerun3.simon.elf` | tae | 0 | 0.00 (0/1024) | False | 3.2 | True |
| `wemu.src.gates.flexo.aes.aes_block-10.elf` | flexo | 37 | 0.00 (0/36) | False | 14.6 | True |
| `wemu.src.gates.flexo.aes.aes_round-16.elf` | flexo | 8 | 0.00 (0/30) | False | 3.1 | True |
| `wemu.src.gates.flexo.alu.ALU-2.elf` | flexo | 12 | 1.00 (12/12) | False | 0.2 | True |
| `wemu.src.gates.flexo.arithmetic.adder.elf` | flexo | 19 | 1.00 (19/19) | False | 0.9 | True |
| `wemu.src.gates.flexo.gates.gate_and.elf` | flexo | 7 | 0.88 (7/8) | False | 0.2 | True |
| `wemu.src.gates.flexo.gates.gate_mux.elf` | flexo | 7 | 0.88 (7/8) | False | 0.2 | True |
| `wemu.src.gates.flexo.gates.gate_nand.elf` | flexo | 7 | 0.88 (7/8) | False | 0.2 | True |
| `wemu.src.gates.flexo.gates.gate_not.elf` | flexo | 7 | 0.88 (7/8) | False | 0.2 | True |
| `wemu.src.gates.flexo.gates.gate_or.elf` | flexo | 7 | 0.88 (7/8) | False | 0.2 | True |
| `wemu.src.gates.flexo.gates.gate_xor.elf` | flexo | 7 | 0.88 (7/8) | False | 0.5 | True |
| `wemu.src.gates.flexo.gates.gate_xor3.elf` | flexo | 7 | 0.88 (7/8) | False | 0.2 | True |
| `wemu.src.gates.flexo.gates.gate_xor4.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.gates.elf` | flexo | 7 | 0.88 (7/8) | False | 0.1 | True |
| `wemu.src.gates.flexo.sha1.sha1_2blocks-6.elf` | flexo | 58 | 0.97 (63/65) | False | 5.3 | True |
| `wemu.src.gates.flexo.sha1.sha1_round.elf` | flexo | 0 | 0.00 (0/41) | False | 1.2 | True |
| `wemu.src.gates.flexo.sha1.sha1_round_broken.elf` | flexo | 41 | 1.00 (41/41) | False | 1.3 | True |
| `wemu.src.gates.flexo.simon.simon32-14.elf` | flexo | 0 | 0.00 (0/16) | False | 7.8 | True |
| `wemu.src.gates.gitm.and_timing.elf` | gitm | 19 |  | False | 0.6 | True |
| `wemu.src.gates.gitm.main_and.elf` | gitm | 0 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_assign.elf` | gitm | 0 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_mux.elf` | gitm | 0 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_nand.elf` | gitm | 0 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_not.elf` | gitm | 0 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_or.elf` | gitm | 0 |  | False | 0.1 | True |
| `wemu.src.gates.gitm.main_xor.elf` | gitm | 0 |  | False | 0.1 | True |
| `neg.simd.o` | neg | 0 |  | False | 0.0 | True |
| `neg.crypto.o` | neg | 0 |  | False | 0.0 | True |
| `neg.templates.o` | neg | 0 |  | False | 0.0 | True |
| `neg.inlined_libc.o` | neg | 0 |  | False | 0.0 | True |

## Negatives (diffing FPR-ish)

- `neg.simd.o` pairs=0
- `neg.crypto.o` pairs=0
- `neg.templates.o` pairs=0
- `neg.inlined_libc.o` pairs=0
