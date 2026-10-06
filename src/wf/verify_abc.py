from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def verify_blif(blif: str) -> dict:
    abc = shutil.which("abc")
    if not abc:
        return {"ok": False, "skipped": True, "reason": "abc not on PATH"}
    tmp = Path("/tmp/wf-verify.blif")
    tmp.write_text(blif)
    proc = subprocess.run([abc, "-c", f"read {tmp}; print_stats"], capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "skipped": False,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-500:],
    }
