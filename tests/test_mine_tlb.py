from __future__ import annotations

from wf.mine import mine_path
from tests.helpers import DEFAULT_MINER, TLB_TEST, eval_gates, pair_recall


def test_tlb_test_elf_exists():
    assert TLB_TEST.is_file(), f"missing {TLB_TEST}"


def test_tlb_test_elf_pair_recall():
    view, pairs = mine_path(TLB_TEST, DEFAULT_MINER)
    assert view.arch == "x86"
    gates = eval_gates(TLB_TEST, "flexo")
    assert len(gates) >= 8
    rec, hit, n = pair_recall(pairs, gates)
    assert len(pairs) >= 1, f"expected pair regions, got {len(pairs)}"
    assert rec >= 0.75, f"TLB DualGate pair recall {rec:.3f} ({hit}/{n}) pairs={len(pairs)}"
    print(f"tlb test.elf pairs={len(pairs)} recall={rec:.3f} ({hit}/{n}) gates={n}")
