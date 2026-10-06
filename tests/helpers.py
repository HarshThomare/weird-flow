from __future__ import annotations

import bisect
from pathlib import Path

from elftools.elf.elffile import ELFFile

from wf.artifact import PairRegion
from wf.mine import exec_sections

ROOT = Path(__file__).resolve().parents[1]
FLEXO_TEST = ROOT / "third_party/flexo/circuits/gates/test.elf"
FLEXO_AND = ROOT / "third_party/flexo/circuits/gates/and.elf"
TLB_TEST = ROOT / "third_party/tlb/Flexo/Flexo-TLB/circuits/gates/test.elf"
TAE_GATES = ROOT / "third_party/tae/elf/rerun1/gates.elf"
GITM_AND = ROOT / "tests/fixtures/gitm/main_and.elf"
NEG_DIR = ROOT / "experiment/repeat miner/negatives"
CLANG = Path("/tmp/llvm-17/bin/clang-17")
CLANGXX = Path("/tmp/llvm-17/bin/clang++-17")

DEFAULT_MINER = {
    "n": 6,
    "abstract_regs": True,
    "abstract_imms": False,
    "drop_nop": True,
    "min_count": 2,
    "snap": 16,
    "jaccard": 0.4,
    "min_gap": 64,
    "max_gap": 2048,
}


def keep_name(name: str, kind: str) -> bool:
    if kind == "flexo":
        return "DualGate" in name
    if kind == "tae":
        return name.startswith("jmpreg")
    return False


def eval_gates(path: Path, kind: str) -> list[tuple[int, int, str]]:
    """Eval-only ground truth. The miner never sees these names."""
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        sections = exec_sections(elf)
        by_idx = {s["idx"]: s for s in sections}
        relocatable = elf["e_type"] == "ET_REL"
        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            return []
        syms = []
        for sym in symtab.iter_symbols():
            shndx = sym["st_shndx"]
            if not sym.name or shndx not in by_idx:
                continue
            sec = by_idx[shndx]
            val = sec["base"] + int(sym["st_value"]) if relocatable else int(sym["st_value"])
            syms.append((val, int(sym["st_size"]), sym.name, sec["base"] + len(sec["data"])))
        syms.sort()
        gates = []
        for i, (val, size, name, sec_end) in enumerate(syms):
            if not keep_name(name, kind):
                continue
            if size > 0:
                end = val + size
            elif name.startswith("jmpreg"):
                end = val + 32
            else:
                end = sec_end
                for val2, _, _, _ in syms[i + 1 :]:
                    if val2 > val:
                        end = val2
                        break
            if end > val:
                gates.append((val, end, name))
        return gates


def pair_recall(pairs: list[PairRegion], gates: list[tuple[int, int, str]]) -> tuple[float, int, int]:
    if not gates:
        return 0.0, 0, 0
    hit = 0
    for gs, ge, _ in gates:
        if any(p.start < ge and gs < p.end for p in pairs):
            hit += 1
    return hit / len(gates), hit, len(gates)
