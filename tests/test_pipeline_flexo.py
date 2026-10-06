from __future__ import annotations

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
def test_live_qwen_optional():
    from wf.llm import make_llm

    llm = make_llm({"provider": "local_hf", "model": "models/Qwen3-8B", "json_only": True})
    raw = llm.complete('Reply JSON only: {"yes": false, "role": "pair", "forcing": {"state": "x", "value": 0, "how": "n"}, "window": "none", "substrate": "unknown", "confidence": 0.1, "span": [0, 1]}')
    data = parse_judge_json(raw)
    assert "yes" in data
