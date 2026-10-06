from __future__ import annotations

import json
import re

from wf.artifact import Artifact, Judgment, PairRegion
from wf.llm import LLM

_THINK = re.compile(r"<think>.*?</think>", re.S)


def parse_judge_json(text: str) -> dict:
    raw = _THINK.sub("", text).strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
        if m:
            raw = m.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("judge did not return JSON")
    return json.loads(raw[start : end + 1])


def _judgment(data: dict, raw: str, pair: PairRegion) -> Judgment:
    forcing = data.get("forcing") or {}
    if not isinstance(forcing, dict):
        forcing = {"state": "", "value": forcing, "how": ""}
    span = data.get("span") or [pair.start, pair.end]
    if not isinstance(span, list) or len(span) != 2:
        span = [pair.start, pair.end]
    return Judgment(
        yes=bool(data.get("yes")),
        role=str(data.get("role", "pair")),
        forcing=forcing,
        window=str(data.get("window", "")),
        substrate=str(data.get("substrate", "unknown")),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        span=[int(span[0]), int(span[1])],
        raw=raw,
    )


def judge_pairs(art: Artifact, llm: LLM, prompt_tmpl: str) -> list[Judgment]:
    out = []
    for pair in art.pairs:
        prompt = prompt_tmpl.format(
            start=pair.start,
            end=pair.end,
            family_a=pair.family_a,
            family_b=pair.family_b,
            disasm=pair.disasm or "(empty)",
        )
        raw = llm.complete(prompt)
        try:
            data = parse_judge_json(raw)
        except (ValueError, json.JSONDecodeError):
            data = {
                "yes": False,
                "role": "pair",
                "forcing": {"state": "", "value": None, "how": "unparseable"},
                "window": "",
                "substrate": "unknown",
                "confidence": 0.0,
                "span": [pair.start, pair.end],
            }
        out.append(_judgment(data, raw, pair))
    return out
