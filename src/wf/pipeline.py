from __future__ import annotations

from pathlib import Path

import yaml

from wf.artifact import Artifact
from wf.compose import compose_pairs
from wf.emit_blif import emit_blif
from wf.emit_c import emit_c
from wf.judge import judge_pairs
from wf.llm import make_llm
from wf.mine import load_text, mine_path
from wf.verify_abc import verify_blif
from wf.verify_native import guess_family, run_native


def load_config(path: Path) -> dict:
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    default = path.parent / "default.yml"
    if default.exists() and path.resolve() != default.resolve():
        base = yaml.safe_load(default.read_text()) or {}
        return _merge(base, data)
    return data


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_prompt(root: Path, rel: str) -> str:
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p.read_text()


def load_stage(art: Artifact, cfg: dict, root: Path) -> Artifact:
    view = load_text(art.elf)
    art.arch = view.arch
    art.text = view.blob
    art.text_base = view.base
    art.insns = view.insns
    return art


def mine_stage(art: Artifact, cfg: dict, root: Path) -> Artifact:
    _view, pairs = mine_path(art.elf, cfg.get("miner") or {})
    art.pairs = pairs
    if not art.insns:
        art.arch = _view.arch
        art.text = _view.blob
        art.text_base = _view.base
        art.insns = _view.insns
    return art


def judge_stage(art: Artifact, cfg: dict, root: Path) -> Artifact:
    spec = (cfg.get("models") or {}).get("judge") or {}
    llm = make_llm(spec)
    tmpl = _read_prompt(root, (cfg.get("prompts") or {}).get("judge", "prompts/judge_jev.txt"))
    art.judgments = judge_pairs(art, llm, tmpl)
    return art


def compose_stage(art: Artifact, cfg: dict, root: Path) -> Artifact:
    art.composed = compose_pairs(art)
    return art


def emit_c_stage(art: Artifact, cfg: dict, root: Path) -> Artifact:
    if not (cfg.get("emit") or {}).get("c", True):
        return art
    spec = (cfg.get("models") or {}).get("decompile") or {}
    llm = make_llm(spec)
    tmpl = _read_prompt(root, (cfg.get("prompts") or {}).get("decompile", "prompts/decompile_c.txt"))
    art.c_source = emit_c(art, llm, tmpl)
    return art


def emit_blif_stage(art: Artifact, cfg: dict, root: Path) -> Artifact:
    if not (cfg.get("emit") or {}).get("blif", False):
        return art
    art.blif = emit_blif(art)
    return art


def verify_native_stage(art: Artifact, cfg: dict, root: Path) -> Artifact:
    v = (cfg.get("verify") or {}).get("native") or {}
    if not v.get("enabled"):
        art.verify["native"] = {"skipped": True, "reason": "disabled"}
        return art
    families = list(v.get("families") or ["flexo", "gitm", "tlb"])
    fam = guess_family(art.elf, families)
    if fam is None:
        art.verify["native"] = {"skipped": True, "reason": "no matching family"}
        return art
    if fam == "tae":
        art.verify["native"] = {"skipped": True, "reason": "TAE native CPU verification skipped"}
        return art
    art.verify["native"] = run_native(art.elf, fam)
    return art


def verify_abc_stage(art: Artifact, cfg: dict, root: Path) -> Artifact:
    v = (cfg.get("verify") or {}).get("abc") or {}
    if not v.get("enabled") or not art.blif:
        art.verify["abc"] = {"skipped": True, "reason": "disabled or no blif"}
        return art
    art.verify["abc"] = verify_blif(art.blif)
    return art


STAGES = {
    "load": load_stage,
    "mine": mine_stage,
    "judge": judge_stage,
    "compose": compose_stage,
    "emit_c": emit_c_stage,
    "emit_blif": emit_blif_stage,
    "verify_native": verify_native_stage,
    "verify_abc": verify_abc_stage,
}


def run_pipeline(elf: Path, cfg: dict, root: Path | None = None) -> Artifact:
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    art = Artifact(elf=Path(elf), config=cfg)
    for name in cfg.get("pipeline") or ["load", "mine"]:
        fn = STAGES[name]
        art = fn(art, cfg, root)
    emit = cfg.get("emit") or {}
    if emit.get("blif") and "emit_blif" not in (cfg.get("pipeline") or []):
        art = emit_blif_stage(art, cfg, root)
    native = (cfg.get("verify") or {}).get("native") or {}
    if native.get("enabled") and "verify_native" not in (cfg.get("pipeline") or []):
        # ponytail: parse banners only; do not inject inputs. Skip live run in tests via env.
        import os

        if os.environ.get("WF_NATIVE") == "1":
            art = verify_native_stage(art, cfg, root)
        else:
            art.verify["native"] = {
                "skipped": True,
                "reason": "set WF_NATIVE=1 to exec the ELF; parsers are unit-tested",
            }
    abc = (cfg.get("verify") or {}).get("abc") or {}
    if abc.get("enabled") and "verify_abc" not in (cfg.get("pipeline") or []):
        art = verify_abc_stage(art, cfg, root)
    return art
