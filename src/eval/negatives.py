"""Expanded near-miss negative corpus + per-detector false-positive harness.

Mirrors the validated Phase 1 specificity corpus
(~/workspace/weird-decomp/exp/phase1/exp1/, 11 files from 9 C sources):
near-miss programs sharing surface features with weird machines (ret
triggers, divider chains, clflush+rdtsc, indirect branches) that compute no
weird function. The C sources below are verbatim copies of the validated
exp1 controls.

Detectors (repo terms, mirroring the Phase 1 F-detector definitions):
  trigger-def  : harvest WINDOW_OPEN with "cacm.window.rsb" provenance
                 (add/or/xor on (%rsp)) with `ret` in the next 2 insns
                 (Phase 1: "`addq %rdx, (%rsp)` with `ret` in next 2 insns";
                 the ret-requirement is the specificity mechanism)
  trigger-call : `call` whose immediate target lands in a trigger-def chunk
  dualgate     : has_dual_gate() — DualGate symbols in the symbol table
  probe-site   : `call` to an rdtscp-containing function, then `cmp $imm`
                 within 15 insns, then `setb` within 4 (Phase 1 definition;
                 the call-boundary requirement is load-bearing)

Established boundary (Phase 1 verdict: SPLIT), encoded as assertions:
  - trigger-def / trigger-call / DualGate: 0 FP across all 11 files — ASSERTED.
  - probe-site: fires on the two forced-setb Spectre controls (it is a
    generic timing-side-channel probe detector; probe-site specificity is
    explicitly NOT claimed) — RECORDED and reported, never asserted zero.

Usage: python src/eval/negatives.py [--outdir DIR] [--keep]
Writes the C sources, compiles them with gcc, runs harvest + detectors over
each ELF, prints the FP table, asserts the trigger/DualGate boundary, and
writes negatives_report.json. Nothing is executed: binaries are only
disassembled (like Phase 1, which used gcc -S only).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capstone.x86 import X86_OP_IMM
from elftools.elf.elffile import ELFFile

from ir.events import EventKind
from lift.flexo import has_dual_gate
from lift.harvest import _assign_funcs, _disasm, _func_entries, _text, harvest_elf

# ---------------------------------------------------------------------------
# Corpus sources: verbatim copies of the validated Phase 1 exp1 controls.
# ---------------------------------------------------------------------------

SRC_SPECTRE_SETB = r'''/* (a) TRUE near-miss Spectre-PHT gadget.
 *
 * The old control (exp/static/neg/spectre.c) was a near-miss: it contained
 *   call <rdtscp-timer>; cmpq $181, %rax
 * but gcc materialized the boolean with `adcl $0, %ebx`, so the probe
 * detector (call -> cmp $imm -> setb) rejected it. Here BOTH boolean
 * materializations are forced to `setb` via inline asm so gcc cannot
 * substitute `adcl`:
 *   1. bounds check: cmp + setb (inb)
 *   2. reload probe: call measure (rdtscp timer chunk) -> cmpq $181 -> setb
 * Control (a) completes the EXACT structural pattern of the Flexo probe
 * detector on ordinary published attack code. If the probe detector fires
 * here, that is a false positive by the experiment's falsifier rule.
 */
#include <stddef.h>
#include <stdint.h>
#include <x86intrin.h>

#define STRIDE 4096
static unsigned char array1[16] = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};
static unsigned char array2[256 * STRIDE];
static volatile size_t array1_size = 16;
static unsigned char secret = 42;

/* noinline so the rdtscp timer is its own chunk and probe_one's `call`
   resolves to it structurally (this is what the probe detector keys on). */
__attribute__((noinline)) static uint64_t measure(volatile unsigned char *p) {
    unsigned aux;
    uint64_t t0 = __rdtscp(&aux);
    (void)*p;
    return __rdtscp(&aux) - t0;
}

/* bounds check with FORCED setb: gcc cannot rewrite this into adcl. */
static void victim(size_t x) {
    int inb;
    size_t sz = array1_size; /* volatile read */
    __asm__ volatile("cmpq %2, %1\n\tsetb %b0"
                     : "=r"(inb) : "r"(x), "r"(sz) : "cc");
    if (inb) {
        /* speculative out-of-bounds load into the oracle */
        volatile unsigned char v = array2[array1[x] * STRIDE];
        (void)v;
    }
}

/* reload probe: times one oracle line; 1 iff cached (t < 181, Flexo's own
   threshold). call -> cmp $imm -> setb, the detector's exact pattern. */
static int probe_one(int i) {
    uint64_t t = measure(&array2[i * STRIDE]);
    int hit;
    __asm__ volatile("cmpq $181, %1\n\tsetb %b0"
                     : "=r"(hit) : "r"(t) : "cc");
    return hit;
}

int spectre_poc(void) {
    int hits = 0;
    for (int r = 0; r < 256; r++) {
        for (int i = 0; i < 32; i++)
            victim(i % 16);               /* train PHT in-bounds */
        victim((size_t)(&secret - array1)); /* out-of-bounds speculative */
        for (int i = 0; i < 256; i++)
            hits += probe_one(i);         /* reload probe */
    }
    return hits;
}
'''

SRC_RETPOLINE_CALL = r'''/* (b1) Indirect CALL through a hand-written retpoline thunk.
 *
 * The thunk is a genuine ret-based speculation trap:
 *     call 1f; 2: pause; lfence; jmp 2b; 1: mov %rax,(%rsp); ret
 * i.e. it writes the stack slot and returns into the real target, exactly
 * like the Flexo trigger's `addq %rdx,(%rsp); ret` -- except the stack write
 * is `mov`, not `addq %rdx`. Near-miss on the trigger-def pattern:
 * retpoline-shaped ret, but the wrong stack-write opcode.
 * The thunk is defined in this file so it is a real chunk the detector sees.
 */
#include <stddef.h>

__asm__(
    ".globl __x86_indirect_thunk_rax\n"
    ".type __x86_indirect_thunk_rax, @function\n"
    "__x86_indirect_thunk_rax:\n"
    "  call 1f\n"
    "2: pause\n"
    "  lfence\n"
    "  jmp 2b\n"
    "1: mov %rax, (%rsp)\n"
    "  ret\n"
);

typedef void (*fn_t)(void);

void dispatch_call(fn_t *table, size_t n, size_t idx) {
    fn_t f = table[idx % n];
    /* route the indirect call through the retpoline thunk (target in %rax) */
    __asm__ volatile("call __x86_indirect_thunk_rax"
                     :: "a"(f) : "memory");
}
'''

SRC_RETPOLINE_JMP = r'''/* (b2) Indirect JMP through a retpoline-style thunk.
 *
 * Same idea as (b1) but for the jump variant: the dispatch site does
 * `jmp __x86_indirect_thunk_r11` with the target pinned in %r11, and the
 * thunk captures speculation in pause/lfence loop, plants the target with
 * `mov %r11,(%rsp)`, and rets into it. Near-miss: retpoline-shaped ret,
 * but mov-not-addq stack write, and reached via jmp (Flexo's trigger is
 * reached via call).
 */
#include <stddef.h>

__asm__(
    ".globl __x86_indirect_thunk_r11\n"
    ".type __x86_indirect_thunk_r11, @function\n"
    "__x86_indirect_thunk_r11:\n"
    "  call 1f\n"
    "2: pause\n"
    "  lfence\n"
    "  jmp 2b\n"
    "1: mov %r11, (%rsp)\n"
    "  ret\n"
);

void dispatch_jmp(void **table, size_t n, size_t idx) {
    void *t = table[idx % n];
    register void *tt __asm__("r11") = t; /* retpoline ABI: target in %r11 */
    __asm__ volatile("jmp __x86_indirect_thunk_r11"
                     :: "r"(tt) : "memory");
    __builtin_unreachable();
}
'''

SRC_DIVCHAIN_NORET = r'''/* (c) Long `divw %%cx` sizer chain (Flexo's own sizer idiom) immediately
 * followed by `addq %%rdx,(%%rsp)` -- but with NO `ret` nearby.
 *
 * This breaks the trigger-def pattern at the last step: the detector needs
 * addq %%rdx,(%%rsp) with ret among the next 2 instructions. The result is
 * kept live through further arithmetic so the epilogue `ret` sits far from
 * the addq. The grep baseline (`divw` within 40 lines above `addq.*(%%rsp)`)
 * WILL fire here; the F trigger detector must not. That contrast is the
 * point: it isolates the ret-requirement as the specificity mechanism.
 *
 * The 48 divw lines are spelled out explicitly (not .rept) so the analyzed
 * .s text literally contains the long chain.
 */
#include <stdint.h>

__attribute__((noinline)) uint32_t divchain(uint32_t a, uint32_t b) {
    uint32_t q;
    __asm__ volatile(
        "movl %1, %%eax\n\t"
        "xorl %%edx, %%edx\n\t"
        "movl %2, %%ecx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "divw %%cx\n\t"
        "addq %%rdx, (%%rsp)\n\t" /* the stack write, with NO ret after it */
        "movzwl %%ax, %0\n\t"
        : "=r"(q) : "r"(a), "r"(b)
        : "eax", "ecx", "edx", "cc", "memory");
    /* keep q live so the function-epilogue ret is far from the addq */
    uint32_t r = q ^ 0x9e3779b9u;
    r += (r >> 7) * 31u;
    r ^= r >> 13;
    return r;
}
'''

SRC_FLUSHRELOAD = r'''/* (d) Flush+Reload loop: clflush + INLINED rdtscp + forced setb.
 *
 * All probe ingredients are present in ONE chunk -- clflush eviction,
 * rdtscp timing, cmp $imm, setb materialization -- but there is NO call to
 * a timer function (the rdtscp intrinsics are inlined in the loop body).
 * Near-miss on the probe detector's call-boundary requirement: if the
 * detector's `call <rdtscp-chunk>` condition is doing real structural work,
 * it must stay silent here while (a) fires.
 */
#include <stddef.h>
#include <stdint.h>
#include <x86intrin.h>

#define STRIDE 4096
static unsigned char oracle[256 * STRIDE];

int fr_scan(volatile unsigned char *base, int n) {
    int hits = 0;
    for (int i = 0; i < n; i++) {
        volatile unsigned char *p = &base[i * STRIDE];
        _mm_clflush((void *)p);
        _mm_mfence();
        unsigned aux;
        uint64_t t0 = __rdtscp(&aux);   /* inlined: no call boundary */
        (void)*p;
        uint64_t dt = __rdtscp(&aux) - t0;
        int hit;
        __asm__ volatile("cmpq $200, %1\n\tsetb %b0"
                         : "=r"(hit) : "r"(dt) : "cc");
        hits += hit;
    }
    return hits;
}

int fr_run(void) {
    return fr_scan(oracle, 256);
}
'''

SRC_AESNI = r'''/* (e) Ordinary AES-NI crypto: AES-128 key expansion + round loop.
 *
 * Vectorized crypto with aesenc/aesenclast, key-schedule loads, and a
 * clflush key wipe. Exercises the "weird-adjacent" crypto idiom (Flexo's
 * own artifact ships an AES circuit) with no timing, no ret tricks, and no
 * bool materialization. Compile with -maes.
 */
#include <wmmintrin.h>
#include <emmintrin.h>
#include <stdint.h>
#include <stddef.h>

static __m128i rk[11];

static __m128i keygen_step(__m128i k, int rcon) {
    __m128i t = _mm_aeskeygenassist_si128(k, rcon);
    t = _mm_shuffle_epi32(t, 0xff);
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    k = _mm_xor_si128(k, _mm_slli_si128(k, 4));
    return _mm_xor_si128(k, t);
}

void aes128_setkey(const unsigned char key[16]) {
    __m128i k = _mm_loadu_si128((const __m128i *)key);
    rk[0] = k;
    rk[1]  = keygen_step(k,      0x01); k = rk[1];
    rk[2]  = keygen_step(k,      0x02); k = rk[2];
    rk[3]  = keygen_step(k,      0x04); k = rk[3];
    rk[4]  = keygen_step(k,      0x08); k = rk[4];
    rk[5]  = keygen_step(k,      0x10); k = rk[5];
    rk[6]  = keygen_step(k,      0x20); k = rk[6];
    rk[7]  = keygen_step(k,      0x40); k = rk[7];
    rk[8]  = keygen_step(k,      0x80); k = rk[8];
    rk[9]  = keygen_step(k,      0x1b); k = rk[9];
    rk[10] = keygen_step(k,      0x36);
}

void aes128_enc(const unsigned char in[16], unsigned char out[16]) {
    __m128i s = _mm_loadu_si128((const __m128i *)in);
    s = _mm_xor_si128(s, rk[0]);
    for (int r = 1; r < 10; r++)
        s = _mm_aesenc_si128(s, rk[r]);
    s = _mm_aesenclast_si128(s, rk[10]);
    _mm_storeu_si128((__m128i *)out, s);
}

void aes128_wipekey(void) {
    for (size_t i = 0; i < 11; i++)
        _mm_clflush(&rk[i]);
}
'''

SRC_COMPGOTO = r'''/* (f1) Computed-goto threaded interpreter: indirect-jmp dispatch loop.
 *
 * The classic "weird control flow" of ordinary programs: dispatch through a
 * table of label addresses with `goto *table[*pc++]`. Indirect-branch-heavy
 * code with data-dependent jump targets -- near-miss for anything keyed on
 * indirect branches, but no ret-based trigger and no timing idiom.
 */
#include <stddef.h>
#include <stdint.h>

long interp(const unsigned char *code, size_t len, long *stack) {
    static const void *table[] = { &&op_add, &&op_sub, &&op_mul, &&op_ret };
    long *sp = stack;
    const unsigned char *pc = code;
    const unsigned char *end = code + len;
    long acc = 0;

#define NEXT() do { if (pc >= end) goto done; goto *table[*pc++]; } while (0)

    NEXT();
op_add: acc += *sp++; NEXT();
op_sub: acc -= *sp++; NEXT();
op_mul: acc *= *sp++; NEXT();
op_ret: goto done;
done:
    return acc;
}
'''

SRC_SETJMP = r'''/* (f2) setjmp/longjmp-heavy control flow.
 *
 * Non-local jumps that unwind the stack and restore registers -- the
 * ordinary-programming-language version of return-address/stack
 * manipulation. Goes through libc (setjmp/longjmp@PLT, unresolvable
 * targets the detectors skip); no inline stack surgery, no ret tricks.
 */
#include <setjmp.h>
#include <stddef.h>

static jmp_buf env;
static int depth = 0;

static void deep(int n) {
    if (n <= 0)
        longjmp(env, 42);
    volatile int pad[16];
    for (int i = 0; i < 16; i++)
        pad[i] = n + i;
    depth++;
    deep(n - 1);
    depth--;
    (void)pad[0];
}

int run_unwind(int n) {
    int v = setjmp(env);
    if (v == 0)
        deep(n);
    return v + depth;
}
'''

SRC_COSWITCH = r'''/* (f3) Manual coroutine stack switch in inline asm.
 *
 * Direct stack-pointer surgery: saves %rsp to one context and loads %rsp
 * from another, plus a variant that plants a return-address slot with
 * `movq %reg,(%rsp)`. Near-miss for the trigger's `(%rsp)` write idiom --
 * but the write is `mov`, not `addq %rdx`, and there is no `ret` involved.
 */
#include <stddef.h>

typedef struct { void *rsp; } ctx_t;

void co_switch(ctx_t *from, ctx_t *to) {
    __asm__ volatile(
        "movq %%rsp, (%0)\n\t"
        "movq (%1), %%rsp\n\t"
        :: "r"(&from->rsp), "r"(&to->rsp) : "memory");
}

void co_switch_plantret(ctx_t *from, ctx_t *to, void *retaddr) {
    __asm__ volatile(
        "movq %%rsp, (%0)\n\t"
        "movq %2, (%%rsp)\n\t"   /* plant return-address slot, mov not addq */
        "movq (%1), %%rsp\n\t"
        :: "r"(&from->rsp), "r"(&to->rsp), "r"(retaddr) : "memory");
}
'''

# ---------------------------------------------------------------------------
# Corpus: 11 files from 9 sources (mirrors the Phase 1 build matrix).
# ---------------------------------------------------------------------------


@dataclass
class CorpusEntry:
    name: str
    cfile: str
    src: str
    cflags: List[str] = field(default_factory=list)


CORPUS: List[CorpusEntry] = [
    CorpusEntry("spectre_setb_O2", "spectre_setb.c", SRC_SPECTRE_SETB, ["-O2"]),
    CorpusEntry("spectre_setb_O1", "spectre_setb.c", SRC_SPECTRE_SETB, ["-O1"]),
    CorpusEntry("retpoline_call", "retpoline_call.c", SRC_RETPOLINE_CALL, ["-O2"]),
    CorpusEntry("retpoline_jmp", "retpoline_jmp.c", SRC_RETPOLINE_JMP, ["-O2"]),
    CorpusEntry("divchain_noret_O2", "divchain_noret.c", SRC_DIVCHAIN_NORET, ["-O2"]),
    CorpusEntry("divchain_noret_O1", "divchain_noret.c", SRC_DIVCHAIN_NORET, ["-O1"]),
    CorpusEntry("flushreload", "flushreload.c", SRC_FLUSHRELOAD, ["-O2"]),
    CorpusEntry("aesni", "aesni.c", SRC_AESNI, ["-O2", "-maes"]),
    CorpusEntry("compgoto", "compgoto.c", SRC_COMPGOTO, ["-O2"]),
    CorpusEntry("setjmp", "setjmp.c", SRC_SETJMP, ["-O2"]),
    CorpusEntry("coswitch", "coswitch.c", SRC_COSWITCH, ["-O2"]),
]

# The established boundary: trigger/DualGate detectors must stay silent on
# every control (asserted); probe-site FPs are recorded, not asserted.
ASSERT_ZERO = ("trigger_def", "trigger_call", "dualgate")

# ---------------------------------------------------------------------------
# Detectors (repo terms; definitions mirror Phase 1 detect.py).
# ---------------------------------------------------------------------------


def _load_insns(elf_path: str):
    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        text_lo, text_hi, code = _text(elf)
    return _disasm(code, text_lo), text_lo, text_hi


def detect_trigger_defs(h, insns) -> List[int]:
    """add/or/xor on (%rsp) with `ret` in the next 2 insns (Phase 1 def)."""
    hits = []
    addr_to_idx = {insn.address: i for i, insn in enumerate(insns)}
    for frag in h.fragments:
        for e in frag.events:
            if e.kind != EventKind.WINDOW_OPEN:
                continue
            if "cacm.window.rsb" not in e.provenance:
                continue
            i = addr_to_idx.get(e.addr)
            if i is None:
                continue
            nxt = [insns[j].mnemonic for j in range(i + 1, min(i + 3, len(insns)))]
            if "ret" in nxt:
                hits.append(e.addr)
    return sorted(set(hits))


def detect_trigger_calls(h, insns, trig_addrs) -> List[int]:
    """`call` whose immediate target lands in a trigger-def chunk."""
    trig_addrs = set(trig_addrs)
    ranges = []
    for frag in h.fragments:
        if any(e.addr in trig_addrs for e in frag.events):
            ranges.append((frag.entry or 0, frag.exit or 0))
    hits = []
    for insn in insns:
        if insn.mnemonic != "call" or not insn.operands:
            continue
        op = insn.operands[0]
        if op.type != X86_OP_IMM:
            continue
        tgt = int(op.imm)
        if any(lo <= tgt <= hi for lo, hi in ranges):
            hits.append(insn.address)
    return sorted(set(hits))


def detect_dualgate(elf_path: str) -> List[dict]:
    """DualGate symbols in the symbol table (repo's DualGate detector)."""
    return has_dual_gate(elf_path)


def detect_probe_sites(insns, text_lo: int, text_hi: int) -> List[int]:
    """call to an rdtscp-chunk, then `cmp $imm`, then `setb` (Phase 1 def)."""
    entries = _func_entries(insns, text_lo, text_hi)
    func_of = _assign_funcs(insns, entries)
    rdtsc_funcs = set()
    for insn in insns:
        if insn.mnemonic in ("rdtsc", "rdtscp"):
            f = func_of.get(insn.address)
            if f is not None:
                rdtsc_funcs.add(f)
    anchors = []
    n = len(insns)
    for t, insn in enumerate(insns):
        if insn.mnemonic != "call" or not insn.operands:
            continue
        op = insn.operands[0]
        if op.type != X86_OP_IMM:
            continue
        if func_of.get(int(op.imm)) not in rdtsc_funcs:
            continue
        for j in range(t + 1, min(t + 16, n)):
            s = insns[j]
            if (
                s.mnemonic == "cmp"
                and len(s.operands) >= 2
                and s.operands[1].type == X86_OP_IMM
            ):
                if any(
                    insns[k].mnemonic == "setb" for k in range(j + 1, min(j + 5, n))
                ):
                    anchors.append(s.address)
                break
    anchors = sorted(set(anchors))
    merged = []
    for a in anchors:
        if merged and a - merged[-1] <= 16:
            continue
        merged.append(a)
    return merged


def evaluate(elf_path: str) -> dict:
    """Run harvest + all four detectors over one ELF. Returns addr-hit lists."""
    h = harvest_elf(elf_path)
    insns, text_lo, text_hi = _load_insns(elf_path)
    trig = detect_trigger_defs(h, insns)
    return {
        "trigger_def": trig,
        "trigger_call": detect_trigger_calls(h, insns, trig),
        "dualgate": detect_dualgate(elf_path),
        "probe_site": detect_probe_sites(insns, text_lo, text_hi),
    }


# ---------------------------------------------------------------------------
# Build + harness.
# ---------------------------------------------------------------------------


def write_corpus(outdir: Path) -> List[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    seen = set()
    for entry in CORPUS:
        p = outdir / entry.cfile
        if entry.cfile not in seen:
            p.write_text(entry.src)
            seen.add(entry.cfile)
        written.append(p)
    return written


def compile_corpus(outdir: Path) -> dict:
    """Compile each corpus entry. Returns {name: elf_path}; raises on failure."""
    elfs = {}
    for entry in CORPUS:
        src = outdir / entry.cfile
        elf = outdir / f"{entry.name}.elf"
        cmd = ["gcc", *entry.cflags, "-o", str(elf), str(src)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(
                f"compile failed for {entry.name}:\n{proc.stderr[-2000:]}"
            )
        elfs[entry.name] = str(elf)
    return elfs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default="negatives_out",
                    help="directory for sources, ELFs, and the JSON report")
    ap.add_argument("--keep", action="store_true",
                    help="keep ELFs (default: sources + report only)")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    write_corpus(outdir)
    elfs = compile_corpus(outdir)

    rows = []
    totals = {"trigger_def": 0, "trigger_call": 0, "dualgate": 0, "probe_site": 0}
    for entry in CORPUS:
        det = evaluate(elfs[entry.name])
        counts = {k: len(v) for k, v in det.items()}
        for k in totals:
            totals[k] += counts[k]
        rows.append({"control": entry.name, "fps": counts, "hits": det})

    report = {"controls": rows, "totals": totals}
    (outdir / "negatives_report.json").write_text(json.dumps(report, indent=2))

    print(f"{'control':22s} {'trig_def':>9s} {'trig_call':>10s} {'dualgate':>9s} {'probe':>6s}")
    for r in rows:
        f = r["fps"]
        print(f"{r['control']:22s} {f['trigger_def']:9d} {f['trigger_call']:10d} "
              f"{f['dualgate']:9d} {f['probe_site']:6d}")
    print(f"{'TOTAL':22s} {totals['trigger_def']:9d} {totals['trigger_call']:10d} "
          f"{totals['dualgate']:9d} {totals['probe_site']:6d}")

    # Established boundary: trigger/DualGate detectors must be silent.
    for det in ASSERT_ZERO:
        assert totals[det] == 0, (
            f"SPECIFICITY VIOLATION: {det} fired {totals[det]}x on the negative "
            f"corpus (Phase 1 established 0 FP)"
        )
    # Probe-site FPs are recorded, not asserted: the detector is a generic
    # timing-side-channel probe detector (Phase 1: 2 FPs, both forced-setb).
    print(f"probe-site FPs recorded (not asserted): {totals['probe_site']} "
          f"(Phase 1 reference: 2, both forced-setb Spectre)")

    if not args.keep:
        for p in elfs.values():
            Path(p).unlink(missing_ok=True)
    print(f"report: {outdir / 'negatives_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
