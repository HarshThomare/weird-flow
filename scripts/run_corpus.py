#!/usr/bin/env python3
"""Run the weird-flow pipeline over the compiled ELF corpus.

Writes results/run-diffing/<elf-id>/ and results/run-symmetry/<elf-id>/
with per-stage dumps. Live Qwen is used only for a small live set; the
rest uses MockLLM. Policy is recorded in results/RUN.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from wf.cli import elf_id  # noqa: E402
from wf.pipeline import load_config, run_pipeline  # noqa: E402

CLANG = Path("/tmp/llvm-17/bin/clang-17")
CLANGXX = Path("/tmp/llvm-17/bin/clang++-17")
GCC_DIR = "/usr/lib/gcc/x86_64-linux-gnu/11"
NEG_SRC = ROOT / "experiment" / "repeat miner" / "negatives"
NEG_OUT = ROOT / "results" / "negatives"
WEMU = Path("/u/hthomare/weird-machines/artifacts/WeMu")
MWM_GITM = Path("/u/hthomare/mWM-decompiler/third_party/gitm")

LIVE_NEEDLES = (
    "third_party/flexo/circuits/gates/test.elf",
    "tests/fixtures/gitm/main_and.elf",
    "Flexo-TLB/circuits/gates/test.elf",
)

SYMMETRY_PLOTS = [
    "flexo_test_periodogram",
    "flexo_test_two_family",
    "flexo_alu_two_family",
    "flexo_alu_periodogram",
    "gitm_and_combined",
    "tae_jmpreg_trap",
]


def discover_elfs() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    globs = [
        ROOT / "third_party" / "flexo",
        ROOT / "third_party" / "tlb",
        ROOT / "third_party" / "tae" / "elf",
        ROOT / "tests" / "fixtures" / "gitm",
    ]
    for base in globs:
        if base.is_dir():
            for p in sorted(base.rglob("*.elf")):
                if p.is_file():
                    found.append((elf_id(p, ROOT), p))
    if MWM_GITM.is_dir():
        for p in sorted(MWM_GITM.rglob("*.elf")):
            if p.is_file():
                found.append((elf_id(p, ROOT), p))
    if WEMU.is_dir():
        for p in sorted(WEMU.rglob("*.elf")):
            if p.is_file():
                found.append((elf_id(p, ROOT), p))
    seen = set()
    out = []
    for ident, path in found:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append((ident, path))
    return out


def compile_negatives() -> list[tuple[str, Path]]:
    NEG_OUT.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("neg.simd.o", NEG_SRC / "simd_kernel.c", CLANG, ["-O3", "-mavx2"]),
        ("neg.crypto.o", NEG_SRC / "unrolled_crypto.c", CLANG, ["-O3"]),
        ("neg.templates.o", NEG_SRC / "templates.cpp", CLANGXX, ["-O3", "-std=c++20"]),
        ("neg.inlined_libc.o", NEG_SRC / "inlined_libc.c", CLANG, ["-O3"]),
    ]
    out = []
    for ident, src, cc, flags in jobs:
        dest = NEG_OUT / Path(ident).name
        if not src.is_file():
            continue
        if not cc.is_file():
            print(f"skip compile {src.name}: missing {cc}", flush=True)
            continue
        cmd = [str(cc), f"--gcc-install-dir={GCC_DIR}", "-c", *flags, str(src), "-o", str(dest)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        (NEG_OUT / f"{dest.name}.compile.log").write_text(
            (proc.stdout or "") + (proc.stderr or "")
        )
        if proc.returncode != 0:
            print(f"negative compile failed {src}: {proc.stderr[-300:]}", flush=True)
            continue
        out.append((ident, dest))
    return out


def family_of(path: Path) -> str:
    s = str(path).lower()
    if "/results/negatives/" in s or "negatives" in s:
        return "neg"
    if "tae" in s:
        return "tae"
    if "gitm" in s:
        return "gitm"
    if "flexo-tlb" in s or "/tlb/" in s and "dcache" not in s:
        return "tlb"
    if "dcache" in s:
        return "dcache"
    if "flexo" in s:
        return "flexo"
    if "wemu" in s:
        return "wemu"
    return "other"


def is_live(path: Path) -> bool:
    s = str(path)
    return any(n in s for n in LIVE_NEEDLES)


def pick_gpu() -> tuple[str | None, dict]:
    info = {"gpus": [], "picked": None, "reason": ""}
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:
        info["reason"] = f"nvidia-smi failed: {exc}"
        return None, info
    rows = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        idx, used, total, util = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        free = total - used
        rows.append({"index": idx, "used": used, "total": total, "util": util, "free": free})
    info["gpus"] = rows
    need = 18000
    by_idx = {r["index"]: r for r in rows}
    if 2 in by_idx and by_idx[2]["free"] >= need:
        info["picked"] = 2
        info["reason"] = f"GPU 2 has {by_idx[2]['free']} MiB free"
        return "2", info
    candidates = [r for r in rows if r["free"] >= need]
    if candidates:
        best = max(candidates, key=lambda r: r["free"])
        info["picked"] = best["index"]
        info["reason"] = (
            f"GPU 2 short of {need} MiB; using GPU {best['index']} with {best['free']} MiB free"
        )
        return str(best["index"]), info
    info["reason"] = f"no GPU with >={need} MiB free; live LLM will use CPU if CUDA is false"
    return None, info


def eval_pair_stats(path: Path, pairs) -> dict:
    from tests.helpers import eval_gates, pair_recall

    kind = None
    fam = family_of(path)
    if fam in ("flexo", "tlb", "dcache"):
        kind = "flexo"
    elif fam == "tae":
        kind = "tae"
    if kind is None:
        return {"gates": 0, "hit": 0, "recall": None}
    gates = eval_gates(path, kind)
    rec, hit, n = pair_recall(pairs, gates)
    return {"gates": n, "hit": hit, "recall": rec}


def run_one(ident: str, path: Path, cfg: dict, outdir: Path, live: bool) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(json.dumps(cfg, default=str))
    cfg["dump_dir"] = str(outdir)
    if not live:
        models = cfg.setdefault("models", {})
        for key in ("judge", "decompile"):
            spec = models.setdefault(key, {})
            spec["provider"] = "mock"
    stdout_path = outdir / "stdout.txt"
    stderr_path = outdir / "stderr.txt"
    t0 = time.perf_counter()
    row = {
        "elf_id": ident,
        "elf": str(path.resolve()),
        "family": family_of(path),
        "live_llm": live,
        "ok": False,
        "n_pairs": 0,
        "error": None,
        "seconds": 0.0,
    }
    try:
        art = run_pipeline(path, cfg, ROOT)
        elapsed = time.perf_counter() - t0
        stats = eval_pair_stats(path, art.pairs)
        row.update(
            {
                "ok": True,
                "n_pairs": len(art.pairs),
                "n_yes": sum(1 for j in art.judgments if j.yes),
                "seconds": elapsed,
                "gates": stats["gates"],
                "hit": stats["hit"],
                "recall": stats["recall"],
                "native": art.verify.get("native"),
            }
        )
        stdout_path.write_text(f"pairs={len(art.pairs)} live={live}\n")
        stderr_path.write_text("")
        (outdir / "timing.json").write_text(
            json.dumps({"seconds": elapsed, "live_llm": live, "elf_id": ident}, indent=2) + "\n"
        )
        (outdir / "eval.json").write_text(json.dumps(stats, indent=2) + "\n")
        if art.c_source and not (outdir / "emit.c").exists() and not (outdir / "04-emit.c").exists():
            (outdir / "emit.c").write_text(art.c_source)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        row["seconds"] = elapsed
        row["error"] = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()
        stderr_path.write_text(tb)
        stdout_path.write_text("")
        (outdir / "error.json").write_text(json.dumps({"error": row["error"], "traceback": tb}, indent=2) + "\n")
        (outdir / "timing.json").write_text(json.dumps({"seconds": elapsed, "failed": True}, indent=2) + "\n")
    return row


def copy_symmetry_plots(dest: Path) -> None:
    src = ROOT / "experiment" / "symmetry" / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    meas = ROOT / "experiment" / "symmetry" / "measurements.json"
    if meas.is_file():
        shutil.copy2(meas, dest / "measurements.json")
    readme = ROOT / "experiment" / "symmetry" / "README.md"
    if readme.is_file():
        shutil.copy2(readme, dest / "README.md")
    for stem in SYMMETRY_PLOTS:
        for ext in (".png", ".svg"):
            p = src / f"{stem}{ext}"
            if p.is_file():
                shutil.copy2(p, dest / p.name)


def write_run_md(path: Path, payload: dict) -> None:
    lines = [
        "# Weird Flow corpus runs",
        "",
        f"- torch: `{payload.get('torch')}`",
        f"- CUDA: `{payload.get('cuda')}` available={payload.get('cuda_available')}",
        f"- GPU: `{payload.get('gpu')}` ({payload.get('gpu_reason')})",
        f"- live LLM policy: {payload.get('live_policy')}",
        f"- symmetry run: **{payload.get('run_b')}**",
        "",
        "## ELF counts",
        "",
    ]
    for fam, n in sorted(payload.get("counts", {}).items()):
        lines.append(f"- {fam}: {n}")
    lines += ["", "## Run A (diffing)", ""]
    lines.append("| elf-id | family | pairs | DualGate recall | live | s | ok |")
    lines.append("|---|---|---:|---:|---|---:|---|")
    for r in payload.get("run_a", []):
        rec = "" if r.get("recall") is None else f"{r['recall']:.2f} ({r.get('hit')}/{r.get('gates')})"
        lines.append(
            f"| `{r['elf_id']}` | {r['family']} | {r.get('n_pairs', 0)} | {rec} | {r.get('live_llm')} | {r.get('seconds', 0):.1f} | {r.get('ok')} |"
        )
    if payload.get("run_b") == "yes":
        lines += ["", "## Run B (symmetry)", ""]
        lines.append("| elf-id | family | pairs | DualGate recall | live | s | ok |")
        lines.append("|---|---|---:|---:|---|---:|---|")
        for r in payload.get("run_b_rows", []):
            rec = "" if r.get("recall") is None else f"{r['recall']:.2f} ({r.get('hit')}/{r.get('gates')})"
            lines.append(
                f"| `{r['elf_id']}` | {r['family']} | {r.get('n_pairs', 0)} | {rec} | {r.get('live_llm')} | {r.get('seconds', 0):.1f} | {r.get('ok')} |"
            )
    else:
        lines += ["", "## Run B", "", payload.get("run_b_note", "skipped"), ""]
    negs = [r for r in payload.get("run_a", []) if r.get("family") == "neg"]
    if negs:
        lines += ["", "## Negatives (diffing FPR-ish)", ""]
        for r in negs:
            lines.append(f"- `{r['elf_id']}` pairs={r.get('n_pairs')}")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()
    elves = discover_elfs()
    negs = compile_negatives()
    elves.extend(negs)
    print(f"corpus {len(elves)} ELFs ({len(negs)} negatives)", flush=True)

    gpu, gpu_info = pick_gpu()
    if gpu is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = gpu
    os.environ.setdefault("WF_LIVE_LLM", "1")

    torch_s = cuda_s = None
    cuda_ok = False
    try:
        import torch

        torch_s = torch.__version__
        cuda_s = torch.version.cuda
        cuda_ok = bool(torch.cuda.is_available())
        print(f"torch {torch_s} cuda {cuda_s} available={cuda_ok} GPU={gpu}", flush=True)
    except Exception as exc:
        print(f"torch import failed: {exc}", flush=True)

    live_policy = (
        "Live local Qwen3-8B on Flexo test.elf + GITM main_and.elf + Flexo-TLB test.elf; "
        "MockLLM for every other ELF. WF_LIVE_MAX_PAIRS unset for Flexo test, cap=2 for the other live ELFs."
    )

    def run_mode(name: str, cfg_path: Path, dest: Path) -> list[dict]:
        dest.mkdir(parents=True, exist_ok=True)
        cfg = load_config(cfg_path)
        rows = []
        live_first = [x for x in elves if is_live(x[1])]
        rest = [x for x in elves if not is_live(x[1])]
        ordered = live_first + rest
        for i, (ident, path) in enumerate(ordered, 1):
            live = is_live(path)
            if live and "flexo/circuits/gates/test.elf" not in str(path):
                os.environ["WF_LIVE_MAX_PAIRS"] = "2"
            elif live:
                os.environ.pop("WF_LIVE_MAX_PAIRS", None)
            print(f"[{name} {i}/{len(ordered)}] {ident} live={live}", flush=True)
            row = run_one(ident, path, cfg, dest / ident, live=live)
            rows.append(row)
            if not row["ok"]:
                print(f"  FAIL {row['error']}", flush=True)
            else:
                print(f"  pairs={row['n_pairs']} recall={row.get('recall')} {row['seconds']:.1f}s", flush=True)
        (dest / "summary.json").write_text(json.dumps(rows, indent=2, default=str) + "\n")
        return rows

    payload = {
        "torch": torch_s,
        "cuda": cuda_s,
        "cuda_available": cuda_ok,
        "gpu": gpu,
        "gpu_reason": gpu_info.get("reason"),
        "gpu_info": gpu_info,
        "live_policy": live_policy,
        "counts": {},
        "run_a": [],
        "run_b": "no",
        "run_b_rows": [],
    }
    counts: dict[str, int] = {}
    for ident, path in elves:
        counts[family_of(path)] = counts.get(family_of(path), 0) + 1
    payload["counts"] = counts

    if mode in ("diffing", "both", "a"):
        payload["run_a"] = run_mode("diffing", ROOT / "config" / "flexo.yml", ROOT / "results" / "run-diffing")
    if mode in ("symmetry", "both", "b"):
        copy_symmetry_plots(ROOT / "results" / "run-symmetry" / "plots")
        payload["run_b"] = "yes"
        payload["run_b_rows"] = run_mode(
            "symmetry", ROOT / "config" / "symmetry.yml", ROOT / "results" / "run-symmetry"
        )
        payload["run_b_note"] = (
            "Go: Flexo test/ALU/sbox and GITM show a DualGate-scale period, FFT line, "
            "and ~515 B two-family lag (see experiment/symmetry/measurements.json)."
        )

    (ROOT / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "corpus.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    write_run_md(ROOT / "results" / "RUN.md", payload)
    print("wrote", ROOT / "results" / "RUN.md", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
