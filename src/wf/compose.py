from __future__ import annotations

from wf.artifact import Artifact, PairRegion


def compose_pairs(art: Artifact) -> str:
    """Keep judged-yes pair windows, merge overlaps, list them for emit."""
    chosen: list[PairRegion] = []
    if art.judgments:
        for pair, j in zip(art.pairs, art.judgments):
            if j.yes:
                chosen.append(pair)
    else:
        chosen = list(art.pairs)
    spans = sorted((p.start, p.end, p) for p in chosen)
    merged: list[tuple[int, int, list[PairRegion]]] = []
    for a, b, p in spans:
        if merged and a <= merged[-1][1] + 32:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b), merged[-1][2] + [p])
        else:
            merged.append((a, b, [p]))
    lines = []
    for a, b, ps in merged:
        lines.append(f"/* pair {a:#x}-{b:#x} families={len(ps)} */")
        lines.append(ps[0].disasm)
        lines.append("")
    return "\n".join(lines).rstrip() + ("\n" if lines else "")
