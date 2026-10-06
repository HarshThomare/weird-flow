from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass
class PairRegion:
    start: int
    end: int
    family_a: str
    family_b: str
    n_matches: int
    gap: int
    disasm: str = ""


@dataclass
class Judgment:
    yes: bool
    role: str
    forcing: dict[str, Any]
    window: str
    substrate: str
    confidence: float
    span: list[int]
    raw: str = ""


@dataclass
class Artifact:
    elf: Path
    arch: str = "x86"
    text: bytes = b""
    text_base: int = 0
    insns: list = field(default_factory=list)
    pairs: list[PairRegion] = field(default_factory=list)
    judgments: list[Judgment] = field(default_factory=list)
    composed: str = ""
    c_source: str = ""
    blif: str = ""
    verify: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    dump_dir: Path | None = None
    mine_dump: dict[str, Any] = field(default_factory=dict)

    def write_json(self, name: str, payload: Any) -> Path | None:
        if not self.dump_dir:
            return None
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        path = self.dump_dir / name
        path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n")
        return path

    def write_text(self, name: str, text: str) -> Path | None:
        if not self.dump_dir:
            return None
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        path = self.dump_dir / name
        path.write_text(text if text.endswith("\n") else text + "\n")
        return path


def _json_default(obj: Any):
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"
    try:
        import numpy as np

        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if k != "text"}
    return str(obj)
