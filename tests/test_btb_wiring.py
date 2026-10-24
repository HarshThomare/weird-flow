"""The BTB wiring kill test is part of the suite: it must keep passing."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_btb_cross_function_wiring_kill():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "experiments" / "btb-wiring" / "run.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    text = (ROOT / "experiments" / "btb-wiring" / "RESULTS.md").read_text()
    assert "**Verdict: PASS**" in text
