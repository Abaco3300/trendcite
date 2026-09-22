"""The Cloud side of a core Signal: stored globally, referenced per tenant.

Governance rule this module exists to enforce: **public-source signals are globally
canonical; only relevance and matching are tenant-scoped.** So the split is:

:class:`StoredSignal`
    The signal itself. No ``workspace_id``. Keyed by the core ``signal_id``, which is
    reused verbatim -- Cloud never re-derives, re-scores, or forks signal identity.
:class:`StoredSignalEvaluation`
    One append-only evaluation event, keyed by the core ``snapshot_id``. Also global,
    and content-addressed, so two tenants evaluating the same public evidence at the
    same instant share one row instead of racing to write two.
:class:`RunSignal`
    The tenant-scoped edge: "workspace W's run R saw signal S, and *for W* its
    relevance was X". This is the only place a tenant opinion about a public signal
    is allowed to live.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ...signal import Signal, SignalSnapshot
from ...versions import SIGNAL_ID_VERSION
from .. import ids
from ._base import iso, require_aware


@dataclass(frozen=True)
class StoredSignal:
    """A globally canonical signal, as Cloud persists it."""

    signal_id: str
    signal_key: str
    label: str
    related_terms: tuple[str, ...]
    first_seen_at: datetime
    last_seen_at: datetime
    signal_id_version: str

    @classmethod
    def of(cls, signal: Signal) -> StoredSignal:
        """Lift a core signal without changing a single identifying field."""
        return cls(
            signal_id=signal.signal_id,
            signal_key=signal.key,
            label=signal.label,
            related_terms=tuple(signal.related_terms),
            first_seen_at=require_aware(signal.first_seen_at, "first_seen_at"),
            last_seen_at=require_aware(signal.last_seen_at, "last_seen_at"),
            signal_id_version=SIGNAL_ID_VERSION,
        )

    def merged_with(self, other: StoredSignal) -> StoredSignal:
        """Widen the observed window when the same signal is seen again.

        Only the seen-at window and the human-facing label move. Identity never does.
        """
        return StoredSignal(
            signal_id=self.signal_id,
            signal_key=self.signal_key,
            label=other.label or self.label,
            related_terms=other.related_terms or self.related_terms,
            first_seen_at=min(self.first_seen_at, other.first_seen_at),
            last_seen_at=max(self.last_seen_at, other.last_seen_at),
            signal_id_version=self.signal_id_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_key": self.signal_key,
            "label": self.label,
            "related_terms": list(self.related_terms),
            "first_seen_at": iso(self.first_seen_at),
            "last_seen_at": iso(self.last_seen_at),
            "signal_id_version": self.signal_id_version,
        }


@dataclass(frozen=True)
class StoredSignalEvaluation:
    """One append-only evaluation event, mirroring a core :class:`SignalSnapshot`."""

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
    component_values: Mapping[str, float | None]

    @classmethod
    def of(cls, snapshot: SignalSnapshot) -> StoredSignalEvaluation:
        return cls(
            snapshot_id=snapshot.snapshot_id,
            signal_id=snapshot.signal_id,
            captured_at=require_aware(snapshot.captured_at, "captured_at"),
            evaluation_version=snapshot.evaluation_version,
            evidence_set_version=snapshot.evidence_set_version,
            score=float(snapshot.score),
            confidence=snapshot.confidence,
            state=snapshot.state,
            observation_count=snapshot.observation_count,
            story_count=snapshot.story_count,
            source_count=snapshot.source_count,
            component_values=dict(snapshot.component_values),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "signal_id": self.signal_id,
            "captured_at": iso(self.captured_at),
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


@dataclass(frozen=True)
class RunSignal:
    """The tenant-scoped edge from one run to one globally canonical signal."""

    run_signal_id: str
    run_id: str
    workspace_id: str
    signal_id: str
    snapshot_id: str
    relevance: float

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        workspace_id: str,
        signal_id: str,
        snapshot_id: str,
        relevance: float,
    ) -> RunSignal:
        return cls(
            run_signal_id=ids.run_signal_id(run_id, signal_id),
            run_id=run_id,
            workspace_id=workspace_id,
            signal_id=signal_id,
            snapshot_id=snapshot_id,
            relevance=round(float(relevance), 3),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_signal_id": self.run_signal_id,
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "signal_id": self.signal_id,
            "snapshot_id": self.snapshot_id,
            "relevance": self.relevance,
        }
