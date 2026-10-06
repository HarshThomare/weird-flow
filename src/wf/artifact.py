from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
