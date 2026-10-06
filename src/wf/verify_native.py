"""Native stdout parsers. TAE CPU verification is skipped on purpose."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Copied (not imported) from mWM-decompiler oracle/native.py
GATE_RE = re.compile(
    r"=== (?P<name>.+?) ===\s+"
    r"Accuracy:\s+(?P<acc>[\d.]+)%,\s+"
    r"Error detected:\s+(?P<det>[\d.]+)%,\s+"
    r"Undetected error:\s+(?P<und>[\d.]+)%",
    re.MULTILINE,
)

GITM_HEADER_RE = re.compile(r"=== (?P<name>.+?) ===")
GITM_ACC_RE = re.compile(
    r"(?:Accuracy|Correct rate).*?(?:=|:)\s*\(?(?P<acc>[\d.]+)\s*%",
    re.IGNORECASE,
)
GITM_MEDIAN_RE = re.compile(
    r"Accuracy:\s*median\s*=\s*(?P<acc>[\d.]+)\s*%",
    re.IGNORECASE,
)


def parse_flexo_output(text: str) -> list[dict]:
    rows = []
    for m in GATE_RE.finditer(text):
        acc = float(m.group("acc"))
        rows.append(
            {
                "name": m.group("name").strip(),
                "accuracy_pct": acc,
                "error_detected_pct": float(m.group("det")),
                "undetected_error_pct": float(m.group("und")),
                "admitted": acc >= 90.0,
            }
        )
    return rows


def parse_gitm_output(text: str) -> list[dict]:
    """GITM prints '=== NAME gate ... ===' then Correct rate / Accuracy lines.

    If the banner is not stable, return [] and the adapter abstains.
    """
    rows = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        hm = GITM_HEADER_RE.search(lines[i])
        if not hm:
            i += 1
            continue
        name = hm.group("name").strip()
        acc = None
        for j in range(i + 1, min(i + 6, len(lines))):
            mm = GITM_MEDIAN_RE.search(lines[j]) or GITM_ACC_RE.search(lines[j])
            if mm:
                acc = float(mm.group("acc"))
                break
        if acc is not None:
            rows.append({"name": name, "accuracy_pct": acc, "admitted": acc >= 90.0})
        i += 1
    return rows


def parse_tlb_output(text: str) -> list[dict]:
    # Flexo-TLB ELFs use the Flexo accuracy banner when they run.
    return parse_flexo_output(text)


def parse_native(text: str, family: str) -> dict:
    family = family.lower()
    if family == "tae":
        return {"skipped": True, "reason": "TAE native CPU verification skipped", "circuits": []}
    if family == "gitm":
        rows = parse_gitm_output(text)
        if not rows:
            return {
                "skipped": True,
                "reason": "GITM adapter abstained: no stable accuracy banner",
                "circuits": [],
            }
        return {"skipped": False, "circuits": rows, "family": "gitm"}
    if family == "tlb":
        rows = parse_tlb_output(text)
        return {"skipped": False, "circuits": rows, "family": "tlb"}
    rows = parse_flexo_output(text)
    return {"skipped": False, "circuits": rows, "family": "flexo"}


def guess_family(path: Path, allowed: list[str]) -> str | None:
    p = str(path).lower()
    # Always identify TAE so native exec is skipped even if it is not in allowed.
    if "tae" in p:
        return "tae"
    for fam in allowed:
        if fam == "tlb" and "tlb" in p:
            return "tlb"
        if fam == "gitm" and "gitm" in p:
            return "gitm"
        if fam == "flexo" and "flexo" in p and "tlb" not in p:
            return "flexo"
        if fam == "tae" and "tae" in p:
            return "tae"
    return None


def run_native(path: Path, family: str, timeout_s: int = 60) -> dict:
    if family == "tae":
        return {"skipped": True, "reason": "TAE native CPU verification skipped", "circuits": []}
    cmd = [os.path.abspath(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"skipped": True, "reason": str(exc), "circuits": []}
    text = (proc.stdout or "") + (proc.stderr or "")
    parsed = parse_native(text, family)
    parsed["returncode"] = proc.returncode
    return parsed
