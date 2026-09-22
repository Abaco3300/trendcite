"""The canonical intelligence entities: candidate signals, signals and their evaluations.

A :class:`Signal` is what TrendCite actually knows about: a topic that public sources
are talking about, with a stable identity that survives across runs. Everything the
product shows is a *projection* of a signal -- a Content Opportunity Brief is one
such projection, not the root entity.

The chain is::

    Source -> Observation -> ObservationSnapshot
           -> Cluster -> CandidateSignal -> Signal
           -> EvidenceItem / EvidenceSetVersion
           -> SignalEvaluation (versioned) -> SignalSnapshot
           -> SignalBrief -> ContentOpportunityBrief

Three identities are kept apart on purpose:

``signal_id``
    Stable across runs, derived only from the canonical topic key. The same topic
    evaluated tomorrow is the same signal, so history lines up.
``EvidenceSetVersion.version_id``
    Changes whenever the backing evidence changes. It is what makes an evaluation
    reproducible: same evidence set + same evaluation version => same numbers.
``SignalSnapshot.snapshot_id``
    One append-only evaluation event, unique to (signal, evidence set, time).

Nothing here computes a score; :mod:`trendcite.signal_scoring` does that, and it is
the only module that may.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .observation import Observation
from .versions import (
    EVIDENCE_SET_ALGORITHM,
    SIGNAL_EVALUATION_VERSION,
    SIGNAL_ID_VERSION,
)

_ID_CHARS = 16

# --------------------------------------------------------------------- component status

#: The component was computed from evidence that actually exists.
MEASURED = "measured"
#: The inputs the component needs are absent. It contributes nothing to the score and
#: its weight is removed from the denominator. It is never silently replaced with 0.
INSUFFICIENT_DATA = "insufficient_data"

# ------------------------------------------------------------------------ signal state

STATE_EMERGING = "emerging"
STATE_SUSTAINED = "sustained"
STATE_DORMANT = "dormant"
STATE_REACTIVATED = "reactivated"
STATE_INSUFFICIENT_DATA = "insufficient_data"
STATES = (
    STATE_EMERGING,
    STATE_SUSTAINED,
    STATE_DORMANT,
    STATE_REACTIVATED,
    STATE_INSUFFICIENT_DATA,
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


# ----------------------------------------------------------------------------- identity


def signal_key(cluster_key: str) -> str:
    """Canonical, run-independent key for a topic (lowercase, whitespace-collapsed)."""
    return " ".join(cluster_key.lower().split())


def signal_id_for(key: str) -> str:
    """Stable signal id. Depends on the topic key only, never on a particular run."""
    digest = hashlib.sha256(f"{SIGNAL_ID_VERSION}|{signal_key(key)}".encode()).hexdigest()
    return digest[:_ID_CHARS]


# ------------------------------------------------------------------------ evidence set


@dataclass(frozen=True)
class EvidenceSetVersion:
    """A content-addressed version of the exact evidence an evaluation ran over."""

    version_id: str
    algorithm: str
    observation_ids: tuple[str, ...]
    story_keys: tuple[str, ...]
    created_at: datetime

    @classmethod
    def of(cls, observations: Sequence[Observation], *, created_at: datetime) -> EvidenceSetVersion:
        ids = tuple(o.observation_id for o in observations)
        keys = tuple(sorted({o.story_key for o in observations}))
        # Sorted, so the same set in a different display order is the same version.
        material = f"{EVIDENCE_SET_ALGORITHM}|" + "|".join(sorted(ids))
        return cls(
            version_id=hashlib.sha256(material.encode()).hexdigest()[:_ID_CHARS],
            algorithm=EVIDENCE_SET_ALGORITHM,
            observation_ids=ids,
            story_keys=keys,
            created_at=created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "algorithm": self.algorithm,
            "observation_ids": list(self.observation_ids),
            "story_keys": list(self.story_keys),
            "observation_count": len(self.observation_ids),
            "story_count": len(self.story_keys),
            "created_at": _iso(self.created_at),
        }


# ------------------------------------------------------------------ candidate and signal


@dataclass(frozen=True)
class CandidateSignal:
    """A cluster that has been proposed as a signal but not yet evaluated.

    Clustering decides *what might be one thing*; evaluation decides *whether it is
    worth anything*. Keeping the candidate distinct means a topic can be rejected or
    scored INSUFFICIENT_DATA without the cluster layer knowing anything about scores.
    """

    key: str
    label: str
    observations: tuple[Observation, ...]
    related_terms: tuple[str, ...] = ()
    cohesive: bool = True

    @property
    def signal_id(self) -> str:
        return signal_id_for(self.key)

    @property
    def canonical_key(self) -> str:
        return signal_key(self.key)


@dataclass(frozen=True)
class Signal:
    """The canonical intelligence entity: a topic with a stable cross-run identity."""

    signal_id: str
    key: str
    label: str
    first_seen_at: datetime
    last_seen_at: datetime
    related_terms: tuple[str, ...] = ()

    @classmethod
    def promote(
        cls, candidate: CandidateSignal, *, now: datetime, first_seen_at: datetime | None = None
    ) -> Signal:
        return cls(
            signal_id=candidate.signal_id,
            key=candidate.canonical_key,
            label=candidate.label,
            first_seen_at=first_seen_at or now,
            last_seen_at=now,
            related_terms=candidate.related_terms,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "key": self.key,
            "label": self.label,
            "first_seen_at": _iso(self.first_seen_at),
            "last_seen_at": _iso(self.last_seen_at),
            "related_terms": list(self.related_terms),
        }


# -------------------------------------------------------------------------- evaluation


@dataclass(frozen=True)
class ComponentScore:
    """One scoring component, with its status stated rather than implied."""

    name: str
    weight: float
    value: float | None  # None exactly when status is INSUFFICIENT_DATA
    status: str
    basis: str  # what was actually measured, in words

    @property
    def contribution(self) -> float:
        """Weighted contribution in points, before renormalisation. 0 when unmeasured."""
        return 0.0 if self.value is None else self.value * self.weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "value": self.value,
            "status": self.status,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class Counterevidence:
    """A reason to trust the signal less, attached to the evidence that caused it."""

    code: str
    detail: str
    observation_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "observation_ids": list(self.observation_ids),
        }


@dataclass(frozen=True)
class SignalEvaluation:
    """A versioned, reproducible verdict about one signal at one point in time.

    ``score`` answers "how strong is this signal" and nothing else. Confidence (how
    much the evidence supports any verdict at all) and relevance (how much it matches
    the user's niche) are deliberately separate fields: folding them into one number
    is what makes a trend score unexplainable.
    """

    evaluation_version: str
    evaluated_at: datetime
    score: float  # 0-100 over the measured components
    components: tuple[ComponentScore, ...]
    measured_weight: float  # total weight of components that had data
    confidence: str  # "high" | "medium" | "low"
    relevance: float  # 0-1, reported beside the score, never inside it
    state: str
    counterevidence: tuple[Counterevidence, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def insufficient(self) -> list[str]:
        return [c.name for c in self.components if c.status == INSUFFICIENT_DATA]

    def component(self, name: str) -> ComponentScore:
        for c in self.components:
            if c.name == name:
                return c
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_version": self.evaluation_version,
            "evaluated_at": _iso(self.evaluated_at),
            "score": self.score,
            "confidence": self.confidence,
            "relevance": self.relevance,
            "state": self.state,
            "measured_weight": round(self.measured_weight, 3),
            "insufficient_data": self.insufficient,
            "components": [c.to_dict() for c in self.components],
            "counterevidence": [c.to_dict() for c in self.counterevidence],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------- snapshot


@dataclass(frozen=True)
class SignalSnapshot:
    """One append-only evaluation event, safe to store and compare across runs."""

    snapshot_id: str
    signal_id: str
    captured_at: datetime
    evaluation_version: str
    evidence_set_version: str
    score: float
    confidence: str
    state: str
    observation_count: int
    story_count: int
    source_count: int
    component_values: dict[str, float | None] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        signal: Signal,
        evaluation: SignalEvaluation,
        evidence_set: EvidenceSetVersion,
        *,
        source_count: int,
    ) -> SignalSnapshot:
        material = (
            f"{signal.signal_id}|{evidence_set.version_id}|"
            f"{evaluation.evaluation_version}|{_iso(evaluation.evaluated_at)}"
        )
        return cls(
            snapshot_id=hashlib.sha256(material.encode()).hexdigest()[:_ID_CHARS],
            signal_id=signal.signal_id,
            captured_at=evaluation.evaluated_at,
            evaluation_version=evaluation.evaluation_version,
            evidence_set_version=evidence_set.version_id,
            score=evaluation.score,
            confidence=evaluation.confidence,
            state=evaluation.state,
            observation_count=len(evidence_set.observation_ids),
            story_count=len(evidence_set.story_keys),
            source_count=source_count,
            component_values={c.name: c.value for c in evaluation.components},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "signal_id": self.signal_id,
            "captured_at": _iso(self.captured_at),
            "evaluation_version": self.evaluation_version,
            "evidence_set_version": self.evidence_set_version,
            "score": self.score,
            "confidence": self.confidence,
            "state": self.state,
            "observation_count": self.observation_count,
            "story_count": self.story_count,
            "source_count": self.source_count,
            "component_values": dict(self.component_values),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignalSnapshot:
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            signal_id=str(data["signal_id"]),
            captured_at=_parse_iso(str(data["captured_at"])),
            evaluation_version=str(data.get("evaluation_version", SIGNAL_EVALUATION_VERSION)),
            evidence_set_version=str(data.get("evidence_set_version", "")),
            score=float(data.get("score", 0.0)),
            confidence=str(data.get("confidence", "low")),
            state=str(data.get("state", STATE_EMERGING)),
            observation_count=int(data.get("observation_count", 0)),
            story_count=int(data.get("story_count", 0)),
            source_count=int(data.get("source_count", 0)),
            component_values=dict(data.get("component_values", {})),
        )


# ------------------------------------------------------------------------- signal brief


@dataclass(frozen=True)
class SignalBrief:
    """Everything known about one signal in one run: the internal intelligence record.

    A Content Opportunity Brief is a projection of this. Other projections (an alert,
    a digest, a research note) can be added later without touching the signal layer.
    """

    signal: Signal
    evaluation: SignalEvaluation
    evidence_set: EvidenceSetVersion
    observations: tuple[Observation, ...]
    snapshot: SignalSnapshot

    @property
    def signal_id(self) -> str:
        return self.signal.signal_id

    def observation_snapshots(self, *, captured_at: datetime | None = None) -> list[Any]:
        """Metric readings for this brief's observations, for the history store."""
        from .observation import ObservationSnapshot

        when = captured_at or self.evaluation.evaluated_at
        return [ObservationSnapshot.of(o, captured_at=when) for o in self.observations]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "evidence_set": self.evidence_set.to_dict(),
            "snapshot": self.snapshot.to_dict(),
            "observations": [o.to_dict() for o in self.observations],
        }


def sort_snapshots(snapshots: Iterable[SignalSnapshot]) -> list[SignalSnapshot]:
    """Oldest first, deterministically, so history comparisons are reproducible."""
    return sorted(snapshots, key=lambda s: (s.captured_at, s.snapshot_id))
