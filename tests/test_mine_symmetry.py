from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wf.mine import mine_path
from tests.helpers import CLANG, DEFAULT_MINER, FLEXO_TEST, NEG_DIR, TAE_GATES, eval_gates, pair_recall

SYMMETRY = dict(DEFAULT_MINER)
SYMMETRY["strategy"] = "symmetry"


def test_flexo_test_symmetry_pair_recall():
    view, pairs = mine_path(FLEXO_TEST, SYMMETRY)
    assert view.arch == "x86"
    gates = eval_gates(FLEXO_TEST, "flexo")
    rec, hit, n = pair_recall(pairs, gates)
    assert len(pairs) >= 1, f"symmetry expected pair regions, got {len(pairs)}"
    assert rec >= 0.75, f"symmetry DualGate recall {rec:.3f} ({hit}/{n}) pairs={len(pairs)}"
    print(f"symmetry flexo test.elf pairs={len(pairs)} recall={rec:.3f} ({hit}/{n})")


def test_tae_symmetry_does_not_pair_a_clone_class():
    _, pairs = mine_path(TAE_GATES, SYMMETRY)
    gates = eval_gates(TAE_GATES, "tae")
    rec, hit, n = pair_recall(pairs, gates)
    print(f"symmetry tae gates.elf pairs={len(pairs)} jmpreg={n} recall={rec:.3f} ({hit}/{n})")
    assert n >= 1000
    assert len(pairs) < 64, f"clone class leaked into {len(pairs)} pair regions"


def test_symmetry_simd_few_or_zero_pairs(tmp_path: Path):
    src = NEG_DIR / "simd_kernel.c"
    dest = tmp_path / "simd.o"
    if not CLANG.is_file():
        pytest.skip("clang-17 missing")
    subprocess.run(
        [str(CLANG), "-c", "-O3", "-mavx2", str(src), "-o", str(dest)],
        check=True,
        capture_output=True,
    )
    _, pairs = mine_path(dest, SYMMETRY)
    assert len(pairs) <= 1, f"simd hard-negative produced {len(pairs)} pairs"
    print(f"symmetry-negative simd pairs={len(pairs)}")
