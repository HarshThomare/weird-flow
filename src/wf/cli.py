from __future__ import annotations

import argparse
import json
from pathlib import Path

from wf.pipeline import load_config, run_pipeline


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser(prog="wf")
    p.add_argument("--config", default=str(root / "config" / "flexo.yml"))
    p.add_argument("--elf", required=True)
    args = p.parse_args(argv)
    cfg = load_config(Path(args.config))
    art = run_pipeline(Path(args.elf), cfg, root)
    outdir = Path(cfg.get("results_dir") or "results")
    if not outdir.is_absolute():
        outdir = root / outdir
    outdir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.elf).stem
    payload = {
        "elf": str(art.elf),
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
    }
    (outdir / f"{stem}.json").write_text(json.dumps(payload, indent=2) + "\n")
    if art.c_source:
        (outdir / f"{stem}.c").write_text(art.c_source)
    print(f"pairs={len(art.pairs)} -> {outdir / (stem + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
