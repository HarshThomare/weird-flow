from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from wf.judge import parse_judge_json
from wf.pipeline import load_config, run_pipeline
from wf.verify_native import parse_flexo_output, parse_gitm_output, parse_native
from tests.helpers import FLEXO_TEST, ROOT


def test_parse_judge_json_strips_think_and_fences():
    raw = '<think>nope</think>\n```json\n{"yes": true, "role": "pair", "forcing": {"state": "occupancy", "value": 0, "how": "x"}, "window": "transient", "substrate": "dcache", "confidence": 0.9, "span": [1, 2]}\n```\n'
    data = parse_judge_json(raw)
    assert data["yes"] is True
    assert data["forcing"]["value"] == 0


def test_flexo_banner_parser():
    text = (
        "=== AND ===\n"
        "Accuracy: 95.11000%, Error detected: 4.81000%, Undetected error: 0.08000%\n"
    )
    rows = parse_flexo_output(text)
    assert len(rows) == 1
    assert rows[0]["name"] == "AND"
    assert rows[0]["admitted"] is True


def test_gitm_banner_parser_and_tae_skip():
    text = (
        "=== AND gate (Exception) ===\n"
        "Correct rate: (avg, std) = (97.5000%, 0.0100)\n"
        "Time usage: 1.000s over 100 iterations.\n"
    )
    rows = parse_gitm_output(text)
    assert rows and rows[0]["name"].startswith("AND")
    skipped = parse_native("ignored", "tae")
    assert skipped["skipped"] is True


def test_pipeline_flexo_mock(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WF_LLM", "mock")
    monkeypatch.delenv("WF_NATIVE", raising=False)
    cfg = load_config(ROOT / "config" / "default.yml")
    cfg["models"]["judge"]["provider"] = "mock"
    cfg["models"]["decompile"]["provider"] = "mock"
    art = run_pipeline(FLEXO_TEST, cfg, ROOT)
    assert len(art.pairs) >= 1
    assert art.judgments and art.judgments[0].yes is True
    assert "void decompile" in art.c_source
    assert "wr_in" in art.c_source and "wr_out" in art.c_source
    native = art.verify.get("native") or {}
    assert native.get("skipped") is True


@pytest.mark.skipif(os.environ.get("WF_LIVE_LLM") != "1", reason="set WF_LIVE_LLM=1 to load Qwen3-8B")
def test_live_qwen_flexo_judge_decompile():
    """One Flexo pair: LLM1 JSON + LLM2 C on local Qwen3-8B (CPU if no CUDA)."""
    from wf.llm import make_llm
    from wf.mine import mine_path
    from tests.helpers import DEFAULT_MINER

    os.environ.setdefault("WF_LIVE_MAX_PAIRS", "1")
    _view, pairs = mine_path(FLEXO_TEST, DEFAULT_MINER)
    assert pairs, "miner returned no pair regions"
    pair = pairs[0]
    spec = {"provider": "local_hf", "model": "models/Qwen3-8B", "json_only": True}
    llm = make_llm(spec)
    judge_tmpl = (ROOT / "prompts" / "judge_jev.txt").read_text()
    judge_prompt = judge_tmpl.format(
        start=pair.start,
        end=pair.end,
        family_a=pair.family_a,
        family_b=pair.family_b,
        disasm=pair.disasm or "(empty)",
    )
    raw_json = llm.complete(judge_prompt)
    print("Qwen judge raw:\n", raw_json[:2000])
    data = parse_judge_json(raw_json)
    assert "yes" in data

    spec["json_only"] = False
    llm.json_only = False
    de_tmpl = (ROOT / "prompts" / "decompile_c.txt").read_text()
    de_prompt = de_tmpl.format(
        start=pair.start,
        end=pair.end,
        disasm=pair.disasm or "(empty)",
        judge_json=json.dumps(data),
    )
    raw_c = llm.complete(de_prompt)
    print("Qwen decompile raw:\n", raw_c[:2000])
    assert raw_c.strip()
