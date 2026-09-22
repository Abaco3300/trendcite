"""Canonical observations and their point-in-time snapshots.

An :class:`Observation` is "source S showed us thing X at time T". It is the unit the
intelligence layer reasons over, and it is deliberately separate from
:class:`~trendcite.models.EvidenceItem`, which is the sanitised *display* record.

Time semantics are explicit, because conflating them is how trend tools invent
velocity that never happened:

``event_time``
    When the thing itself happened (the item was published). What recency measures.
``observed_at``
    When the source showed it to us (the fetch that returned it).
``ingested_at``
    When this run took it in. Equal to ``observed_at`` for a live run; for the
    offline demo both are the fixture's pinned reference time.

An :class:`ObservationSnapshot` is one append-only reading of an observation's
mutable facts - its metrics - at a known capture time. Snapshots are never edited:
velocity across runs is derived by comparing two of them, so a rewritten snapshot
would silently rewrite history.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .identity import ObservationIdentity
from .models import EvidenceItem


@dataclass(frozen=True)
class Observation:
    """One canonical record of something a source showed us."""

    identity: ObservationIdentity
    source: str
    source_label: str
    publisher: str
    title: str
    excerpt: str
    url: str
    event_time: datetime
    observed_at: datetime
    ingested_at: datetime
    metrics: Mapping[str, float]
    flags: tuple[str, ...]
    evidence_item_id: str

    @property
    def observation_id(self) -> str:
        return self.identity.observation_id

    @property
    def story_key(self) -> str:
        return self.identity.story_key

    @classmethod
    def from_evidence(cls, item: EvidenceItem, *, ingested_at: datetime) -> Observation:
        return cls(
            identity=item.observation_identity,
            source=item.source,
            source_label=item.source_label,
            publisher=item.publisher,
            title=item.title,
            excerpt=item.excerpt,
            url=item.url,
            event_time=item.published_at,
            observed_at=item.fetched_at,
            ingested_at=ingested_at,
            metrics=dict(item.metrics),
            flags=item.flags,
            evidence_item_id=item.item_id,
        )

    def engagement(self) -> float | None:
        """Raw engagement as the source reports it, or ``None`` when it reports none.

        ``None`` is a fact, not a zero: a feed that carries no vote counts is not a
        post with no votes.
        """
        m = self.metrics
        if self.source in {"hackernews", "reddit"} and ("points" in m or "score" in m):
            return m.get("points", m.get("score", 0.0)) + 0.5 * m.get("comments", 0.0)
        if self.source == "github" and "stars" in m:
            return m["stars"] + 0.25 * m.get("forks", 0.0)
        return None

    def to_dict(self) -> dict[str, Any]:
        """Compact audit record.

        Title, excerpt and metrics already appear in the brief's evidence list; this
        view carries identity and time semantics only, joined by ``observation_id``.
        """
        return {
            "observation_id": self.observation_id,
            "identity": self.identity.to_dict(),
            "source": self.source,
            "source_label": self.source_label,
            "publisher": self.publisher,
            "url": self.url,
            "story_key": self.story_key,
            "event_time": self.event_time.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "evidence_item_id": self.evidence_item_id,
            "flags": list(self.flags),
        }


def observe(items: Iterable[EvidenceItem], *, ingested_at: datetime) -> list[Observation]:
    """Lift display records into canonical observations, order preserved."""
    return [Observation.from_evidence(i, ingested_at=ingested_at) for i in items]


def dedupe_observations(observations: Iterable[Observation]) -> list[Observation]:
    """Keep the first observation per ``observation_id`` (see :mod:`trendcite.identity`)."""
    seen: set[str] = set()
    out: list[Observation] = []
    for obs in observations:
        if obs.observation_id in seen:
            continue
        seen.add(obs.observation_id)
        out.append(obs)
    return out


def story_keys(observations: Iterable[Observation]) -> set[str]:
    """Distinct underlying stories, collapsing syndicated echoes of the same URL."""
    return {o.story_key for o in observations}


@dataclass(frozen=True)
class ObservationSnapshot:
    """An append-only reading of one observation's metrics at a known time."""

    observation_id: str
    captured_at: datetime
    source: str
    story_key: str
    event_time: datetime
    observed_at: datetime
    metrics: Mapping[str, float]

    @classmethod
    def of(cls, observation: Observation, *, captured_at: datetime) -> ObservationSnapshot:
        return cls(
            observation_id=observation.observation_id,
            captured_at=captured_at,
            source=observation.source,
            story_key=observation.story_key,
            event_time=observation.event_time,
            observed_at=observation.observed_at,
            metrics=dict(observation.metrics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "captured_at": self.captured_at.isoformat(),
            "source": self.source,
            "story_key": self.story_key,
            "event_time": self.event_time.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "metrics": dict(self.metrics),
        }
