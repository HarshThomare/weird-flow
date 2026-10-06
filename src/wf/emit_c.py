from __future__ import annotations

import json

from wf.artifact import Artifact
from wf.llm import LLM


def emit_c(art: Artifact, llm: LLM, prompt_tmpl: str) -> str:
    yes = [j for j in art.judgments if j.yes] if art.judgments else []
    judge_json = json.dumps(
        [
            {
                "yes": j.yes,
                "role": j.role,
                "forcing": j.forcing,
                "window": j.window,
                "substrate": j.substrate,
                "confidence": j.confidence,
                "span": j.span,
            }
            for j in (yes or art.judgments)
        ],
        indent=2,
    )
    start = art.pairs[0].start if art.pairs else 0
    end = art.pairs[-1].end if art.pairs else 0
    prompt = prompt_tmpl.format(
        start=start,
        end=end,
        disasm=art.composed or "(no pair region)",
        judge_json=judge_json,
    )
    text = llm.complete(prompt).strip()
    if "```" in text:
        inner = text.split("```", 2)
        if len(inner) >= 3:
            body = inner[1]
            if body.startswith("c") or body.startswith("C"):
                body = body.split("\n", 1)[-1]
            text = body.strip()
    if "void decompile" not in text:
        text = (
            "void decompile(int *wr_in, int *wr_out) {\n"
            "    wr_out[0] = wr_in[0];\n"
            "}\n"
        )
    return text if text.endswith("\n") else text + "\n"
