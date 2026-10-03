#!/usr/bin/env python3
"""Repeat miner experiment.

Builds Flexo and TAE-style binaries, records gate spans before stripping,
and scores a repetition miner against that ground truth. Writes
results/metrics.json, results/degradation.svg, and results/summary.txt.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from elftools.elf.elffile import ELFFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miner import (  # noqa: E402
    cluster,
    disassemble,
    features,
    is_nop_key,
    lsh_keys,
    minhash_sig,
    score,
    stable_hash,
)

ROOT = Path("/u/hthomare/weird-flow")
EXP = ROOT / "experiment" / "repeat miner"
NEG = EXP / "negatives"
BUILD = Path("/tmp/repeat-miner-build")
RES = EXP / "results"
CLANG = "/tmp/llvm-17/bin/clang-17"
CLANGXX = "/tmp/llvm-17/bin/clang++-17"
CLANG14 = "/usr/bin/clang-14"
CLANGXX14 = "/usr/bin/clang++-14"
GPP = "/usr/bin/g++"
GCC_DIR = "--gcc-install-dir=/usr/lib/gcc/x86_64-linux-gnu/11"


def cc_prefix(cc: str) -> list[str]:
    # clang-14 rejects --gcc-install-dir. clang-17 needs it to see the host libstdc++.
    name = Path(cc).name
    if name in {"clang-14", "clang++-14"}:
        return []
    if "clang" in name:
        return [GCC_DIR]
    return []
TAE = ROOT / "third_party" / "tae"

SPECS = [
    ("bb", False, 6),
    ("bb", True, 6),
    ("ngram", False, 4),
    ("ngram", True, 4),
    ("ngram", False, 6),
    ("ngram", True, 6),
    ("cfg", False, 6),
    ("cfg", True, 6),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def fmt(x, digits: int = 2) -> str:
    if x is None:
        return "n/a"
    return f"{x:.{digits}f}"


def median(xs: list[float]) -> float | None:
    vals = sorted(v for v in xs if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return 0.5 * (vals[mid - 1] + vals[mid])


EXEC = 0x4
STRIP = "/tmp/llvm-17/bin/llvm-strip"


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


def keep_gate(name: str, positive: str) -> bool:
    if positive == "flexo":
        return "DualGate" in name
    if positive == "tae":
        return name.startswith("jmpreg")
    if positive == "synth":
        return name.startswith("gate") and name[4:].isdigit()
    if positive == "isa":
        return name.startswith("g") and name[1:].isdigit()
    return False


def read_elf(path: Path, positive: str) -> tuple[bytes, int, list[tuple[int, int, str]]]:
    sections, gates = load_view(path, positive)
    ordered = sorted(sections, key=lambda s: s["base"])
    blob = b"".join(s["data"] for s in ordered)
    base = ordered[0]["base"] if ordered else 0
    return blob, base, gates


def load_view(path: Path, positive: str) -> tuple[list[dict], list[tuple[int, int, str]]]:
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        sections = exec_sections(elf)
        by_idx = {s["idx"]: s for s in sections}
        relocatable = elf["e_type"] == "ET_REL"
        symtab = elf.get_section_by_name(".symtab")
        syms = []
        if symtab is not None:
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
            if not keep_gate(name, positive):
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
        return sections, gates


def adopt(src: Path, sid: str, meta: dict, positive: str, arch: str = "x86") -> dict | None:
    stripped = BUILD / f"{sid}.stripped"
    shutil.copyfile(src, stripped)
    proc = run([STRIP, "--strip-all", str(stripped)])
    if proc.returncode != 0:
        log(f"  strip failed {sid}: {(proc.stderr or '')[-180:]}")
        return None
    sections, gates = load_view(src, positive)
    sections_s, _ = load_view(stripped, "none")
    raw = b"".join(s["data"] for s in sections)
    raw_s = b"".join(s["data"] for s in sections_s)
    if raw != raw_s:
        log(f"  text changed under strip: {sid}")
    insns = []
    for sec in sections_s:
        insns.extend(disassemble(sec["data"], sec["base"], arch))
    insns.sort(key=lambda ins: ins.addr)
    blob_s = raw_s
    aligned = 0
    if gates and insns:
        addrs = [ins.addr for ins in insns]
        import bisect

        for start, end, _ in gates:
            i = bisect.bisect_left(addrs, start)
            if i < len(addrs) and addrs[i] < end:
                aligned += 1
    sample = dict(meta)
    sample.update(
        {
            "id": sid,
            "arch": arch,
            "positive": positive,
            "gates": gates,
            "gate_count": len(gates),
            "aligned_gates": aligned,
            "insns": insns,
            "text_bytes": len(blob_s),
            "text_insns": len(insns),
            "feat": {},
        }
    )
    log(f"  {sid}: gates={len(gates)} aligned={aligned} insns={len(insns)} bytes={len(blob_s)}")
    return sample


def groups_of(sample: dict, kind: str, abstract: bool, n: int):
    key = (kind, abstract, n)
    cached = sample["feat"].get(key)
    if cached is None:
        rows = features(sample["insns"], kind, abstract, sample["arch"], n)
        grouped: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for k, a, b in rows:
            grouped[k].append((a, b))
        sample["feat"][key] = grouped
        cached = grouped
    return cached


def mine(sample: dict, kind: str, abstract: bool, n: int, drop_nop: bool = False) -> dict:
    grouped = groups_of(sample, kind, abstract, n)
    if drop_nop:
        grouped = {k: v for k, v in grouped.items() if not is_nop_key(k)}
    else:
        grouped = {k: v for k, v in grouped.items() if len(v) >= 2}
        return _score(grouped, sample)
    # drop_nop path still requires repetition
    grouped = {k: v for k, v in grouped.items() if len(v) >= 2}
    return _score(grouped, sample)


def _score(grouped: dict, sample: dict) -> dict:
    result = score(grouped, sample["gates"], sample["insns"])
    result["gate_count"] = sample["gate_count"]
    return result


def compile_ll(clang: str, opt: str, src: Path, dest: Path) -> tuple[bool, str]:
    cmd = [clang, *cc_prefix(clang), "-c", opt, str(src), "-o", str(dest)]
    proc = run(cmd, timeout=120)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout)[-500:]
    return True, ""


def compile_tae(cxx: str, opt: str, rerun: int, dest: Path) -> tuple[bool, str]:
    srcs = [
        TAE / "src" / "Util.cpp",
        TAE / "src" / "WeirdMachine.cpp",
        TAE / "src" / "TransientWindows" / "RetBased.cpp",
        TAE / "src" / "WeirdStates" / "CacheChannel.cpp",
        TAE / "src" / "WeirdStates" / "IndirectJmp.cpp",
        TAE / "examples" / "gates.cpp",
    ]
    cmd = [cxx, "-std=c++20", opt, f"-DRERUN={rerun}", "-I", str(TAE / "include")]
    cmd.extend(cc_prefix(cxx))
    if Path(cxx).name in {"clang-14", "clang++-14"}:
        cmd += ["-I/usr/include/c++/11", "-I/usr/include/x86_64-linux-gnu/c++/11"]
    cmd += [str(s) for s in srcs] + ["-o", str(dest)]
    proc = run(cmd, timeout=300)
    if proc.returncode != 0 and "clang" in Path(cxx).name:
        cmd.insert(1, "-fno-integrated-as")
        proc = run(cmd, timeout=300)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout)[-800:]
    return True, ""


def build_corpus() -> tuple[list[dict], list[dict]]:
    BUILD.mkdir(parents=True, exist_ok=True)
    samples = []
    notes = []
    flexo = {
        "and": ROOT / "third_party/flexo/circuits/gates/and-wm.ll",
        "test": ROOT / "third_party/flexo/circuits/gates/test-wm.ll",
        "alu": ROOT / "third_party/flexo/circuits/ALU/ALU-wm.ll",
        "sbox": ROOT / "third_party/flexo/circuits/AES/sbox-wm.ll",
    }
    params = {
        "stock": flexo["test"],
        "dcache": ROOT / "third_party/tlb/Flexo/Flexo-DCache/circuits/gates/test-wm.ll",
        "tlb": ROOT / "third_party/tlb/Flexo/Flexo-TLB/circuits/gates/test-wm.ll",
    }
    jobs = []
    for name, path in flexo.items():
        opts = ["-O0", "-O1", "-O2", "-O3", "-Os"] if name in {"and", "test"} else ["-O0", "-O2", "-O3"]
        for opt in opts:
            jobs.append((name, "stock" if name == "test" else name, path, CLANG, "clang-17", opt))
    for param, path in params.items():
        if param == "stock":
            continue
        jobs.append(("test", param, path, CLANG, "clang-17", "-O2"))
    # clang-14 cannot parse the opaque-pointer IR. Record the failure.
    ok, err = compile_ll(CLANG14, "-O2", flexo["test"], BUILD / "clang14-attempt.o")
    notes.append({"what": "clang-14 on test-wm.ll", "ok": ok, "error": err[-300:]})
    log(f"clang-14 wm.ll: {'ok' if ok else 'failed'}")

    for circuit, param, path, clang, compiler, opt in jobs:
        sid = f"flexo-{circuit}-{param}-{compiler}-{opt[1:]}"
        dest = BUILD / f"{sid}.o"
        log(f"compile {sid}")
        good, err = compile_ll(clang, opt, path, dest)
        if not good:
            notes.append({"what": sid, "ok": False, "error": err})
            log(f"  FAIL {err[:200]}")
            continue
        sample = adopt(
            dest,
            sid,
            {"family": "flexo", "circuit": circuit, "param": param, "compiler": compiler, "opt": opt},
            "flexo",
        )
        if sample:
            samples.append(sample)

    tae_jobs = [
        (CLANGXX, "clang-17", "-O0", 1),
        (CLANGXX, "clang-17", "-O2", 1),
        (CLANGXX, "clang-17", "-O3", 1),
        (CLANGXX, "clang-17", "-O2", 3),
        (GPP, "g++-11", "-O2", 1),
        (CLANGXX14, "clang-14", "-O2", 1),
    ]
    for cxx, compiler, opt, rerun in tae_jobs:
        sid = f"tae-{compiler}-{opt[1:]}-rerun{rerun}"
        dest = BUILD / sid
        log(f"compile {sid}")
        try:
            good, err = compile_tae(cxx, opt, rerun, dest)
        except subprocess.TimeoutExpired:
            good, err = False, "timeout"
        if not good:
            notes.append({"what": sid, "ok": False, "error": err})
            log(f"  FAIL {err[:240]}")
            continue
        sample = adopt(
            dest,
            sid,
            {"family": "tae", "circuit": "gates", "param": f"rerun{rerun}", "compiler": compiler, "opt": opt},
            "tae",
        )
        if sample:
            samples.append(sample)

    shipped = TAE / "elf" / "rerun1" / "gates.elf"
    shipped3 = TAE / "elf" / "rerun3" / "gates.elf"
    if shipped.exists():
        sample = adopt(
            shipped,
            "tae-shipped-rerun1",
            {"family": "tae", "circuit": "gates", "param": "rerun1-shipped", "compiler": "clang-17", "opt": "-O2"},
            "tae",
        )
        if sample:
            samples.append(sample)
    if shipped3.exists():
        same = shipped.read_bytes() == shipped3.read_bytes()
        notes.append({"what": "shipped rerun1 vs rerun3 file bytes", "ok": True, "identical": same})
        if not same:
            sample = adopt(
                shipped3,
                "tae-shipped-rerun3",
                {"family": "tae", "circuit": "gates", "param": "rerun3-shipped", "compiler": "clang-17", "opt": "-O2"},
                "tae",
            )
            if sample:
                samples.append(sample)
    return samples, notes


def ablation(samples: list[dict]) -> list[dict]:
    rows = []
    for sample in samples:
        log(f"ablate {sample['id']}")
        for kind, abstract, n in SPECS:
            t0 = time.perf_counter()
            result = mine(sample, kind, abstract, n)
            result.update(
                {
                    "id": sample["id"],
                    "family": sample["family"],
                    "kind": kind,
                    "abstract": abstract,
                    "n": n,
                    "drop_nop": False,
                    "seconds": round(time.perf_counter() - t0, 3),
                }
            )
            rows.append(result)
        if sample["family"] in {"flexo", "tae"}:
            for abstract in (False, True):
                result = mine(sample, "ngram", abstract, 6, drop_nop=True)
                result.update(
                    {
                        "id": sample["id"],
                        "family": sample["family"],
                        "kind": "ngram",
                        "abstract": abstract,
                        "n": 6,
                        "drop_nop": True,
                        "seconds": 0,
                    }
                )
                rows.append(result)
    return rows


def parse_objdump(text: str) -> list[str]:
    import re

    lines = []
    for line in text.splitlines():
        match = re.match(r"\s*[0-9a-f]+:\s+(.*)$", line)
        if not match:
            continue
        inst = re.sub(r"\s+", " ", match.group(1).strip())
        inst = re.sub(r"call\s+[0-9a-f]+\s+<([^>]+)>", r"call \1", inst)
        lines.append(inst)
    return lines


def is_nop_asm(line: str) -> bool:
    head = line.split()[0] if line.split() else ""
    return head in {"nop", "nopw", "nopl"}


def extract_template() -> tuple[list[str], list[list[str]], str]:
    """Return (one gate's logic, every gate's logic, note)."""
    elf = ROOT / "third_party/flexo/circuits/gates/test.elf"
    _, _, gates = read_elf(elf, "flexo")
    bodies = []
    for start, end, name in gates:
        proc = run(
            [
                "objdump",
                "-d",
                "-M",
                "att",
                "--no-show-raw-insn",
                f"--start-address={start}",
                f"--stop-address={end}",
                str(elf),
            ]
        )
        logic = [ln for ln in parse_objdump(proc.stdout) if not is_nop_asm(ln)]
        logic = ["call *%r12" if ln.startswith("call ") else ln for ln in logic]
        bodies.append(logic)
    # Prefer the body that has several movzbq instructions (reorder needs them).
    best = max(bodies, key=lambda b: sum(ln.startswith("movzbq") for ln in b))
    return best, bodies, f"{len(bodies)} DualGate bodies from test.elf; direct calls rewritten to call *%r12 so copies do not embed distinct absolute targets"


def assemble(funcs: list[tuple[str, list[str]]], dest: Path) -> tuple[bool, str]:
    lines = [".text"]
    for name, body in funcs:
        lines.append(f".globl {name}")
        lines.append(f"{name}:")
        lines.extend(f"  {ln}" for ln in body)
        lines.append("  ret")
    dest.with_suffix(".s").write_text("\n".join(lines) + "\n")
    proc = run(["as", str(dest.with_suffix(".s")), "-o", str(dest)])
    if proc.returncode != 0:
        return False, (proc.stderr or "")[-500:]
    return True, ""


def rename_regs(lines: list[str], mapping: dict[str, str]) -> list[str]:
    import re

    out = []
    for line in lines:
        def sub(match: re.Match) -> str:
            base = "r" + match.group(1)
            suf = match.group(2) or ""
            return "§" + mapping.get(base, base) + suf

        line = re.sub(r"%r(1[0-5]|[0-9])([dwb])?", sub, line)
        out.append(line.replace("§", "%"))
    return out


def sprinkle(lines: list[str], gap: int) -> list[str]:
    out = []
    for line in lines:
        out.append(line)
        out.extend(["nop"] * gap)
    return out


def score_objs(specs: list[tuple[str, bool, int]], dest: Path, sid: str) -> dict:
    sample = adopt(dest, sid, {"family": "obfuscation"}, "synth")
    if sample is None:
        return {"error": "strip failed"}
    out = {"gates": sample["gate_count"], "insns": sample["text_insns"]}
    for kind, abstract, n in specs:
        result = mine(sample, kind, abstract, n)
        tag = f"{kind}-{'abs' if abstract else 'raw'}-n{n}"
        out[tag] = {
            "recall": result["recall"],
            "recall_nonop": result["recall_nonop"],
            "purity": result["purity"],
            "fpr": result["fpr"],
            "clusters": result["clusters"],
        }
    return out


def obfuscation() -> dict:
    log("obfuscation")
    template, bodies, note = extract_template()
    specs = [("ngram", False, 6), ("ngram", True, 6), ("bb", True, 6)]
    import re

    regs = []
    for match in re.findall(r"%r(1[0-5]|[89])", " ".join(template)):
        name = "r" + match
        if name not in regs:
            regs.append(name)
    regs.sort(key=lambda r: int(r[1:]))
    report: dict = {
        "note": note
        + f". Rename rotates {regs or 'no rN'}. Reorder is a distinct shuffle of the whole body. Junk inserts a copy-specific run of nops after every instruction.",
        "template_insns": len(template),
        "curves": {},
    }
    n_copies = 8

    def altered_count(frac: float) -> int:
        return int(round(frac * n_copies))

    fracs = [0.0, 0.25, 0.5, 0.75, 1.0]
    # Register renaming: a growing fraction of copies get a unique permutation.
    points = []
    for frac in fracs:
        n_alt = altered_count(frac)
        funcs = []
        alt = 0
        for i in range(n_copies):
            body = list(template)
            if i >= n_copies - n_alt and len(regs) > 1:
                if alt == len(regs) - 1:
                    spun = list(reversed(regs))
                else:
                    shift = (alt % (len(regs) - 1)) + 1
                    spun = regs[shift:] + regs[:shift]
                alt += 1
                body = rename_regs(body, dict(zip(regs, spun)))
            funcs.append((f"gate{i}", body))
        dest = BUILD / f"obf-rename-{frac:.2f}.o"
        ok, err = assemble(funcs, dest)
        if not ok:
            points.append({"x": frac, "error": err})
            continue
        scored = score_objs(specs, dest, f"obf-rename-{frac:.2f}")
        scored["x"] = frac
        scored["altered"] = n_alt
        points.append(scored)
    report["curves"]["rename"] = points

    points = []
    for frac in fracs:
        n_alt = altered_count(frac)
        funcs = []
        for i in range(n_copies):
            body = list(template)
            if i >= n_copies - n_alt:
                body = list(template)
                random.Random(1000 + i).shuffle(body)
            funcs.append((f"gate{i}", body))
        dest = BUILD / f"obf-reorder-{frac:.2f}.o"
        ok, err = assemble(funcs, dest)
        if not ok:
            points.append({"x": frac, "error": err})
            continue
        scored = score_objs(specs, dest, f"obf-reorder-{frac:.2f}")
        scored["x"] = frac
        scored["altered"] = n_alt
        points.append(scored)
    report["curves"]["reorder"] = points

    points = []
    for frac in fracs:
        n_alt = altered_count(frac)
        funcs = []
        for i in range(n_copies):
            body = list(template)
            if i >= n_copies - n_alt:
                body = sprinkle(body, gap=1 + i)
            funcs.append((f"gate{i}", body))
        dest = BUILD / f"obf-junk-{frac:.2f}.o"
        ok, err = assemble(funcs, dest)
        if not ok:
            points.append({"x": frac, "error": err})
            continue
        scored = score_objs(specs, dest, f"obf-junk-{frac:.2f}")
        scored["x"] = frac
        scored["altered"] = n_alt
        points.append(scored)
    report["curves"]["junk"] = points

    # Sled length on the real unique bodies, and on eight copies of one body.
    sled_unique = []
    sled_same = []
    for length in (0, 8, 32, 128, 256):
        funcs = []
        for i, logic in enumerate(bodies):
            funcs.append((f"gate{i}", list(logic) + ["nop"] * length))
        dest = BUILD / f"obf-sled-unique-{length}.o"
        ok, err = assemble(funcs, dest)
        if not ok:
            sled_unique.append({"x": length, "error": err})
        else:
            scored = score_objs(specs, dest, f"obf-sled-unique-{length}")
            scored["x"] = length
            sled_unique.append(scored)
        funcs = [(f"gate{i}", list(template) + ["nop"] * length) for i in range(n_copies)]
        dest = BUILD / f"obf-sled-same-{length}.o"
        ok, err = assemble(funcs, dest)
        if not ok:
            sled_same.append({"x": length, "error": err})
        else:
            scored = score_objs(specs, dest, f"obf-sled-same-{length}")
            scored["x"] = length
            sled_same.append(scored)
    report["curves"]["sled_unique"] = sled_unique
    report["curves"]["sled_same"] = sled_same
    return report


def reloc_names(path: Path) -> list[str]:
    names = set()
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        for sec in elf.iter_sections():
            if sec.header["sh_type"] not in {"SHT_REL", "SHT_RELA"}:
                continue
            symtab = elf.get_section(sec["sh_link"])
            for rel in sec.iter_relocations():
                sym = symtab.get_symbol(rel["r_info_sym"])
                if sym.name:
                    names.add(sym.name)
    return sorted(names)


def compile_negatives() -> tuple[list[dict], list[dict]]:
    log("hard negatives")
    notes = []
    samples = []
    jobs = [
        ("unrolled-crypto", ["-O3"], NEG / "unrolled_crypto.c", CLANG, False),
        ("simd", ["-O3", "-mavx2"], NEG / "simd_kernel.c", CLANG, False),
        ("templates", ["-O3", "-std=c++20"], NEG / "templates.cpp", CLANGXX, False),
        ("inlined-libc", ["-O3"], NEG / "inlined_libc.c", CLANG, False),
    ]
    for name, flags, src, cc, _ in jobs:
        dest = BUILD / f"neg-{name}.o"
        cmd = [cc, *cc_prefix(cc), "-c", *flags, str(src), "-o", str(dest)]
        proc = run(cmd)
        if proc.returncode != 0:
            notes.append({"what": name, "ok": False, "error": (proc.stderr or "")[-500:]})
            log(f"  FAIL {name}")
            continue
        relocs = reloc_names(dest)
        sample = adopt(dest, f"neg-{name}", {"family": "negative", "circuit": name, "relocs": relocs}, "none")
        if sample:
            samples.append(sample)
            notes.append({"what": name, "ok": True, "relocs": relocs})
    return samples, notes


def scaling() -> list[dict]:
    log("scaling")
    rng = random.Random(0)
    prime = 2**31 - 1
    perms = [(rng.randrange(1, prime), rng.randrange(0, prime), prime) for _ in range(16)]
    bands = 4
    proto = {
        "A": tuple(f"a{i}" for i in range(32)),
        "B": tuple(f"b{i}" for i in range(32)),
    }
    rows = []
    for n in (16, 256, 4096, 65536):
        docs = []
        proto_at = {}
        per = n // 2
        for fam in ("A", "B"):
            proto_at[fam] = len(docs)
            docs.append((fam, proto[fam], True))
            for k in range(per - 1):
                toks = list(proto[fam])
                for t in range(len(toks)):
                    if rng.random() < 0.10:
                        toks[t] = f"n{fam}{k}_{t}"
                docs.append((fam, tuple(toks), False))
        t0 = time.perf_counter()
        exact: dict[tuple, int] = defaultdict(int)
        for _, toks, _ in docs:
            exact[toks] += 1
        exact_s = time.perf_counter() - t0
        noisy = [d for d in docs if not d[2]]
        exact_hit = sum(1 for _, toks, _ in noisy if exact[toks] >= 2)

        t1 = time.perf_counter()
        keys = []
        buckets: dict[tuple, int] = defaultdict(int)
        for _, toks, _ in docs:
            sig = minhash_sig(toks, perms)
            got = lsh_keys(sig, bands)
            keys.append(got)
            for key in got:
                buckets[key] += 1
        # touch the bucket table so the build is part of the timed work
        _ = len(buckets)
        lsh_s = time.perf_counter() - t1
        proto_keys = {fam: set(keys[proto_at[fam]]) for fam in ("A", "B")}
        other = {"A": "B", "B": "A"}
        lsh_hit = 0
        lsh_false = 0
        for i, (fam, _, clean) in enumerate(docs):
            if clean:
                continue
            if any(k in proto_keys[fam] for k in keys[i]):
                lsh_hit += 1
            if any(k in proto_keys[other[fam]] for k in keys[i]):
                lsh_false += 1
        denom = max(1, len(noisy))
        rows.append(
            {
                "n": n,
                "exact_seconds": round(exact_s, 4),
                "lsh_seconds": round(lsh_s, 4),
                "exact_near_dup_rate": exact_hit / denom,
                "lsh_prototype_recall": lsh_hit / denom,
                "lsh_cross_family_rate": lsh_false / denom,
                "exact_distinct_keys": len(exact),
                "lsh_buckets": len(buckets),
                "hash": stable_hash("probe"),
            }
        )
        log(f"  n={n} exact={exact_s:.3f}s lsh={lsh_s:.3f}s recall={lsh_hit/denom:.2f}")
    return rows


def compile_isa() -> tuple[list[dict], list[dict]]:
    log("isa")
    notes = []
    samples = []
    targets = [
        ("x86", None, []),
        ("arm64", "aarch64-linux-gnu", []),
        ("riscv", "riscv64-linux-gnu", ["-march=rv64gc"]),
    ]
    files = [
        ("repeated", NEG / "repeated_gate.c", CLANG, ["-std=c11"], "isa"),
        ("crypto", NEG / "unrolled_crypto.c", CLANG, ["-std=c11"], "none"),
        ("templates", NEG / "templates.cpp", CLANGXX, ["-std=c++20", "-fno-exceptions", "-fno-rtti"], "none"),
    ]
    for arch, target, extra in targets:
        for name, src, cc, flags, positive in files:
            sid = f"isa-{arch}-{name}"
            dest = BUILD / f"{sid}.o"
            cmd = [cc, *cc_prefix(cc), "-c", "-O2", "-ffreestanding", "-nostdlib", "-fno-builtin", *flags, *extra]
            if target:
                cmd += ["-target", target]
            cmd += [str(src), "-o", str(dest)]
            proc = run(cmd)
            if proc.returncode != 0:
                notes.append({"what": sid, "ok": False, "error": (proc.stderr or "")[-400:]})
                log(f"  FAIL {sid}")
                continue
            sample = adopt(dest, sid, {"family": "isa", "circuit": name, "compiler": arch}, positive, arch=arch)
            if sample:
                samples.append(sample)
                notes.append({"what": sid, "ok": True, "gates": sample["gate_count"], "insns": sample["text_insns"]})
    return samples, notes


def isa_report(samples: list[dict]) -> dict:
    specs = [("bytes", False, 6), ("ngram", False, 6), ("ngram", True, 6), ("bb", True, 6)]
    per = []
    by_key = {}
    for sample in samples:
        row = {"id": sample["id"], "arch": sample["arch"], "circuit": sample["circuit"], "gates": sample["gate_count"]}
        for kind, abstract, n in specs:
            result = mine(sample, kind, abstract, n)
            tag = f"{kind}-{'abs' if abstract else 'raw'}"
            row[tag] = {
                "recall": result["recall"],
                "recall_nonop": result["recall_nonop"],
                "fpr": result["fpr"],
                "insn_rate": result["insn_rate"],
                "purity": result["purity"],
                "clusters": result["clusters"],
            }
            by_key[(sample["arch"], sample["circuit"], kind, abstract)] = set(groups_of(sample, kind, abstract, n))
        per.append(row)

    def jaccard(a: set, b: set) -> float | None:
        if not a and not b:
            return None
        return len(a & b) / len(a | b)

    crosses = []
    for circuit in ("repeated", "crypto", "templates"):
        for kind, abstract in (("bytes", False), ("ngram", False), ("ngram", True)):
            keys = {}
            for arch in ("x86", "arm64", "riscv"):
                # repeated clusters only: keys with... groups_of includes count 1.
                # Use mined clusters (count>=2) for the agnostic claim.
                sample = next((s for s in samples if s["arch"] == arch and s["circuit"] == circuit), None)
                if sample is None:
                    continue
                grouped = groups_of(sample, kind, abstract, 6)
                keys[arch] = {k for k, v in grouped.items() if len(v) >= 2}
            for left, right in (("x86", "arm64"), ("x86", "riscv"), ("arm64", "riscv")):
                if left in keys and right in keys:
                    crosses.append(
                        {
                            "circuit": circuit,
                            "kind": kind,
                            "abstract": abstract,
                            "pair": f"{left}/{right}",
                            "jaccard": jaccard(keys[left], keys[right]),
                            "left": len(keys[left]),
                            "right": len(keys[right]),
                            "shared": len(keys[left] & keys[right]),
                        }
                    )
    return {"samples": per, "cross_isa_keys": crosses}


def mode_report(samples: list[dict]) -> list[dict]:
    log("mode")
    want = {s["id"]: s for s in samples}

    def find(prefix: str) -> dict | None:
        return want.get(prefix)

    pairs = []
    flexo_o0 = find("flexo-test-stock-clang-17-O0")
    flexo_o2 = find("flexo-test-stock-clang-17-O2")
    dcache = find("flexo-test-dcache-clang-17-O2")
    tlb = find("flexo-test-tlb-clang-17-O2")
    tae_o0 = find("tae-clang-17-O0-rerun1")
    tae_o2 = find("tae-clang-17-O2-rerun1")
    tae_g = next((s for s in samples if s["id"].startswith("tae-g++")), None)
    if flexo_o0 and flexo_o2:
        pairs.append(("flexo opt O0 vs O2", flexo_o0, flexo_o2))
    if flexo_o2 and dcache:
        pairs.append(("flexo stock vs dcache", flexo_o2, dcache))
    if flexo_o2 and tlb:
        pairs.append(("flexo stock vs tlb", flexo_o2, tlb))
    if tae_o0 and tae_o2:
        pairs.append(("tae opt O0 vs O2", tae_o0, tae_o2))
    if tae_o2 and tae_g:
        pairs.append(("tae clang vs g++", tae_o2, tae_g))

    specs = [("ngram", False, 6), ("ngram", True, 6), ("bb", False, 6), ("bb", True, 6)]
    rows = []
    for label, left, right in pairs:
        for kind, abstract, n in specs:
            gl = groups_of(left, kind, abstract, n)
            gr = groups_of(right, kind, abstract, n)
            single = {k: v for k, v in gr.items() if len(v) >= 2}
            cross = {k: gr[k] for k in gl.keys() & gr.keys()}
            stable = {k: v for k, v in cross.items() if len(gl[k]) >= 2 and len(v) >= 2}
            one = _score(single, right)
            two = _score(cross, right)
            three = _score(stable, right)
            rows.append(
                {
                    "pair": label,
                    "target": right["id"],
                    "kind": kind,
                    "abstract": abstract,
                    "single_recall": one["recall"],
                    "single_recall_nonop": one["recall_nonop"],
                    "single_fpr": one["fpr"],
                    "single_purity": one["purity"],
                    "cross_recall": two["recall"],
                    "cross_recall_nonop": two["recall_nonop"],
                    "cross_fpr": two["fpr"],
                    "cross_purity": two["purity"],
                    "cross_clusters": two["clusters"],
                    "stable_recall": three["recall"],
                    "stable_recall_nonop": three["recall_nonop"],
                    "stable_fpr": three["fpr"],
                    "stable_purity": three["purity"],
                    "stable_clusters": three["clusters"],
                }
            )
    return rows


def series(points: list[dict], tag: str, field: str) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for point in points:
        block = point.get(tag)
        if not isinstance(block, dict):
            continue
        val = block.get(field)
        if val is None:
            continue
        xs.append(point["x"])
        ys.append(val)
    return xs, ys


def write_svg(obf: dict, path: Path) -> None:
    panels = [
        (
            "Register renaming (fraction of copies with a distinct rN rotation)",
            "fraction altered",
            [
                ("ngram raw recall", *series(obf["curves"]["rename"], "ngram-raw-n6", "recall"), "#1b4f72", ""),
                ("ngram abstract recall", *series(obf["curves"]["rename"], "ngram-abs-n6", "recall"), "#b03a2e", ""),
                ("ngram abstract non-nop", *series(obf["curves"]["rename"], "ngram-abs-n6", "recall_nonop"), "#1e8449", "4 3"),
            ],
        ),
        (
            "Instruction reordering (fraction of copies with a distinct full shuffle)",
            "fraction altered",
            [
                ("ngram raw recall", *series(obf["curves"]["reorder"], "ngram-raw-n6", "recall"), "#1b4f72", ""),
                ("ngram abstract recall", *series(obf["curves"]["reorder"], "ngram-abs-n6", "recall"), "#b03a2e", ""),
                ("ngram abstract non-nop", *series(obf["curves"]["reorder"], "ngram-abs-n6", "recall_nonop"), "#1e8449", "4 3"),
            ],
        ),
        (
            "Junk insertion (fraction of copies with a distinct nop after every instruction)",
            "fraction altered",
            [
                ("ngram raw recall", *series(obf["curves"]["junk"], "ngram-raw-n6", "recall"), "#1b4f72", ""),
                ("ngram abstract recall", *series(obf["curves"]["junk"], "ngram-abs-n6", "recall"), "#b03a2e", ""),
                ("ngram abstract non-nop", *series(obf["curves"]["junk"], "ngram-abs-n6", "recall_nonop"), "#1e8449", "4 3"),
            ],
        ),
        (
            "Nop sled length on the eight real DualGate bodies",
            "sled nops",
            [
                ("unique bodies recall", *series(obf["curves"]["sled_unique"], "ngram-abs-n6", "recall"), "#b03a2e", ""),
                ("unique bodies non-nop", *series(obf["curves"]["sled_unique"], "ngram-abs-n6", "recall_nonop"), "#1e8449", "4 3"),
                ("same body recall", *series(obf["curves"]["sled_same"], "ngram-abs-n6", "recall"), "#1b4f72", ""),
            ],
        ),
    ]
    width = 760
    panel_h = 210
    height = 36 + len(panels) * panel_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfbfb"/>',
        '<style>text{font-family:ui-monospace,monospace;font-size:12px;fill:#222}</style>',
    ]

    def esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;")

    for p_i, (title, xlabel, lines) in enumerate(panels):
        top = 28 + p_i * panel_h
        left, right, plot_h = 56, 16, 140
        bottom = top + plot_h
        parts.append(f'<text x="56" y="{top - 8}">{esc(title)}</text>')
        xs = [x for row in lines for x in row[1]]
        if not xs:
            parts.append(f'<text x="56" y="{top + 40}">no points</text>')
            continue
        xmin, xmax = min(xs), max(xs)
        if xmin == xmax:
            xmax = xmin + 1

        def px(x: float) -> float:
            return left + (x - xmin) / (xmax - xmin) * (width - left - right)

        def py(y: float) -> float:
            return bottom - y * plot_h

        parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#999"/>')
        parts.append(f'<line x1="{left}" y1="{bottom}" x2="{width - right}" y2="{bottom}" stroke="#999"/>')
        for tick in (0, 0.5, 1):
            y = py(tick)
            parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#eee"/>')
            parts.append(f'<text x="8" y="{y + 4:.1f}">{tick:.1f}</text>')
        parts.append(f'<text x="{left}" y="{bottom + 28}">{esc(xlabel)}</text>')
        parts.append(f'<text x="{left}" y="{bottom + 44}">{xmin:g} … {xmax:g}</text>')
        for name, xvals, yvals, color, dash in lines:
            if len(xvals) < 1:
                continue
            pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(xvals, yvals))
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2"{dash_attr} points="{pts}"/>')
            for x, y in zip(xvals, yvals):
                parts.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="2.5" fill="{color}"/>')
        legend_x = width - 280
        for j, (name, _, _, color, _) in enumerate(lines):
            ly = top + 4 + j * 16
            parts.append(f'<rect x="{legend_x}" y="{ly}" width="10" height="10" fill="{color}"/>')
            parts.append(f'<text x="{legend_x + 16}" y="{ly + 10}">{esc(name)}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n")


def row_of(rows: list[dict], sid: str, kind: str, abstract: bool, n: int = 6, drop_nop: bool = False) -> dict | None:
    for row in rows:
        if (
            row["id"] == sid
            and row["kind"] == kind
            and row["abstract"] is abstract
            and row["n"] == n
            and row.get("drop_nop", False) is drop_nop
        ):
            return row
    return None


def write_summary(payload: dict, path: Path) -> None:
    rows = payload["ablation"]
    samples = payload["samples"]
    lines = []
    lines.append("Repeat miner")
    lines.append("")
    lines.append("Core question: does repetition alone separate weird gates from everything else, and at what granularity?")
    lines.append("")
    lines.append("Ground truth is DualGate symbols in Flexo objects and jmpreg symbols in TAE binaries, recorded before strip --strip-all. The miner sees only the stripped .text bytes. A repeated cluster is an exact feature key with count >= 2. Recall is the fraction of ground-truth gates whose instructions are at least 50% covered. recall_nonop drops nop instructions from that fraction. recall_nonop_90 requires 90% of the non-nop instructions. Purity is the fraction of repeated-cluster members whose span overlaps a gate. FPR is the fraction of instructions outside every gate that still fall in a repeated cluster (on a binary with no gates, that is just instruction coverage).")
    lines.append("")

    def sid_row(family_pred, kind, abstract, drop=False):
        return [
            r
            for r in rows
            if family_pred(r) and r["kind"] == kind and r["abstract"] is abstract and r["n"] == 6 and r.get("drop_nop", False) is drop
        ]

    flexo = [s for s in samples if s["family"] == "flexo"]
    tae = [s for s in samples if s["family"] == "tae"]
    lines.append("Ground truth")
    lines.append(f"Flexo objects: {len(flexo)}. TAE binaries: {len(tae)}.")
    for note in payload["builds"]:
        if note.get("ok") is False:
            err = (note.get("error") or "").replace("\n", " ")[:180]
            lines.append(f"Build failed: {note['what']}: {err}")
        elif "identical" in note:
            lines.append(
                "Shipped TAE rerun1 and rerun3 gates.elf are "
                + ("byte-identical. " if note["identical"] else "not byte-identical. ")
                + "RERUN does not change this pair of shipped images, so the parameter axis is the fresh rerun1 vs rerun3 rebuild plus the Flexo stock/dcache/tlb IR, which were produced with different weird-machine sizes."
            )
    lines.append("Gate alignment (symbol span contains at least one instruction):")
    for sample in samples:
        if sample["family"] not in {"flexo", "tae"}:
            continue
        lines.append(
            f"  {sample['id']}: gates={sample['gate_count']} aligned={sample['aligned_gates']} insns={sample['text_insns']}"
        )
    lines.append("")

    focus_id = "flexo-test-stock-clang-17-O2"
    sbox_id = "flexo-sbox-sbox-clang-17-O2"
    alu_id = "flexo-alu-alu-clang-17-O2"
    and_id = "flexo-and-and-clang-17-O2"
    tae_id = "tae-clang-17-O2-rerun1"
    lines.append("Granularity on Flexo test -O2 (clang-17, stock IR) and TAE gates -O2.")
    lines.append("kind        abs  recall  nonop  nonop90  mean_logic  purity  fpr    clusters")
    for sid in (focus_id, sbox_id, tae_id):
        lines.append(f"[{sid}]")
        for kind, abstract, n in SPECS:
            if n not in (6,) and kind == "ngram":
                pass
            row = row_of(rows, sid, kind, abstract, n, False)
            if row is None:
                continue
            lines.append(
                f"{kind:6} n={n:<2} {str(abstract):5} {fmt(row['recall']):7} {fmt(row['recall_nonop']):6} {fmt(row['recall_nonop_90']):8} {fmt(row['mean_nonop_coverage']):10} {fmt(row['purity']):7} {fmt(row['fpr']):6} {row['clusters']}"
            )
        for abstract in (False, True):
            row = row_of(rows, sid, "ngram", abstract, 6, True)
            if row is None:
                continue
            lines.append(
                f"ngram n=6 drop-nop abs={abstract} recall={fmt(row['recall'])} nonop={fmt(row['recall_nonop'])} purity={fmt(row['purity'])} fpr={fmt(row['fpr'])} clusters={row['clusters']}"
            )
    lines.append("")
    lines.append("Opt sweep, Flexo test, n-gram-6 abstract:")
    lines.append("opt  recall  nonop  nonop90  mean_logic  purity  fpr")
    for opt in ("O0", "O1", "O2", "O3", "Os"):
        row = row_of(rows, f"flexo-test-stock-clang-17-{opt}", "ngram", True, 6, False)
        if row:
            lines.append(
                f"{opt:4} {fmt(row['recall']):7} {fmt(row['recall_nonop']):6} {fmt(row['recall_nonop_90']):8} {fmt(row['mean_nonop_coverage']):10} {fmt(row['purity']):7} {fmt(row['fpr'])}"
            )
    lines.append("Build parameters, Flexo test -O2, n-gram-6 abstract:")
    for param in ("stock", "dcache", "tlb"):
        row = row_of(rows, f"flexo-test-{param}-clang-17-O2", "ngram", True, 6, False)
        if row:
            lines.append(
                f"  {param:8} recall={fmt(row['recall'])} nonop={fmt(row['recall_nonop'])} purity={fmt(row['purity'])} fpr={fmt(row['fpr'])} gates={row['gate_count']}"
            )
    and_row = row_of(rows, and_id, "ngram", True, 6, False)
    alu_row = row_of(rows, alu_id, "ngram", True, 6, False)
    if and_row:
        if and_row["gate_count"] == 1 and (and_row["recall"] or 0) >= 0.5:
            lines.append(
                f"and.ll has a single DualGate and n-gram-6 abstract recall is still {fmt(and_row['recall'])}. The sled repeats inside that one function, so the miner does not need a second gate."
            )
        else:
            lines.append(
                f"and.ll has {and_row['gate_count']} DualGate. n-gram-6 abstract recall={fmt(and_row['recall'])}."
            )
    if alu_row:
        lines.append(
            f"ALU -O2 n-gram-6 abstract recall={fmt(alu_row['recall'])} nonop={fmt(alu_row['recall_nonop'])} mean_logic={fmt(alu_row['mean_nonop_coverage'])} purity={fmt(alu_row['purity'])}."
        )

    focus = row_of(rows, focus_id, "ngram", True, 6, False)
    focus_raw = row_of(rows, focus_id, "ngram", False, 6, False)
    focus_drop = row_of(rows, focus_id, "ngram", True, 6, True)
    bb = row_of(rows, focus_id, "bb", True, 6, False)
    cfg = row_of(rows, focus_id, "cfg", True, 6, False)
    n4 = row_of(rows, focus_id, "ngram", True, 4, False)
    tae_abs = row_of(rows, tae_id, "ngram", True, 6, False)
    tae_raw = row_of(rows, tae_id, "ngram", False, 6, False)
    lines.append("")
    lines.append("What the numbers say about granularity:")
    if focus and focus_raw and focus_drop and bb and cfg:
        lines.append(
            f"On Flexo test -O2 the bodies are mostly a shared nop sled (recall {fmt(focus['recall'])} with nops in the denominator, non-nop recall {fmt(focus['recall_nonop'])}, mean logic coverage {fmt(focus['mean_nonop_coverage'])}, 90% bar {fmt(focus['recall_nonop_90'])})."
        )
        if (focus["recall"] or 0) > (focus["recall_nonop"] or 0) + 0.2:
            lines.append("Including nops inflates gate recall. The miner is leaning on the sled.")
        else:
            lines.append("Dropping nops from the coverage test does not by itself erase recall, so some non-nop bytes are shared too.")
        lines.append(
            f"Deleting nop-only clusters moves all-insn recall from {fmt(focus['recall'])} to {fmt(focus_drop['recall'])} and leaves non-nop recall at {fmt(focus_drop['recall_nonop'])}."
        )
        if (focus_drop["recall"] or 0) + 0.2 < (focus["recall"] or 0) and (focus_drop["recall_nonop"] or 0) >= 0.5:
            lines.append("The 50% bar over every byte, nops included, is what the sled was carrying. The non-nop instructions stay covered by repeated logic, and abstraction is what pushes that coverage to the whole gate.")
        elif (focus_drop["recall_nonop"] or 0) + 0.2 < (focus["recall_nonop"] or 0):
            lines.append("Dropping nop-only clusters also drops non-nop recall, so the sled was the feature that touched the logic bytes (mixed nop/logic windows).")
        lines.append(
            f"Same binary, abstract features: basic-block recall {fmt(bb['recall'])} non-nop {fmt(bb['recall_nonop'])}; CFG-edge recall {fmt(cfg['recall'])} non-nop {fmt(cfg['recall_nonop'])}; 4-gram recall {fmt(n4['recall'])} non-nop {fmt(n4['recall_nonop'])}; 6-gram raw recall {fmt(focus_raw['recall'])} non-nop {fmt(focus_raw['recall_nonop'])} purity {fmt(focus_raw['purity'])} versus abstract purity {fmt(focus['purity'])}."
        )
        if bb["recall_nonop"] < focus["recall_nonop"] - 0.15:
            lines.append("Basic blocks are coarser than the repeated fragment: a whole gate-plus-fallthrough rarely matches another gate, so block keys miss gates that n-grams hit.")
        if abs((focus["recall_nonop"] or 0) - (focus_raw["recall_nonop"] or 0)) < 0.1:
            lines.append("Register and constant abstraction barely moves Flexo non-nop recall. The repeated part was already identical, including register names, or it was nops.")
        elif (focus["recall_nonop"] or 0) > (focus_raw["recall_nonop"] or 0) + 0.1:
            lines.append("Abstraction raises non-nop recall: gates share an instruction shape but not concrete registers or immediates.")
    if tae_abs and tae_raw:
        lines.append(
            f"TAE -O2 n-gram-6 raw recall {fmt(tae_raw['recall'])} non-nop {fmt(tae_raw['recall_nonop'])} purity {fmt(tae_raw['purity'])} fpr {fmt(tae_raw['fpr'])} clusters {tae_raw['clusters']}. Abstract: recall {fmt(tae_abs['recall'])} non-nop {fmt(tae_abs['recall_nonop'])} purity {fmt(tae_abs['purity'])} fpr {fmt(tae_abs['fpr'])} clusters {tae_abs['clusters']}."
        )
        if (tae_raw["purity"] or 0) > (tae_abs["purity"] or 0) + 0.1:
            lines.append("Constant abstraction lowers TAE purity. The decode table is thousands of `mov immediate; ret` sites; once the immediate is erased they cluster, and they are not jmpreg gates.")
        if (tae_raw["recall"] or 0) > 0.8:
            lines.append("The jmpreg gates themselves are one repeated `jmp` plus a fixed pad, so raw repetition recalls them without any weirdness test. That is recall of a clone, not a test that the clone is weird.")
    lines.append("")

    lines.append("Obfuscation")
    lines.append(payload["obfuscation"].get("note", ""))
    lines.append("Eight copies of one DualGate body. A growing fraction is altered so those copies no longer match each other. Recall is n-gram-6.")
    for name in ("rename", "reorder", "junk"):
        lines.append(f"  {name}:")
        for point in payload["obfuscation"]["curves"][name]:
            if "error" in point and "ngram-abs-n6" not in point:
                lines.append(f"    x={point['x']}: assembler error {point['error'][:160]}")
                continue
            raw = point.get("ngram-raw-n6", {})
            ab = point.get("ngram-abs-n6", {})
            lines.append(
                f"    x={point['x']}: raw recall {fmt(raw.get('recall'))} nonop {fmt(raw.get('recall_nonop'))}; abstract recall {fmt(ab.get('recall'))} nonop {fmt(ab.get('recall_nonop'))}"
            )
    lines.append("Sled length, eight distinct DualGate bodies in one object (abstract n-gram-6):")
    for point in payload["obfuscation"]["curves"]["sled_unique"]:
        if "ngram-abs-n6" not in point:
            lines.append(f"  L={point.get('x')}: {point.get('error','missing')[:160]}")
            continue
        ab = point["ngram-abs-n6"]
        raw = point.get("ngram-raw-n6", {})
        lines.append(
            f"  L={point['x']}: abstract recall {fmt(ab.get('recall'))} nonop {fmt(ab.get('recall_nonop'))}; raw recall {fmt(raw.get('recall'))} nonop {fmt(raw.get('recall_nonop'))}"
        )
    lines.append("Same body, sled length, abstract recall (control; the logic already repeats):")
    for point in payload["obfuscation"]["curves"]["sled_same"]:
        ab = point.get("ngram-abs-n6", {})
        if not ab:
            continue
        lines.append(f"  L={point['x']}: recall {fmt(ab.get('recall'))} nonop {fmt(ab.get('recall_nonop'))}")
    # Interpret rename vs reorder from endpoints
    ren = payload["obfuscation"]["curves"]["rename"]
    reo = payload["obfuscation"]["curves"]["reorder"]
    sled = payload["obfuscation"]["curves"]["sled_unique"]

    def endpoint(points, tag, field, x):
        for point in points:
            if point.get("x") == x and isinstance(point.get(tag), dict):
                return point[tag].get(field)
        return None

    r_raw_0 = endpoint(ren, "ngram-raw-n6", "recall", 0.0)
    r_raw_1 = endpoint(ren, "ngram-raw-n6", "recall", 1.0)
    r_abs_1 = endpoint(ren, "ngram-abs-n6", "recall", 1.0)
    o_abs_1 = endpoint(reo, "ngram-abs-n6", "recall", 1.0)
    s0 = endpoint(sled, "ngram-abs-n6", "recall", 0)
    s0n = endpoint(sled, "ngram-abs-n6", "recall_nonop", 0)
    s256 = endpoint(sled, "ngram-abs-n6", "recall", 256)
    s256n = endpoint(sled, "ngram-abs-n6", "recall_nonop", 256)
    junk = payload["obfuscation"]["curves"]["junk"]
    j_abs_1 = endpoint(junk, "ngram-abs-n6", "recall", 1.0)
    if None not in (r_raw_0, r_raw_1, r_abs_1, o_abs_1):
        lines.append(
            f"Renaming every copy differently moves raw recall from {fmt(r_raw_0)} to {fmt(r_raw_1)} and leaves abstract recall at {fmt(r_abs_1)}. A full shuffle of every copy leaves abstract recall at {fmt(o_abs_1)}. Distinct per-instruction nops leave abstract recall at {fmt(j_abs_1)}."
        )
        if (r_abs_1 or 0) > (r_raw_1 or 0) + 0.2:
            lines.append("Abstraction absorbs a register rotation: raw recall falls and abstract recall does not.")
        if o_abs_1 is not None and o_abs_1 < 0.2:
            lines.append(f"A full shuffle drops abstract recall to {fmt(o_abs_1)}. Reordering breaks the n-gram for raw and abstract keys alike.")
        if j_abs_1 is not None and j_abs_1 > 0.8:
            lines.append(
                f"A regular nop after every instruction leaves abstract recall at {fmt(j_abs_1)}. The padded shape still repeats inside the gate, so this kind of junk becomes part of the signature instead of hiding the clone."
            )
    if None not in (s0, s256, s0n, s256n):
        lines.append(
            f"On distinct DualGate bodies, sled length 0 gives abstract recall {fmt(s0)} (non-nop {fmt(s0n)}); length 256 gives recall {fmt(s256)} (non-nop {fmt(s256n)}). Recall that rises with the sled while non-nop recall stays put is the miner matching nops."
        )
    lines.append("Curves: results/degradation.svg")
    lines.append("")

    lines.append("Hard negatives")
    lines.append("No ground-truth gates. Every repeated cluster is a false positive. FPR is instruction coverage.")
    lines.append("name            kind     abs  fpr    insn_rate  clusters  relocs")
    neg_ids = [s["id"] for s in samples if s["family"] == "negative"]
    for sid in neg_ids:
        sample = next(s for s in samples if s["id"] == sid)
        rel = ",".join(sample.get("relocs") or []) or "-"
        for kind, abstract in (("ngram", False), ("ngram", True), ("bb", True)):
            row = row_of(rows, sid, kind, abstract, 6, False)
            if row is None:
                continue
            lines.append(
                f"{sample['circuit']:15} {kind:8} {str(abstract):5} {fmt(row['fpr']):6} {fmt(row['insn_rate']):10} {row['clusters']:8}  {rel if kind=='ngram' and abstract else ''}"
            )
    # prior
    neg_abs = [row_of(rows, sid, "ngram", True, 6, False) for sid in neg_ids]
    neg_abs = [r for r in neg_abs if r]
    if neg_abs and focus:
        worst = max(neg_abs, key=lambda r: r["fpr"] or 0)
        lines.append(
            f"Highest abstract n-gram-6 coverage on a negative is {fmt(worst['fpr'])} ({worst['id']}). Flexo test -O2 false-positive rate on non-gate instructions is {fmt(focus['fpr'])}, with gate recall {fmt(focus['recall'])}. TAE abstract fpr is {fmt(tae_abs['fpr']) if tae_abs else 'n/a'}."
        )
        tmpl_raw = row_of(rows, "neg-templates", "ngram", False, 6, False)
        tmpl_abs = row_of(rows, "neg-templates", "ngram", True, 6, False)
        if tmpl_raw and tmpl_abs and (tmpl_abs["fpr"] or 0) > (tmpl_raw["fpr"] or 0) + 0.3:
            lines.append(
                f"Template instantiations show where the prior has to push back on abstraction: raw 6-gram coverage is {fmt(tmpl_raw['fpr'])} and abstract coverage is {fmt(tmpl_abs['fpr'])}."
            )
        if (worst["fpr"] or 0) > 0.15:
            lines.append("Repetition fires on ordinary repeated code (unrolled rounds, SIMD clones, template copies, or inlined library bodies) at a rate that is not a rare tail. A gate decision needs a weirdness prior on top of repetition: repetition proposes candidates, it does not define the class.")
        else:
            lines.append("On these negatives the repeated-cluster coverage stays low, so repetition is more specific here than the sled-heavy Flexo objects suggested. The prior is still required wherever a compiler clones a ordinary function.")
    for note in payload["negative_notes"]:
        if note.get("ok") is False:
            lines.append(f"Negative build failed: {note['what']}: {(note.get('error') or '').replace(chr(10),' ')[:180]}")
    lines.append("")

    lines.append("Scaling")
    lines.append("Two synthetic families, 32 tokens, 10% token noise. Exact clustering groups identical keys. MinHash uses 16 permutations and 4 bands. LSH recall is the fraction of noisy copies that share a band with their clean prototype; cross-family is the fraction that share a band with the other prototype.")
    lines.append("n      exact_s  lsh_s  exact_near  lsh_recall  lsh_cross  distinct_keys")
    for row in payload["scaling"]:
        lines.append(
            f"{row['n']:<6} {row['exact_seconds']:<8} {row['lsh_seconds']:<6} {fmt(row['exact_near_dup_rate']):11} {fmt(row['lsh_prototype_recall']):11} {fmt(row['lsh_cross_family_rate']):10} {row['exact_distinct_keys']}"
        )
    if payload["scaling"]:
        last = payload["scaling"][-1]
        first = payload["scaling"][0]
        lines.append(
            f"From {first['n']} to {last['n']} gates, exact time goes from {first['exact_seconds']}s to {last['exact_seconds']}s and LSH from {first['lsh_seconds']}s to {last['lsh_seconds']}s. Exact near-duplicate rate stays {fmt(last['exact_near_dup_rate'])} because 10% noise almost never reproduces a full key. LSH prototype recall is {fmt(last['lsh_prototype_recall'])} with cross-family rate {fmt(last['lsh_cross_family_rate'])}."
        )
        if last["lsh_seconds"] > last["exact_seconds"]:
            lines.append("At this size the approximate method is the slower one. It earns its cost only when near-duplicates must count as the same gate. Identical clones do not need it.")
    lines.append("")

    lines.append("ISA transfer")
    lines.append("Flexo and TAE gadgets are x86 (cache timing, indirect jmp through rbx, nop sleds) and were not cross-compiled. The ISA run uses the same miner on a portable repeated function, the unrolled-crypto negative, and the template negative, compiled freestanding for x86-64, AArch64, and riscv64. Raw bytes are 6-byte shingles. The IR is this miner's normalization (mnemonic plus register and immediate abstraction). There is no separate lifter in this tree.")
    for note in payload["isa_notes"]:
        if note.get("ok") is False:
            lines.append(f"ISA build failed: {note['what']}: {(note.get('error') or '').replace(chr(10),' ')[:160]}")
    lines.append("arch    circuit     bytes_fpr  ngram_raw_recall  ngram_abs_recall  bb_abs_recall  ngram_abs_fpr")
    for row in payload["isa"]["samples"]:
        def pull(tag, field):
            block = row.get(tag) or {}
            return block.get(field)

        lines.append(
            f"{row['arch']:7} {row['circuit']:11} {fmt(pull('bytes-raw','fpr') if row['gates']==0 else pull('bytes-raw','recall')):10} {fmt(pull('ngram-raw','recall')):17} {fmt(pull('ngram-abs','recall')):17} {fmt(pull('bb-abs','recall')):14} {fmt(pull('ngram-abs','fpr'))}"
        )
    lines.append("Cross-ISA Jaccard of repeated keys (count>=2):")
    for row in payload["isa"]["cross_isa_keys"]:
        if row["circuit"] != "repeated" and row["kind"] == "bytes":
            continue
        lines.append(
            f"  {row['circuit']:11} {row['kind']:6} abs={str(row['abstract']):5} {row['pair']:14} jaccard={fmt(row['jaccard'], 3)} shared={row['shared']} sizes={row['left']}/{row['right']}"
        )
    rep = [r for r in payload["isa"]["cross_isa_keys"] if r["circuit"] == "repeated" and r["pair"] == "x86/arm64"]
    raw_j = next((r["jaccard"] for r in rep if r["kind"] == "bytes"), None)
    abs_j = next((r["jaccard"] for r in rep if r["kind"] == "ngram" and r["abstract"]), None)
    mn_j = next((r["jaccard"] for r in rep if r["kind"] == "ngram" and not r["abstract"]), None)
    if raw_j is not None and abs_j is not None:
        lines.append(
            f"x86 vs AArch64 on the repeated function: raw-byte Jaccard {fmt(raw_j, 3)}, raw n-gram Jaccard {fmt(mn_j, 3)}, abstract n-gram Jaccard {fmt(abs_j, 3)}."
        )
        if (abs_j or 0) < 0.05 and (raw_j or 0) < 0.05:
            lines.append("Normalization does not carry an ISA-agnostic claim. Abstract keys still contain ISA mnemonics (`mov` versus `mov`/`ldr`/`add` spellings differ), so repeated clusters do not transfer. Within one ISA, repetition still finds the eight copies when the compiler emits them alike.")
        elif (abs_j or 0) > (raw_j or 0) + 0.05:
            lines.append("Abstraction shares more keys across ISAs than raw bytes do. The overlap is whatever mnemonics happen to be spelled the same; it is not a lifted IR.")
    lines.append("")

    lines.append("Mode comparison")
    lines.append("Single-binary mining keeps keys that occur at least twice in the target. Cross-build keeps every key that occurs at least once in both binaries (a gate that is unique inside one build can still be stable across builds). Stable-repeated is the intersection of the two within-binary repeated sets. Scores are on the second binary of each pair.")
    lines.append("pair                      kind   abs  single_rec  single_nonop  single_fpr  cross_rec  cross_nonop  cross_fpr  stable_rec  stable_fpr")
    for row in payload["mode"]:
        if row["kind"] == "bb" and row["abstract"] is False:
            continue
        lines.append(
            f"{row['pair'][:24]:24} {row['kind']:6} {str(row['abstract']):5} {fmt(row['single_recall']):11} {fmt(row['single_recall_nonop']):13} {fmt(row['single_fpr']):11} {fmt(row['cross_recall']):10} {fmt(row['cross_recall_nonop']):12} {fmt(row['cross_fpr']):10} {fmt(row['stable_recall']):11} {fmt(row['stable_fpr'])}"
        )
    # judgement on flexo opt pair, ngram abstract
    mode_focus = next(
        (r for r in payload["mode"] if r["pair"].startswith("flexo opt") and r["kind"] == "ngram" and r["abstract"]),
        None,
    )
    mode_tae = next(
        (r for r in payload["mode"] if r["pair"].startswith("tae opt") and r["kind"] == "ngram" and r["abstract"]),
        None,
    )
    if mode_focus:
        lines.append(
            f"Flexo test -O0 vs -O2, abstract 6-grams, scored on -O2: single recall {fmt(mode_focus['single_recall'])} non-nop {fmt(mode_focus['single_recall_nonop'])} fpr {fmt(mode_focus['single_fpr'])}; cross recall {fmt(mode_focus['cross_recall'])} non-nop {fmt(mode_focus['cross_recall_nonop'])} fpr {fmt(mode_focus['cross_fpr'])}; stable recall {fmt(mode_focus['stable_recall'])} fpr {fmt(mode_focus['stable_fpr'])}."
        )
        single_f = mode_focus["single_fpr"] or 0
        cross_f = mode_focus["cross_fpr"] or 0
        single_r = mode_focus["single_recall_nonop"] or 0
        cross_r = mode_focus["cross_recall_nonop"] or 0
        if cross_r + 0.05 >= single_r and cross_f < single_f - 0.05:
            lines.append("Cross-build diffing keeps the non-nop recall and cuts the false-positive rate. On this pair, diffing beats single-binary mining.")
        elif cross_r + 0.05 < single_r and cross_f < single_f:
            lines.append("Diffing lowers both false positives and recall. It is stricter, not uniformly better: gates that the optimizer rewrote in only one build disappear.")
        else:
            lines.append("On this pair, diffing does not dominate single-binary mining. The repeated sled is already shared inside one binary, so a second build adds little once nops are the feature.")
    if mode_tae:
        lines.append(
            f"TAE -O0 vs -O2, abstract 6-grams: single non-nop recall {fmt(mode_tae['single_recall_nonop'])} fpr {fmt(mode_tae['single_fpr'])}; cross non-nop {fmt(mode_tae['cross_recall_nonop'])} fpr {fmt(mode_tae['cross_fpr'])}."
        )
    mode_cc = next(
        (r for r in payload["mode"] if "clang vs" in r["pair"] and r["kind"] == "ngram" and r["abstract"]),
        None,
    )
    if mode_cc:
        lines.append(
            f"TAE clang-17 vs g++, abstract 6-grams, scored on g++: single recall {fmt(mode_cc['single_recall'])} fpr {fmt(mode_cc['single_fpr'])}; cross-build recall {fmt(mode_cc['cross_recall'])} fpr {fmt(mode_cc['cross_fpr'])}."
        )
        if (mode_cc["cross_recall"] or 0) < 0.2 and (mode_cc["cross_fpr"] or 0) > 0.5:
            lines.append("The keys shared by the two compilers cover the non-gate code (the decode table, once immediates are abstracted) and miss the jmpreg bodies. Diffing across compilers keeps the false pattern and drops the gate.")
    lines.append("")
    lines.append("Answer")
    worst_fpr = worst["fpr"] if neg_abs and focus else None
    lines.append(
        "Repetition alone does not separate weird gates from everything else. "
        + (
            f"On Flexo test -O2, abstract 6-grams recall {fmt(focus['recall'])} of the DualGates and also cover {fmt(focus['fpr'])} of the instructions outside them (purity {fmt(focus['purity'])}). "
            if focus
            else ""
        )
        + (
            f"On TAE the same feature recalls {fmt(tae_abs['recall'])} of the jmpreg clones, with purity {fmt(tae_abs['purity'])} after constant abstraction versus {fmt(tae_raw['purity'])} raw. "
            if tae_abs and tae_raw
            else ""
        )
        + (
            f"The highest abstract 6-gram coverage on a hard negative is {fmt(worst_fpr)}. "
            if worst_fpr is not None
            else ""
        )
        + "The match that fires is an n-gram of the shared piece: a nop sled, a jmp pad, or an abstracted instruction shape. Basic blocks are coarser than that piece on Flexo, and CFG edges add little on this straight-line code. Register abstraction recovers renamed copies and also welds the TAE decode table and the template instantiations into false clusters. A shuffle breaks the n-gram. A regular nop gap does not: it becomes part of the repeated key. A shared sled does the same. Exact clustering is the right tool for identical clones. MinHash is what still joins a 10% edit, and it costs more at 65536 items. A second build is a filter on keys the first binary already repeats, not a weirdness test."
    )
    path.write_text("\n".join(lines) + "\n")


def public_sample(sample: dict) -> dict:
    return {
        "id": sample["id"],
        "family": sample["family"],
        "arch": sample.get("arch"),
        "circuit": sample.get("circuit"),
        "param": sample.get("param"),
        "compiler": sample.get("compiler"),
        "opt": sample.get("opt"),
        "gate_count": sample["gate_count"],
        "aligned_gates": sample["aligned_gates"],
        "text_bytes": sample["text_bytes"],
        "text_insns": sample["text_insns"],
        "relocs": sample.get("relocs"),
    }


def public_row(row: dict) -> dict:
    out = dict(row)
    for key, val in list(out.items()):
        if isinstance(val, float):
            out[key] = round(val, 4)
    return out


def main() -> None:
    t0 = time.perf_counter()
    RES.mkdir(parents=True, exist_ok=True)
    samples, notes = build_corpus()
    neg_samples, neg_notes = compile_negatives()
    samples.extend(neg_samples)
    rows = ablation(samples)
    obf = obfuscation()
    scale_rows = scaling()
    isa_samples, isa_notes = compile_isa()
    isa = isa_report(isa_samples)
    mode = mode_report(samples)
    payload = {
        "seconds": round(time.perf_counter() - t0, 1),
        "builds": notes,
        "negative_notes": neg_notes,
        "isa_notes": isa_notes,
        "samples": [public_sample(s) for s in samples],
        "ablation": [public_row(r) for r in rows],
        "obfuscation": obf,
        "scaling": scale_rows,
        "isa": isa,
        "mode": mode,
    }
    (RES / "metrics.json").write_text(json.dumps(payload, indent=2) + "\n")
    write_svg(obf, RES / "degradation.svg")
    write_summary(payload, RES / "summary.txt")
    log(f"done in {payload['seconds']}s")
    log((RES / "summary.txt").read_text()[:4000])


if __name__ == "__main__":
    main()
