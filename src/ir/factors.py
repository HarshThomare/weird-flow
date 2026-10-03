"""Factorized weird-machine model: M = (T, S, E, C).

Ontology §1.2: a weird machine factorizes into Trigger × Substrate × Encoding ×
Schedule. Factors are inferred independently and composed — evidence for T does
not depend on S. Each factor has a menu of known values plus an open-world slot
(``Unknown*``). A new machine is a new value in one slot, not a new class.

This module is the belief substrate: per-factor beliefs with supporting
evidence and competing hypotheses (ontology §1.1, §1.6). It is dependency-free
(stdlib only) so the belief layer can be tested and reused without the IR.

The LLM discipline (§README, src/llm/): nothing here is decided by a model.
Beliefs are set by harvest/static evidence or by validated experiments only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


class Factor(str, Enum):
    """The four factors of M = (T, S, E, C)."""

    TRIGGER = "T"
    SUBSTRATE = "S"
    ENCODING = "E"
    SCHEDULE = "C"


# Value menus per ontology §1.2. The trailing Unknown* entry is the open-world
# slot: an unseen machine is a new value in one slot, not a new top-level class.
TRIGGER_VALUES: Tuple[str, ...] = (
    "ret-mispredict",
    "indjmp-mispredict",
    "fault-suppressed",
    "TSX-abort",
    "UnknownTrigger",
)

SUBSTRATE_VALUES: Tuple[str, ...] = (
    "BTB",
    "PHT",
    "RSB",
    "L1D",
    "L2",
    "LLC",
    "DTLB",
    "ITLB",
    "uop-cache",
    "port-contention",
    "UnknownSubstrate",
)

ENCODING_VALUES: Tuple[str, ...] = (
    "direct-value",
    "single-rail-presence",
    "dual-rail",
    "redundant-vote",
    "UnknownEncoding",
)

SCHEDULE_VALUES: Tuple[str, ...] = (
    "single-window",
    "persistent-wr",
    "rearmed-windows",
    "UnknownSchedule",
)

VALUE_MENUS: Dict[Factor, Tuple[str, ...]] = {
    Factor.TRIGGER: TRIGGER_VALUES,
    Factor.SUBSTRATE: SUBSTRATE_VALUES,
    Factor.ENCODING: ENCODING_VALUES,
    Factor.SCHEDULE: SCHEDULE_VALUES,
}


def is_open_world(factor: Factor, value: str) -> bool:
    """True when the value is the factor's Unknown* slot."""
    return value == VALUE_MENUS[factor][-1]


def menu(factor: Factor) -> Tuple[str, ...]:
    """Known values for a factor, including its Unknown* slot."""
    return VALUE_MENUS[factor]


@dataclass
class FactorBelief:
    """One factor's belief: (confidence, supporting evidence, competitors).

    Ontology §1.1: every hypothesis carries ``(confidence ∈ [0,1],
    supporting-evidence set, competing hypotheses)``.
    """

    factor: Factor
    value: str
    confidence: float = 0.0
    evidence_ids: List[str] = field(default_factory=list)
    competitors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.factor, Factor):
            self.factor = Factor(self.factor)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence!r} outside [0,1]")

    def corroborate(self, evidence_id: str, weight: float) -> float:
        """Fold in one independent evidence item (ontology §1.6.1).

        Independent evidence types combine noisy-OR:
        ``c' = 1 - (1 - c) * (1 - w)``. This is the "multiply confidence"
        reading that sends belief → 1 as independent evidence accumulates
        (naive multiplication of confidences would wrongly send it to 0).

        The evidence id is recorded; re-submitting the same id is a no-op so
        correlated re-observation cannot double-count (independence guard).
        ``weight`` is the evidence item's own strength in [0,1].
        """
        if not 0.0 <= weight <= 1.0:
            raise ValueError(f"weight {weight!r} outside [0,1]")
        if evidence_id in self.evidence_ids:
            return self.confidence
        self.evidence_ids.append(evidence_id)
        self.confidence = 1.0 - (1.0 - self.confidence) * (1.0 - weight)
        # Clamp against float drift; __post_init__ already bounds inputs.
        self.confidence = min(1.0, max(0.0, self.confidence))
        return self.confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "factor": self.factor.value,
            "value": self.value,
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence_ids),
            "competitors": list(self.competitors),
        }


@dataclass
class MachineHypothesis:
    """A factorized machine hypothesis: one belief per factor of M = (T,S,E,C).

    Ontology §1.2: ``P(M | binary, observations) ∝ P(T|ev)·P(S|ev)·P(E|ev)·P(C|ev)``.
    The dict form keeps that factorization explicit — beliefs update per factor,
    never as a monolithic machine label (no family-forcing).
    """

    factors: Dict[Factor, FactorBelief] = field(default_factory=dict)

    def set(
        self,
        factor: Factor,
        value: str,
        confidence: float = 0.0,
        evidence_ids: Optional[Sequence[str]] = None,
        competitors: Optional[Sequence[str]] = None,
    ) -> FactorBelief:
        """Attach (or replace) the belief for one factor. Additive only."""
        belief = FactorBelief(
            factor=factor,
            value=value,
            confidence=confidence,
            evidence_ids=list(evidence_ids or ()),
            competitors=list(competitors or ()),
        )
        self.factors[Factor(factor)] = belief
        return belief

    def get(self, factor: Factor) -> Optional[FactorBelief]:
        """Belief for a factor, or None if the factor is not yet hypothesized."""
        return self.factors.get(Factor(factor))

    def corroborate(self, factor: Factor, evidence_id: str, weight: float) -> float:
        """Independent evidence multiplies confidence (ontology §1.6.1).

        Creates an Unknown*-valued belief at 0.0 if the factor has none yet,
        so corroboration never needs the value decided up front.
        """
        factor = Factor(factor)
        belief = self.factors.get(factor)
        if belief is None:
            belief = self.set(factor, VALUE_MENUS[factor][-1], confidence=0.0)
        return belief.corroborate(evidence_id, weight)

    def competing(self, factor: Factor) -> List[str]:
        """Values competing with the current best for this factor."""
        belief = self.factors.get(Factor(factor))
        return list(belief.competitors) if belief is not None else []

    def unresolved_factors(self) -> List[Factor]:
        """Factors with no belief, or stuck in their Unknown* slot."""
        out = []
        for f in Factor:
            b = self.factors.get(f)
            if b is None or is_open_world(f, b.value):
                out.append(f)
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {f.value: b.to_dict() for f, b in self.factors.items()}


def hypothesis_from_evidence_tags(
    trigger: Optional[str] = None,
    substrate: Optional[str] = None,
    encoding: Optional[str] = None,
    schedule: Optional[str] = None,
    evidence_id: str = "",
    confidence: float = 0.0,
) -> MachineHypothesis:
    """Build a hypothesis from per-factor evidence tags, one belief per factor.

    Unset factors stay absent (not Unknown*), so ``unresolved_factors()``
    distinguishes "no evidence yet" from "evidence points at the open slot".
    """
    hyp = MachineHypothesis()
    tags = {
        Factor.TRIGGER: trigger,
        Factor.SUBSTRATE: substrate,
        Factor.ENCODING: encoding,
        Factor.SCHEDULE: schedule,
    }
    for factor, value in tags.items():
        if value is None:
            continue
        competitors = [v for v in VALUE_MENUS[factor] if v != value]
        hyp.set(
            factor,
            value,
            confidence=confidence,
            evidence_ids=[evidence_id] if evidence_id else [],
            competitors=competitors,
        )
    return hyp


__all__ = [
    "ENCODING_VALUES",
    "Factor",
    "FactorBelief",
    "MachineHypothesis",
    "SCHEDULE_VALUES",
    "SUBSTRATE_VALUES",
    "TRIGGER_VALUES",
    "VALUE_MENUS",
    "hypothesis_from_evidence_tags",
    "is_open_world",
    "menu",
]
