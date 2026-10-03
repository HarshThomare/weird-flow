"""Active experiment selection: the §1.6 discriminator table.

Ontology §1.6: decompilation is active learning, not static analysis. When
hypotheses compete, run the experiment maximizing expected information gain.
Each substrate value has a cheapest distinguishing perturbation; this module
stores them per S value (ontology §1.6.2) and ranks candidate experiments.

Every experiment carries its destructive-read budget (``read_cost`` reads,
``rearm_ops`` re-arm operations). Ontology §2.6: formalizing the
destructive-read calculus is an OPEN problem, not a solved component — this
module records the budget per experiment and can filter by it, but does NOT
claim to solve optimal budget allocation.

The LLM discipline holds: experiments are selected from this deterministic
table by a deterministic ranking. A model may *suggest* an experiment to try;
it may not pick the discriminator or interpret the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .factors import Factor, MachineHypothesis, SUBSTRATE_VALUES


@dataclass
class Experiment:
    """One executable discriminator.

    ``targets`` are the factors this experiment discriminates between.
    ``read_cost`` is the number of destructive reads it performs; ``rearm_ops``
    the re-arm operations needed afterwards (ontology §1.6.4). Both are
    non-negative integers; unknown costs are 0 with a note in ``description``.
    """

    name: str
    targets: List[Factor] = field(default_factory=list)
    read_cost: int = 0
    rearm_ops: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        self.targets = [t if isinstance(t, Factor) else Factor(t) for t in self.targets]
        if self.read_cost < 0 or self.rearm_ops < 0:
            raise ValueError("read_cost and rearm_ops must be non-negative")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "targets": [t.value for t in self.targets],
            "read_cost": self.read_cost,
            "rearm_ops": self.rearm_ops,
            "description": self.description,
        }


# Cheapest distinguishing perturbation per substrate value (ontology §1.6.2).
# The canonical discriminator: "cache or TLB?" → flush the LLC; if the probe
# changes, S=cache. "BTB or PHT?" → collide the BTB set with aliasing
# branches; if the WR value changes, S=BTB.
def _discriminator_table() -> Dict[str, Experiment]:
    return {
        "L1D": Experiment(
            name="llc_flush",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=2,
            description=(
                "Flush the LLC, re-probe. If the WR observation changes, the "
                "substrate is cache (L1D/L2/LLC); if unchanged, it is not "
                "(e.g. TLB). Canonical cache-vs-TLB discriminator."
            ),
        ),
        "L2": Experiment(
            name="llc_flush",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=2,
            description="As L1D: LLC flush discriminates cache from non-cache substrates.",
        ),
        "LLC": Experiment(
            name="llc_flush",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=2,
            description="As L1D: LLC flush discriminates cache from non-cache substrates.",
        ),
        "BTB": Experiment(
            name="btb_set_collision",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=1,
            description=(
                "Collide the BTB set with aliasing branches. If the WR value "
                "changes, S=BTB (vs PHT: history poisoning changes nothing "
                "for a BTB substrate and vice versa)."
            ),
        ),
        "PHT": Experiment(
            name="history_poison",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=1,
            description=(
                "Poison predictor history with a crafted branch ladder. If the "
                "WR value changes, S=PHT (vs BTB)."
            ),
        ),
        "RSB": Experiment(
            name="rsb_fill",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=1,
            description=(
                "Fill/overflow the RSB with nested calls before the window. "
                "If the trigger window changes, S=RSB."
            ),
        ),
        "DTLB": Experiment(
            name="page_walk_perturb",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=2,
            description=(
                "Perturb the page walk (invlpg/invpcid or remap to a huge "
                "page). If the WR observation changes, the substrate is TLB "
                "(vs cache: LLC flush already ruled cache in/out)."
            ),
        ),
        "ITLB": Experiment(
            name="page_walk_perturb",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=2,
            description="As DTLB, applied to the instruction-side mapping.",
        ),
        "uop-cache": Experiment(
            name="uop_cache_pressure",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=1,
            description=(
                "Evict uop-cache entries with a large straight-line sled. If "
                "the window behavior changes, S=uop-cache."
            ),
        ),
        "port-contention": Experiment(
            name="port_pressure",
            targets=[Factor.SUBSTRATE],
            read_cost=1,
            rearm_ops=1,
            description=(
                "Saturate execution ports with dependent ALU chains. If the "
                "race outcome shifts, S=port-contention."
            ),
        ),
        "UnknownSubstrate": Experiment(
            name="differential_oracle",
            targets=[Factor.SUBSTRATE],
            read_cost=2,
            rearm_ops=2,
            description=(
                "Substrate-agnostic differential: run perturbation A then B vs "
                "B alone. A change localizes the substrate without assuming "
                "which structure holds the WR."
            ),
        ),
    }


DISCRIMINATORS: Dict[str, Experiment] = _discriminator_table()

# Sanity: every substrate menu value has a discriminator.
assert set(DISCRIMINATORS) == set(SUBSTRATE_VALUES), (
    "discriminator table must cover every substrate value, including UnknownSubstrate"
)


def eig_heuristic(hypothesis: MachineHypothesis, experiment: Experiment) -> float:
    """Rank experiments by expected information gain — heuristic, NOT true EIG.

    TODO: replace with the true mutual information I(factor value; outcome)
    over the factorized posterior P(T|ev)·P(S|ev)·P(E|ev)·P(C|ev). That needs
    an outcome likelihood model per experiment, which does not exist yet.

    Current heuristic: an experiment is worth more when (a) it targets factors
    whose belief is weak or contested, and (b) it is cheap in destructive
    reads + re-arm. Score = uncertainty_mass / (1 + read_cost + rearm_ops),
    where uncertainty_mass sums (1 - confidence) over targeted factors plus a
    bonus per listed competitor.
    """
    mass = 0.0
    for factor in experiment.targets:
        belief = hypothesis.get(factor)
        if belief is None:
            mass += 1.0  # no belief at all: maximal uncertainty
            continue
        mass += 1.0 - belief.confidence
        mass += 0.25 * len(belief.competitors)
    cost = 1.0 + experiment.read_cost + experiment.rearm_ops
    return mass / cost


def propose(
    hypothesis: MachineHypothesis,
    budget: Optional[int] = None,
    candidates: Optional[Sequence[Experiment]] = None,
) -> List[Experiment]:
    """Rank candidate experiments for a hypothesis by EIG heuristic.

    ``budget`` caps total ``read_cost`` (destructive-read budgeting,
    ontology §1.6.4): candidates are taken in rank order until the budget is
    exhausted. ``None`` means unbounded. The budget filter is a greedy
    stand-in — optimal budget allocation under destructive reads is the §2.6
    open problem, explicitly not solved here.
    """
    if candidates is None:
        seen: Dict[str, Experiment] = {}
        for exp in DISCRIMINATORS.values():
            seen.setdefault(exp.name, exp)
        candidates = list(seen.values())
    ranked = sorted(candidates, key=lambda e: eig_heuristic(hypothesis, e), reverse=True)
    if budget is None:
        return ranked
    out: List[Experiment] = []
    spent = 0
    for exp in ranked:
        if spent + exp.read_cost > budget:
            continue
        out.append(exp)
        spent += exp.read_cost
    return out


__all__ = [
    "DISCRIMINATORS",
    "Experiment",
    "eig_heuristic",
    "propose",
]
