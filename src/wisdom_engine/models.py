"""Wisdom Engine — data models for epistemic filtering."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class HypothesisType(Enum):
    MECHANISM = "mechanism"    # Physical/structural cause
    NARRATIVE = "narrative"    # Social/psychological story
    CONSTRAINT = "constraint"  # Boundary condition or falsification test


class EliminationReason(Enum):
    QUARANTINED = "quarantined"  # Violates known constraints
    DEGENERATING = "degenerating"  # Lakatosian cut — ad hoc defenses
    EXPLAINED_AWAY = "explained_away"  # Bayesian collider — stronger mechanism exists
    LOW_CONFIDENCE = "low_confidence"  # Insufficient evidence


@dataclass
class Hypothesis:
    """A single competing explanation at three recursion depths."""
    id: str
    text: str
    h_type: HypothesisType = HypothesisType.MECHANISM
    d1_symptom: str = ""       # Surface claim / observation
    d2_mechanism: str = ""     # Generative mechanism (how it works)
    d3_invariant: str = ""     # Root law / invariant (why it must be true)
    evidence: list[str] = field(default_factory=list)
    eliminated: bool = False
    elimination_reason: str = ""
    elimination_detail: str = ""


@dataclass
class EliminationRecord:
    """Audit log entry for a eliminated hypothesis."""
    hypothesis_id: str
    hypothesis_text: str
    reason: str
    detail: str


@dataclass
class FilterResult:
    """Output of the Via Negativa filter."""
    surface_symptom: str
    all_hypotheses: list[Hypothesis]
    surviving_hypotheses: list[Hypothesis]
    elimination_log: list[EliminationRecord]
    strongest_mechanism: Hypothesis | None = None
