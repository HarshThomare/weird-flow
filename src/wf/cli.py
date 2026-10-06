from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from wf.pipeline import load_config, run_pipeline


def elf_id(path: Path, root: Path) -> str:
    p = str(path.resolve())
    markers = [
        ("/third_party/flexo/", "flexo."),
        ("/third_party/tlb/", "tlb."),
        ("/third_party/tae/", "tae."),
        ("/tests/fixtures/gitm/", "gitm.fixtures."),
        ("/artifacts/WeMu/", "wemu."),
        ("/results/negatives/", "neg."),
        ("/experiment/repeat miner/negatives/", "neg."),
    ]
    for marker, prefix in markers:
        if marker in p:
            rest = p.split(marker, 1)[1]
            return prefix + rest.replace("/", ".")
    try:
        rel = path.resolve().relative_to(root.resolve())
        return str(rel).replace("/", ".")
    except ValueError:
        return path.name


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser(prog="wf")
    p.add_argument("--config", default=str(root / "config" / "flexo.yml"))
    p.add_argument("--elf", required=True)
    p.add_argument("--out", default=None, help="per-ELF dump directory")
    p.add_argument("--elf-id", default=None)
    args = p.parse_args(argv)
    cfg = load_config(Path(args.config))
    elf = Path(args.elf)
    ident = args.elf_id or elf_id(elf, root)
    outdir = Path(args.out) if args.out else None
    if outdir is None:
        base = Path(cfg.get("results_dir") or "results")
        if not base.is_absolute():
            base = root / base
        outdir = base / ident
    outdir.mkdir(parents=True, exist_ok=True)
    cfg["dump_dir"] = str(outdir)
    t0 = time.perf_counter()
    art = run_pipeline(elf, cfg, root)
    elapsed = time.perf_counter() - t0
    timing = {"seconds": elapsed, "elf": str(elf.resolve()), "elf_id": ident}
    (outdir / "timing.json").write_text(json.dumps(timing, indent=2) + "\n")
    payload = {
        "elf": str(art.elf),
        "elf_id": ident,
        "arch": art.arch,
        "n_pairs": len(art.pairs),
        "pairs": [
            {
                "start": pr.start,
                "end": pr.end,
                "family_a": pr.family_a,
                "family_b": pr.family_b,
                "n_matches": pr.n_matches,
                "gap": pr.gap,
            }
            for pr in art.pairs
        ],
        "judgments": [
            {
                "yes": j.yes,
                "role": j.role,
                "forcing": j.forcing,
                "window": j.window,
                "substrate": j.substrate,
                "confidence": j.confidence,
                "span": j.span,
            }
            for j in art.judgments
        ],
        "verify": art.verify,
        "timing": timing,
    }
    (outdir / "pipeline.json").write_text(json.dumps(payload, indent=2) + "\n")
    if art.c_source:
        (outdir / "emit.c").write_text(art.c_source if art.c_source.endswith("\n") else art.c_source + "\n")
    print(f"pairs={len(art.pairs)} -> {outdir / 'pipeline.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
