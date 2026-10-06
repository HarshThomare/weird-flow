from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from wf.mine import load_text, mine_path
from tests.helpers import CLANG, DEFAULT_MINER, FLEXO_AND, FLEXO_TEST, NEG_DIR, eval_gates, pair_recall


def test_flexo_test_elf_exists():
    assert FLEXO_TEST.is_file(), f"missing {FLEXO_TEST}"


def test_miner_has_no_opcode_catalog():
    src = Path(__file__).resolve().parents[1] / "src" / "wf" / "mine.py"
    text = src.read_text()
    for banned in ("clflush", "rdtsc", "rdtscp", "ud2", "jmpreg", "DualGate", "is_trigger", "is_decode"):
        assert banned not in text


def test_load_text_skips_symtab():
    src = inspect.getsource(load_text)
    assert "symtab" not in src
    assert "DualGate" not in src


def test_flexo_test_elf_pair_recall():
    view, pairs = mine_path(FLEXO_TEST, DEFAULT_MINER)
    assert view.arch == "x86"
    gates = eval_gates(FLEXO_TEST, "flexo")
    assert len(gates) == 8
    rec, hit, n = pair_recall(pairs, gates)
    # Measured on this tree: 7/8 DualGates (1-input body does not share the
    # enter n-gram). Do not fake 1.0.
    assert len(pairs) >= 1, f"expected pair regions, got {len(pairs)}"
    assert rec >= 0.75, f"DualGate pair recall {rec:.3f} ({hit}/{n}) pairs={len(pairs)}"
    print(f"flexo test.elf pairs={len(pairs)} recall={rec:.3f} ({hit}/{n})")


def test_flexo_and_elf_runs_without_symbols():
    # Single DualGate: enter/exit do not repeat, so pairing may be empty.
    _, pairs = mine_path(FLEXO_AND, DEFAULT_MINER)
    gates = eval_gates(FLEXO_AND, "flexo")
    rec, hit, n = pair_recall(pairs, gates)
    print(f"flexo and.elf pairs={len(pairs)} recall={rec:.3f} ({hit}/{n})")
    assert n == 1


def test_flexo_negative_simd_few_or_zero_pairs(tmp_path: Path):
    src = NEG_DIR / "simd_kernel.c"
    dest = tmp_path / "simd.o"
    if not CLANG.is_file():
        pytest.skip("clang-17 missing")
    subprocess.run(
        [str(CLANG), "-c", "-O3", "-mavx2", str(src), "-o", str(dest)],
        check=True,
        capture_output=True,
    )
    _, pairs = mine_path(dest, DEFAULT_MINER)
    assert len(pairs) <= 1, f"simd hard-negative produced {len(pairs)} pairs"
    print(f"flexo-negative simd pairs={len(pairs)}")
