"""Digest, DigestItem and DigestPayload: the batched counterpart to an Alert.

A digest exists because suppression is not the same as deletion. A signal that was
held back by a cooldown was still worth knowing about; it just was not worth an
interruption. The digest is where that material goes, which is what lets the cooldown
be strict without losing anything.

Scoping and identity:

* **Radar-scoped, one per day.** ``digest_id`` is a function of
  (workspace, radar, date), so rebuilding a day is idempotent rather than additive --
  a second build of Tuesday updates Tuesday, it does not create a second Tuesday.
* **One signal at most once.** ``digest_item_id`` is a function of (digest, signal),
  so the "a signal appears once" rule is held by a primary key rather than by whoever
  happens to be writing the ranking loop.
* **An empty digest is not a digest.** Nothing is persisted and nothing is delivered
  when a day produced no eligible material, because "we have nothing for you" is not
  worth a tenant's attention and a stored empty row invites one to be sent.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import ids
from ..errors import ValidationError
from ._base import iso, require_aware
from .alerts import (
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    AlertCandidate,
    materiality_rank,
)


def digest_window(day: datetime) -> tuple[datetime, datetime, str]:
    """The UTC day containing ``day``, as ``(start, end, YYYY-MM-DD)``.

    Half-open ``[start, end)``: an event at exactly midnight belongs to the day that
    is starting, not to the one that just ended, so no event can land in two digests
    and none can fall between them.
    """
    when = require_aware(day, "day").astimezone(UTC)
    start = when.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1), start.date().isoformat()


@dataclass(frozen=True)
class DigestPayload:
    """Rendered, provider-neutral digest content."""

    subject: str
    body: str
    renderer_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "renderer_version": self.renderer_version,
        }


@dataclass(frozen=True)
class DigestItem:
    """One ranked signal inside one digest."""

    item_id: str
    digest_id: str
    workspace_id: str
    signal_id: str
    candidate_id: str
    snapshot_id: str
    rank: int
    label: str
    materiality: str
    relevance_score: float
    signal_score: float
    observed_at: datetime

    @classmethod
    def of(
        cls,
        candidate: AlertCandidate,
        *,
        digest_id: str,
        rank: int,
    ) -> DigestItem:
        if rank < 1:
            raise ValidationError("digest item rank must be 1 or greater")
        return cls(
            item_id=ids.digest_item_id(digest_id, candidate.signal_id),
            digest_id=digest_id,
            workspace_id=candidate.workspace_id,
            signal_id=candidate.signal_id,
            candidate_id=candidate.candidate_id,
            snapshot_id=candidate.snapshot_id,
            rank=rank,
            label=candidate.label,
            materiality=candidate.materiality,
            relevance_score=candidate.relevance_score,
            signal_score=candidate.signal_score,
            observed_at=candidate.observed_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "digest_id": self.digest_id,
            "workspace_id": self.workspace_id,
            "signal_id": self.signal_id,
            "candidate_id": self.candidate_id,
            "snapshot_id": self.snapshot_id,
            "rank": self.rank,
            "label": self.label,
            "materiality": self.materiality,
            "relevance_score": self.relevance_score,
            "signal_score": self.signal_score,
            "observed_at": iso(self.observed_at),
        }


def digest_sort_key(candidate: AlertCandidate) -> tuple[int, float, float, float, str]:
    """Total order over candidates: materiality, relevance, signal score, recency, id.

    Every tie is broken, and the last tiebreak is an id rather than anything temporal,
    so the same day's material always ranks the same way however the rows are read
    back. A ranking that depends on row order is a ranking that changes under you.
    """
    return (
        -materiality_rank(candidate.materiality),
        -candidate.relevance_score,
        -candidate.signal_score,
        -candidate.observed_at.timestamp(),
        candidate.signal_id,
    )


def rank_candidates(
    candidates: Iterable[AlertCandidate],
    *,
    max_items: int,
) -> list[AlertCandidate]:
    """Digest-eligible candidates, one per signal, best first, capped at ``max_items``.

    Deduplication happens *before* the cap, so a signal that produced three candidates
    in one day consumes one of the five slots rather than three of them.
    """
    if max_items < 1:
        raise ValidationError("max_items must be 1 or greater")
    ordered = sorted((c for c in candidates if c.digest_eligible), key=digest_sort_key)
    best: dict[str, AlertCandidate] = {}
    for candidate in ordered:
        best.setdefault(candidate.signal_id, candidate)
    return sorted(best.values(), key=digest_sort_key)[:max_items]


@dataclass(frozen=True)
class Digest:
    """One radar's batched material for one UTC day."""

    digest_id: str
    workspace_id: str
    radar_id: str
    digest_date: str
    window_start: datetime
    window_end: datetime
    item_count: int
    channel: str
    delivery_state: str
    attempt_count: int
    subject: str
    body: str
    renderer_version: str
    created_at: datetime
    delivered_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        radar_id: str,
        day: datetime,
        items: Sequence[DigestItem],
        payload: DigestPayload,
        channel: str,
        created_at: datetime,
    ) -> Digest:
        if not items:
            raise ValidationError("an empty digest is never created")
        start, end, date_key = digest_window(day)
        return cls(
            digest_id=ids.digest_id(workspace_id, radar_id, date_key),
            workspace_id=workspace_id,
            radar_id=radar_id,
            digest_date=date_key,
            window_start=start,
            window_end=end,
            item_count=len(items),
            channel=channel,
            delivery_state=DELIVERY_PENDING,
            attempt_count=0,
            subject=payload.subject,
            body=payload.body,
            renderer_version=payload.renderer_version,
            created_at=require_aware(created_at, "created_at"),
            delivered_at=None,
        )

    def delivered(self, *, attempt_count: int, delivered_at: datetime) -> Digest:
        return replace(
            self,
            delivery_state=DELIVERY_DELIVERED,
            attempt_count=attempt_count,
            delivered_at=require_aware(delivered_at, "delivered_at"),
        )

    def attempted(self, *, attempt_count: int, exhausted: bool) -> Digest:
        return replace(
            self,
            delivery_state=DELIVERY_FAILED if exhausted else DELIVERY_PENDING,
            attempt_count=attempt_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest_id": self.digest_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "digest_date": self.digest_date,
            "window_start": iso(self.window_start),
            "window_end": iso(self.window_end),
            "item_count": self.item_count,
            "channel": self.channel,
            "delivery_state": self.delivery_state,
            "attempt_count": self.attempt_count,
            "subject": self.subject,
            "renderer_version": self.renderer_version,
            "created_at": iso(self.created_at),
            "delivered_at": None if self.delivered_at is None else iso(self.delivered_at),
        }
