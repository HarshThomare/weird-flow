from __future__ import annotations

from pathlib import Path

from wf.mine import mine_path
from tests.helpers import DEFAULT_MINER, GITM_AND

WEMU_GITM = Path("/u/hthomare/weird-machines/artifacts/WeMu/src/gates/gitm/main_and.elf")


def test_gitm_elf_present():
    assert GITM_AND.is_file() or WEMU_GITM.is_file()


def test_gitm_and_emits_pair_regions():
    path = GITM_AND if GITM_AND.is_file() else WEMU_GITM
    view, pairs = mine_path(path, DEFAULT_MINER)
    assert view.arch == "x86"
    # GITM gates are inlined; no DualGate-style symbols. Localization = pairs.
    assert len(pairs) >= 1, f"GITM main_and.elf pairs={len(pairs)}"
    print(f"gitm main_and.elf pairs={len(pairs)} n_matches={[p.n_matches for p in pairs[:5]]}")
