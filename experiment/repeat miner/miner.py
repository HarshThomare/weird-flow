"""Repetition miner: cluster normalized code fragments and score them.

Ground truth is a list of (start, end, name) address spans recorded before
stripping. The miner never reads symbols from the binary it scores.
"""

from __future__ import annotations

import bisect
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

from capstone import (
    CS_ARCH_ARM64,
    CS_ARCH_RISCV,
    CS_ARCH_X86,
    CS_GRP_JUMP,
    CS_MODE_64,
    CS_MODE_ARM,
    CS_MODE_RISCV64,
    CS_MODE_RISCVC,
    Cs,
)

# Longest alternative first. Covers x86 (Intel or AT&T, with or without %),
# AArch64 (xN/wN), and RISC-V (ABI names and xN).
REG = re.compile(
    r"\b(?:"
    r"r1[0-5][dwb]|r[0-9][dwb]|r1[0-5]|r[0-9]|"
    r"[er]?[abcd]x|[abcd][hl]|[er]?[sd]i|[er]?[sb]p|[er]?sp|"
    r"dil|sil|bpl|spl|rip|"
    r"x(?:[12]\d|30|31|[0-9])|w(?:[12]\d|30|31|[0-9])|xzr|wzr|"
    r"s1[01]|a[0-7]|s[0-9]|t[0-6]|zero|ra|gp|tp|fp|sp|lr"
    r")\b",
    re.I,
)
IMM = re.compile(r"\b0x[0-9a-fA-F]+\b|\b\d+\b")


@dataclass
class Insn:
    addr: int
    size: int
    mnemonic: str
    op: str
    raw: bytes


def disassemble(blob: bytes, base: int, arch: str) -> list[Insn]:
    if arch == "x86":
        md = Cs(CS_ARCH_X86, CS_MODE_64)
    elif arch == "arm64":
        md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    elif arch == "riscv":
        md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV64 | CS_MODE_RISCVC)
    else:
        raise ValueError(arch)
    # detail is unused; leaving it off keeps the large TAE .text tractable.
    out = []
    offset = 0
    n = len(blob)
    while offset < n:
        progressed = False
        for ins in md.disasm(blob[offset:], base + offset):
            if ins.size <= 0:
                break
            out.append(Insn(ins.address, ins.size, ins.mnemonic, ins.op_str, bytes(ins.bytes)))
            offset += ins.size
            progressed = True
        if not progressed:
            # Capstone stops at the first unknown opcode (for example SERIALIZE).
            # Skip a byte and resume so later gates are not dropped.
            offset += 1
    return out


def _groups(ins: Insn, arch: str) -> set[int]:
    # capstone detail groups live on the raw insn; we re-read via mnemonic
    m = ins.mnemonic
    if arch == "x86":
        jumps = m.startswith("j") or m in {"loop", "loopne", "loope"}
        if jumps or m == "ret" or m == "call":
            return {CS_GRP_JUMP}
        return set()
    if arch == "arm64":
        if m in {"b", "bl", "br", "blr", "ret", "cbz", "cbnz", "tbz", "tbnz"} or m.startswith("b."):
            return {CS_GRP_JUMP}
        return set()
    if m in {"jal", "jalr", "ret", "beq", "bne", "blt", "bge", "bltu", "bgeu", "c.j", "c.jal", "c.jr", "c.jalr", "c.beqz", "c.bnez"}:
        return {CS_GRP_JUMP}
    return set()


def normalize(ins: Insn, abstract: bool) -> str:
    if not abstract:
        text = ins.mnemonic if not ins.op else f"{ins.mnemonic} {ins.op}"
        return text
    op = REG.sub("REG", ins.op)
    op = IMM.sub("IMM", op)
    return ins.mnemonic if not op else f"{ins.mnemonic} {op}"


def basic_blocks(insns: list[Insn], arch: str) -> list[list[Insn]]:
    if not insns:
        return []
    leaders = {insns[0].addr}
    for n, ins in enumerate(insns):
        groups = _groups(ins, arch)
        if groups:
            if n + 1 < len(insns):
                leaders.add(insns[n + 1].addr)
            # Direct target only. Memory operands also contain hex displacements.
            if "[" not in ins.op and "ptr" not in ins.op:
                for hexaddr in re.findall(r"0x[0-9a-fA-F]+", ins.op):
                    leaders.add(int(hexaddr, 16))
    lead_set = leaders
    blocks = []
    cur: list[Insn] = []
    for ins in insns:
        if ins.addr in lead_set and cur:
            blocks.append(cur)
            cur = []
        cur.append(ins)
    if cur:
        blocks.append(cur)
    return blocks


def features(insns: list[Insn], kind: str, abstract: bool, arch: str, n: int = 6) -> list[tuple[str, int, int]]:
    """Return (key, start_addr, end_addr) fragments."""
    rows = []
    if kind == "bb":
        for bb in basic_blocks(insns, arch):
            if len(bb) < 2:
                continue
            key = "|".join(normalize(i, abstract) for i in bb)
            rows.append((key, bb[0].addr, bb[-1].addr + bb[-1].size))
    elif kind == "ngram":
        norm = [normalize(i, abstract) for i in insns]
        for i in range(0, len(insns) - n + 1):
            key = "|".join(norm[i : i + n])
            a = insns[i].addr
            z = insns[i + n - 1]
            rows.append((key, a, z.addr + z.size))
    elif kind == "cfg":
        bbs = basic_blocks(insns, arch)
        bodies = ["|".join(normalize(i, abstract) for i in bb) for bb in bbs]
        for i, bb in enumerate(bbs):
            if not bb:
                continue
            succ = bodies[i + 1] if i + 1 < len(bbs) else ""
            key = bodies[i] + ">>" + succ
            if bodies[i].count("|") < 1 and not succ:
                continue
            rows.append((key, bb[0].addr, bb[-1].addr + bb[-1].size))
    elif kind == "bytes":
        # Raw-byte shingles. End address is the end of the instruction that
        # contains the last shingle byte, so scoring includes that instruction.
        width = n
        raw = b"".join(i.raw for i in insns)
        spans = []
        off = 0
        for ins in insns:
            spans.append((off, ins))
            off += len(ins.raw)

        def insn_at(byte_off: int) -> Insn:
            chosen = spans[0][1]
            for o, ins in spans:
                if o <= byte_off:
                    chosen = ins
                else:
                    break
            return chosen

        for i in range(0, len(raw) - width + 1):
            key = raw[i : i + width].hex()
            start = insn_at(i)
            end = insn_at(i + width - 1)
            rows.append((key, start.addr, end.addr + end.size))
    else:
        raise ValueError(kind)
    return rows


def cluster(rows: list[tuple[str, int, int]], min_count: int = 2) -> dict[str, list[tuple[int, int]]]:
    groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for key, a, b in rows:
        groups[key].append((a, b))
    return {k: v for k, v in groups.items() if len(v) >= min_count}


def is_nop_key(key: str) -> bool:
    """True when every mnemonic in a disassembly key is nop."""
    if not key or all(c in "0123456789abcdef" for c in key):
        return False
    parts = [p for p in key.replace(">>", "|").split("|") if p]
    return bool(parts) and all(p == "nop" or p.startswith("nop ") for p in parts)


def _span_hits_gate(a: int, b: int, gates: list[tuple[int, int, str]], starts: list[int]) -> bool:
    i = bisect.bisect_left(starts, b) - 1
    if i < 0:
        return False
    s, e, _ = gates[i]
    return a < e and s < b


def score(clusters: dict[str, list[tuple[int, int]]], gates: list[tuple[int, int, str]], insns: list[Insn]) -> dict:
    text_bytes = sum(i.size for i in insns)
    n = len(insns)
    empty = {
        "purity": None,
        "recall": 0.0 if gates else None,
        "recall_nonop": 0.0 if gates else None,
        "recall_nonop_90": 0.0 if gates else None,
        "mean_nonop_coverage": 0.0 if gates else None,
        "clusters": 0,
        "members": 0,
        "covered_span_bytes": 0,
        "text_bytes": text_bytes,
        "byte_rate": 0.0,
        "insn_rate": 0.0,
        "fpr": 0.0 if n else None,
        "text_insns": n,
    }
    if not clusters or not insns:
        return empty
    gates = sorted(gates)
    starts = [s for s, _, _ in gates]
    addrs = [ins.addr for ins in insns]
    hit = bytearray(n)
    member_hits = 0
    member_total = 0
    cov_bytes = 0
    for spans in clusters.values():
        for a, b in spans:
            member_total += 1
            cov_bytes += max(0, b - a)
            if gates and _span_hits_gate(a, b, gates, starts):
                member_hits += 1
            i = bisect.bisect_left(addrs, a)
            while i < n and insns[i].addr < b:
                hit[i] = 1
                i += 1
    in_gate = bytearray(n)
    for s, e, _ in gates:
        i = bisect.bisect_left(addrs, s)
        while i < n and insns[i].addr < e:
            in_gate[i] = 1
            i += 1

    def recall_at(threshold: float, skip_nop: bool) -> float | None:
        if not gates:
            return None
        got = 0
        for s, e, _ in gates:
            i = bisect.bisect_left(addrs, s)
            total = 0
            good = 0
            while i < n and insns[i].addr < e:
                if not (skip_nop and insns[i].mnemonic == "nop"):
                    total += 1
                    good += hit[i]
                i += 1
            if total and good / total >= threshold:
                got += 1
        return got / len(gates)

    coverages = []
    if gates:
        for s, e, _ in gates:
            i = bisect.bisect_left(addrs, s)
            total = 0
            good = 0
            while i < n and insns[i].addr < e:
                if insns[i].mnemonic != "nop":
                    total += 1
                    good += hit[i]
                i += 1
            if total:
                coverages.append(good / total)
    outside = 0
    outside_hit = 0
    hit_n = 0
    for i in range(n):
        hit_n += hit[i]
        if not in_gate[i]:
            outside += 1
            outside_hit += hit[i]
    if gates:
        fpr = (outside_hit / outside) if outside else 0.0
    else:
        fpr = (hit_n / n) if n else None
    return {
        "purity": (member_hits / member_total) if member_total else None,
        "recall": recall_at(0.5, False),
        "recall_nonop": recall_at(0.5, True),
        "recall_nonop_90": recall_at(0.9, True),
        "mean_nonop_coverage": (sum(coverages) / len(coverages)) if coverages else (0.0 if gates else None),
        "clusters": len(clusters),
        "members": member_total,
        "covered_span_bytes": cov_bytes,
        "text_bytes": text_bytes,
        "byte_rate": min(1.0, cov_bytes / text_bytes) if text_bytes else 0.0,
        "insn_rate": (hit_n / n) if n else 0.0,
        "fpr": fpr,
        "text_insns": n,
    }


def stable_hash(text: str) -> int:
    return int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "little")


def minhash_sig(tokens: tuple[str, ...], perms: list[tuple[int, int, int]]) -> tuple[int, ...]:
    sig = []
    hashes = [stable_hash(t) for t in tokens]
    for a, b, p in perms:
        sig.append(min((a * h + b) % p for h in hashes))
    return tuple(sig)


def lsh_keys(sig: tuple[int, ...], bands: int) -> list[tuple[int, tuple[int, ...]]]:
    rows = max(1, len(sig) // bands)
    out = []
    for i in range(bands):
        out.append((i, sig[i * rows : (i + 1) * rows]))
    return out
