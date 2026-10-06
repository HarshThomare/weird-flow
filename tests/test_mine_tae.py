from __future__ import annotations

from wf.mine import mine_path
from tests.helpers import DEFAULT_MINER, TAE_GATES, eval_gates, pair_recall


def test_tae_gates_elf_exists():
    assert TAE_GATES.is_file(), f"missing {TAE_GATES}"


def test_tae_localization_only_not_one_clone_class_as_two_idioms():
    # abstract_imms false so the decode-table mov-imm does not weld.
    # 1024 identical jmpreg clones are one family; gap pairing must not
    # treat that clone class as the two idioms.
    view, pairs = mine_path(TAE_GATES, DEFAULT_MINER)
    gates = eval_gates(TAE_GATES, "tae")
    rec, hit, n = pair_recall(pairs, gates)
    print(f"tae gates.elf pairs={len(pairs)} jmpreg={n} recall={rec:.3f} ({hit}/{n})")
    assert n >= 1000
    # Localization-only: native TAE is skipped elsewhere. A true pair of
    # two distinct co-located families is allowed; a flood of clone-only
    # pairs is not.
    assert len(pairs) < 64, f"clone class leaked into {len(pairs)} pair regions"
