"""Diffing locator: repeated n-grams → families → gap-separated pairs.

No trigger/decode opcode catalogs. Eval symbol names are never read here
(this loader does not open .symtab).
"""

from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from elftools.elf.elffile import ELFFile

from wf.artifact import PairRegion
from wf.symmetry import locate as locate_symmetry

EXEC = 0x4
_MINER = None


def _miner():
    global _MINER
    if _MINER is None:
        path = Path(__file__).resolve().parents[2] / "experiment" / "repeat miner" / "miner.py"
        spec = importlib.util.spec_from_file_location("wf_exp_miner", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["wf_exp_miner"] = mod
        spec.loader.exec_module(mod)
        _MINER = mod
    return _MINER


def arch_of(elf: ELFFile) -> str:
    machine = elf["e_machine"]
    if machine in ("EM_X86_64", 62):
        return "x86"
    if machine in ("EM_AARCH64", 183):
        return "arm64"
    if machine in ("EM_RISCV", 243):
        return "riscv"
    return "x86"


@dataclass
class TextView:
    path: Path
    arch: str
    blob: bytes
    base: int
    insns: list


def exec_sections(elf: ELFFile) -> list[dict]:
    """Executable sections. Relocatable objects get packed bases so COMDAT
    .text.* copies do not all sit at address 0."""
    out = []
    cursor = 0
    relocatable = elf["e_type"] == "ET_REL"
    for idx, sec in enumerate(elf.iter_sections()):
        if not (int(sec["sh_flags"]) & EXEC):
            continue
        data = sec.data()
        if not data:
            continue
        base = cursor if relocatable else int(sec["sh_addr"])
        out.append({"idx": idx, "name": sec.name, "base": base, "data": data})
        if relocatable:
            cursor += len(data)
    return out


def load_text(path: Path) -> TextView:
    """Load stripped-equivalent .text. Does not read symbol names."""
    path = Path(path)
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        arch = arch_of(elf)
        sections = exec_sections(elf)
    miner = _miner()
    insns = []
    for sec in sections:
        insns.extend(miner.disassemble(sec["data"], sec["base"], arch))
    insns.sort(key=lambda ins: ins.addr)
    blob = b"".join(s["data"] for s in sections)
    base = sections[0]["base"] if sections else 0
    return TextView(path, arch, blob, base, insns)


def _norm(ins, abstract_regs: bool, abstract_imms: bool) -> str:
    miner = _miner()
    op = ins.op
    if abstract_regs:
        op = miner.REG.sub("REG", op)
    if abstract_imms:
        op = miner.IMM.sub("IMM", op)
    return ins.mnemonic if not op else f"{ins.mnemonic} {op}"


def ngram_rows(insns, n: int, abstract_regs: bool, abstract_imms: bool, drop_nop: bool):
    miner = _miner()
    norms = [_norm(i, abstract_regs, abstract_imms) for i in insns]
    rows = []
    for i in range(0, len(insns) - n + 1):
        key = "|".join(norms[i : i + n])
        if drop_nop and miner.is_nop_key(key):
            continue
        a = insns[i].addr
        z = insns[i + n - 1]
        rows.append((key, a, z.addr + z.size))
    return rows


class _UF:
    def __init__(self, xs):
        self.p = {x: x for x in xs}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def merge_families(groups: dict, snap: int, jaccard: float, max_keys: int = 512) -> dict[str, list[str]]:
    """Keys whose occurrence sites match (sliding n-grams of one idiom).

    Large binaries (unrolled AES, TAE) can have tens of thousands of repeated
    keys; all-pairs Jaccard is then too slow. Keep the highest-copy keys.
    """
    keys = sorted(groups, key=lambda k: (-len(groups[k]), k))
    if max_keys and len(keys) > max_keys:
        keys = keys[:max_keys]
    if not keys:
        return {}
    sites = {
        k: frozenset(((a + b) // 2) // snap for a, b in groups[k]) for k in keys
    }
    uf = _UF(keys)
    for i, k1 in enumerate(keys):
        s1 = sites[k1]
        if not s1:
            continue
        for k2 in keys[i + 1 :]:
            s2 = sites[k2]
            inter = len(s1 & s2)
            if not inter:
                continue
            if inter / len(s1 | s2) >= jaccard:
                uf.union(k1, k2)
    fam: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        fam[uf.find(k)].append(k)
    return dict(fam)


def family_spans(fam: dict[str, list[str]], groups: dict) -> dict[str, list[tuple[int, int]]]:
    out = {}
    for fid, ks in fam.items():
        spans = []
        for k in ks:
            spans.extend(groups[k])
        spans.sort()
        merged = []
        for a, b in spans:
            if merged and a <= merged[-1][1] + 8:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        out[fid] = merged
    return out


def _covered(fspans: dict) -> list[tuple[int, int]]:
    spans = []
    for sp in fspans.values():
        spans.extend(sp)
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 4:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _gap_after(end: int, covered: list[tuple[int, int]], min_gap: int, max_gap: int) -> int | None:
    for a, b in covered:
        if b <= end:
            continue
        if a > end:
            hole = a - end
            if min_gap <= hole <= max_gap:
                return a
            return None
        return None
    return None


def pair_across_gaps(
    fspans: dict[str, list[tuple[int, int]]],
    min_gap: int,
    max_gap: int,
    min_matches: int,
) -> list[dict]:
    """Two distinct families on opposite sides of a repeated coverage hole.

    drop_nop punches that hole through a nop sled; we never look at mnemonics
    to decide trigger vs decode. One huge clone class with no second family
    across a gap emits nothing (clone-only pads, simd copies).
    """
    covered = _covered(fspans)
    occ = []
    for fid, spans in fspans.items():
        for a, b in spans:
            occ.append((a, b, fid))
    occ.sort()
    bucket: dict[tuple[str, str], dict] = defaultdict(lambda: {"n": 0, "regs": [], "gaps": []})
    for a, b, fid in occ:
        hole_end = _gap_after(b, covered, min_gap, max_gap)
        if hole_end is None:
            continue
        partner = None
        for a2, b2, fid2 in occ:
            if fid2 == fid:
                continue
            if a2 < hole_end - 8:
                continue
            if a2 > hole_end + 64:
                break
            partner = (a2, b2, fid2)
            break
        if partner is None:
            continue
        a2, b2, fid2 = partner
        pair = (fid, fid2) if fid < fid2 else (fid2, fid)
        bucket[pair]["n"] += 1
        bucket[pair]["regs"].append((min(a, a2), max(b, b2)))
        bucket[pair]["gaps"].append(max(0, a2 - b))
    ranked = []
    for (fa, fb), d in bucket.items():
        if d["n"] < min_matches:
            continue
        ranked.append(
            {
                "family_a": fa,
                "family_b": fb,
                "n": d["n"],
                "regs": d["regs"],
                "gaps": d["gaps"],
            }
        )
    ranked.sort(key=lambda r: -r["n"])
    return ranked


def _disasm_window(insns: list, start: int, end: int, limit: int = 80) -> str:
    lines = []
    for ins in insns:
        if ins.addr + ins.size <= start:
            continue
        if ins.addr >= end:
            break
        text = ins.mnemonic if not ins.op else f"{ins.mnemonic} {ins.op}"
        lines.append(f"{ins.addr:#x}: {text}")
        if len(lines) >= limit:
            lines.append("...")
            break
    return "\n".join(lines)


def _family_dump(fam: dict[str, list[str]], fspans: dict, groups: dict) -> list[dict]:
    out = []
    for fid, ks in fam.items():
        spans = fspans.get(fid) or []
        n_hits = sum(len(groups.get(k) or []) for k in ks)
        out.append(
            {
                "id": fid,
                "n_keys": len(ks),
                "n_hits": n_hits,
                "n_spans": len(spans),
                "keys_head": ks[:8],
                "spans": [{"start": a, "end": b} for a, b in spans[:256]],
            }
        )
    out.sort(key=lambda r: -r["n_hits"])
    return out[:32]


def mine_view_ex(
    view: TextView, miner_cfg: dict, peer_groups: dict | None = None
) -> tuple[list[PairRegion], dict]:
    miner = _miner()
    n = int(miner_cfg.get("n", 6))
    abs_regs = bool(miner_cfg.get("abstract_regs", True))
    abs_imms = bool(miner_cfg.get("abstract_imms", False))
    drop_nop = bool(miner_cfg.get("drop_nop", True))
    min_count = int(miner_cfg.get("min_count", 2))
    snap = int(miner_cfg.get("snap", 16))
    jacc = float(miner_cfg.get("jaccard", 0.4))
    max_keys = int(miner_cfg.get("max_keys", 512))
    min_gap = int(miner_cfg.get("min_gap", 64))
    max_gap = int(miner_cfg.get("max_gap", 2048))
    strategy = str(miner_cfg.get("strategy") or "diff").lower()
    if strategy == "diffing":
        strategy = "diff"
    rows = ngram_rows(view.insns, n, abs_regs, abs_imms, drop_nop)
    groups = miner.cluster(rows, min_count)
    if peer_groups is not None:
        keep = set(groups) & set(peer_groups)
        groups = {k: groups[k] for k in keep}
    fam = merge_families(groups, snap, jacc, max_keys=max_keys)
    fspans = family_spans(fam, groups)
    ngram_keys = {
        k: len(v)
        for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:2000]
    }
    dump: dict = {
        "strategy": strategy,
        "n_insns": len(view.insns),
        "text_base": view.base,
        "n_ngram_rows": len(rows),
        "n_repeated_keys": len(groups),
        "n_keys_for_families": min(len(groups), max_keys),
        "ngram_keys": ngram_keys,
        "families": _family_dump(fam, fspans, groups),
        "pair_spans": [],
        "scores": [],
    }
    if strategy == "symmetry":
        located = locate_symmetry(groups, view.insns, miner_cfg)
        jacc_fams = dump.get("families")
        dump.update(located.dump)
        dump["strategy"] = "symmetry"
        dump["jaccard_families"] = jacc_fams
        dump["ngram_keys"] = ngram_keys
        pairs = [
            PairRegion(
                start=int(p["start"]),
                end=int(p["end"]),
                family_a=str(p["family_a"]),
                family_b=str(p["family_b"]),
                n_matches=int(p["n_matches"]),
                gap=int(p["gap"]),
                disasm=_disasm_window(view.insns, int(p["start"]), int(p["end"])),
            )
            for p in located.pairs
        ]
        dump["pair_spans"] = [
            {"start": p.start, "end": p.end, "family_a": p.family_a, "family_b": p.family_b, "gap": p.gap}
            for p in pairs
        ]
        dump["scores"] = {
            "period": dump.get("period"),
            "autocorr_lag": dump.get("autocorr_lag"),
            "autocorr_R": dump.get("autocorr_R"),
            "fft_period": dump.get("fft_period"),
            "fft_snr": dump.get("fft_snr"),
            "xcorr_lag": dump.get("xcorr_lag"),
            "xcorr_peak": dump.get("xcorr_peak"),
            "n_pairs": len(pairs),
        }
        return pairs, dump

    ranked = pair_across_gaps(fspans, min_gap, max_gap, min_matches=min_count)
    pairs = []
    for row in ranked:
        n_matches = row["n"]
        gaps = row["gaps"]
        for i, (a, b) in enumerate(row["regs"]):
            gap = gaps[i] if i < len(gaps) else (sum(gaps) // len(gaps) if gaps else 0)
            pairs.append(
                PairRegion(
                    start=a,
                    end=b,
                    family_a=row["family_a"],
                    family_b=row["family_b"],
                    n_matches=n_matches,
                    gap=gap,
                    disasm=_disasm_window(view.insns, a, b),
                )
            )
    dump["pair_spans"] = [
        {"start": p.start, "end": p.end, "family_a": p.family_a, "family_b": p.family_b, "gap": p.gap}
        for p in pairs
    ]
    dump["scores"] = [
        {"family_a": r["family_a"], "family_b": r["family_b"], "n": r["n"], "mean_gap": (sum(r["gaps"]) / len(r["gaps"]) if r["gaps"] else 0)}
        for r in ranked
    ]
    return pairs, dump


def mine_view(view: TextView, miner_cfg: dict, peer_groups: dict | None = None) -> list[PairRegion]:
    pairs, _dump = mine_view_ex(view, miner_cfg, peer_groups)
    return pairs


def mine_path(path: Path, miner_cfg: dict) -> tuple[TextView, list[PairRegion]]:
    view, pairs, _dump = mine_path_ex(path, miner_cfg)
    return view, pairs


def mine_path_ex(path: Path, miner_cfg: dict) -> tuple[TextView, list[PairRegion], dict]:
    view = load_text(path)
    peer_groups = None
    peer = miner_cfg.get("peer")
    if peer:
        peer_view = load_text(Path(peer))
        rows = ngram_rows(
            peer_view.insns,
            int(miner_cfg.get("n", 6)),
            bool(miner_cfg.get("abstract_regs", True)),
            bool(miner_cfg.get("abstract_imms", False)),
            bool(miner_cfg.get("drop_nop", True)),
        )
        peer_groups = _miner().cluster(rows, int(miner_cfg.get("min_count", 2)))
    pairs, dump = mine_view_ex(view, miner_cfg, peer_groups)
    dump["elf"] = str(view.path)
    dump["arch"] = view.arch
    return view, pairs, dump
