"""Alerting: what changed, whether it was worth saying, and whether it was said.

Four different questions get four different objects here, because folding any two of
them together is what turns an alerting system into a noise generator:

:class:`MaterialityEvaluation`
    *Did anything change enough to be worth an interruption?* Computed against the
    last state that was actually **delivered**, not against the previous run. A signal
    that drifts by two points a day for a month is one material change, not thirty.
:class:`AlertCandidate`
    *Was this tenant willing to hear it?* Every candidate is persisted, including the
    suppressed ones, with the reason stated. "Why didn't I get an alert?" is a
    question the database can answer.
:class:`Alert`
    *What did we decide to send?* One per qualified candidate.
:class:`DeliveryAttempt`
    *What actually happened on the wire?* Append-only, one row per attempt. An Alert
    that failed three times is one Alert and three attempts, and the third attempt
    succeeding does not rewrite the first two.

Signal strength, relevance and materiality are three separate numbers and stay that
way. A very strong signal that a tenant does not care about is not material to them;
a highly relevant signal that has not moved since the last alert is not material
either. Neither is a delivery state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from .. import ids
from ..errors import ValidationError
from ..versions import ALERT_POLICY_VERSION, MATERIALITY_VERSION
from ._base import iso, require_aware, require_text
from .radar import (
    RUN_COVERAGE_COMPLETE,
    RUN_COVERAGE_STATES,
)

# ----------------------------------------------------------------------- materiality

#: Nothing changed that is worth anyone's attention.
MATERIALITY_NONE = "none"
#: Something moved, but not enough to interrupt anybody by default.
MATERIALITY_MINOR = "minor"
#: The default bar for an immediate alert.
MATERIALITY_MATERIAL = "material"
#: A state change, not merely a magnitude change.
MATERIALITY_MAJOR = "major"
MATERIALITY_LEVELS = (
    MATERIALITY_NONE,
    MATERIALITY_MINOR,
    MATERIALITY_MATERIAL,
    MATERIALITY_MAJOR,
)

_LEVEL_RANK: dict[str, int] = {name: rank for rank, name in enumerate(MATERIALITY_LEVELS)}


def materiality_rank(level: str) -> int:
    """Order materiality levels. Raises rather than guessing at an unknown level."""
    try:
        return _LEVEL_RANK[level]
    except KeyError as exc:
        raise ValidationError(f"unknown materiality level: {level!r}") from exc


def materiality_at_least(level: str, minimum: str) -> bool:
    return materiality_rank(level) >= materiality_rank(minimum)


# --------------------------------------------------------------------- material events

EVENT_NEW_SUBJECT = "new_subject"
EVENT_SIGNAL_SCORE = "signal_score"
EVENT_RELEVANCE = "relevance"
EVENT_LIFECYCLE = "lifecycle_transition"
EVENT_VELOCITY = "velocity"
EVENT_ACCELERATION = "acceleration"
EVENT_CORROBORATION = "corroboration"
EVENT_COUNTEREVIDENCE = "counterevidence"
EVENT_KINDS = (
    EVENT_NEW_SUBJECT,
    EVENT_SIGNAL_SCORE,
    EVENT_RELEVANCE,
    EVENT_LIFECYCLE,
    EVENT_VELOCITY,
    EVENT_ACCELERATION,
    EVENT_CORROBORATION,
    EVENT_COUNTEREVIDENCE,
)

DIRECTION_RISE = "rise"
DIRECTION_DECLINE = "decline"
DIRECTION_NEUTRAL = "neutral"

# Thresholds. All of them are constants rather than tunables on purpose: a threshold a
# caller can pass in is a threshold that is not reproducible from a stored artefact.
SIGNAL_SCORE_MINOR = 5.0
SIGNAL_SCORE_MATERIAL = 10.0
SIGNAL_SCORE_MAJOR = 25.0
RELEVANCE_MINOR = 5.0
RELEVANCE_MATERIAL = 15.0
VELOCITY_MINOR = 0.10
VELOCITY_MATERIAL = 0.25
#: Acceleration is only claimed for something that is *already* moving: a signal that
#: goes from stationary to barely-moving has risen, it has not accelerated.
ACCELERATION_FLOOR = 0.50
CORROBORATION_MATERIAL_SOURCES = 2

#: The velocity component of a core signal evaluation, by name.
VELOCITY_COMPONENT = "velocity"

_LIFECYCLE_RANK: dict[str, int] = {
    "insufficient_data": 0,
    "dormant": 1,
    "emerging": 2,
    "reactivated": 3,
    "sustained": 4,
}


@dataclass(frozen=True)
class MaterialEvent:
    """One named, explainable reason the state moved."""

    event_id: str
    kind: str
    level: str
    direction: str
    detail: str
    before: float | None = None
    after: float | None = None

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        kind: str,
        level: str,
        direction: str,
        detail: str,
        before: float | None = None,
        after: float | None = None,
    ) -> MaterialEvent:
        if kind not in EVENT_KINDS:
            raise ValidationError(f"material event kind must be one of {', '.join(EVENT_KINDS)}")
        materiality_rank(level)
        return cls(
            event_id=ids.material_event_id(snapshot_id, kind),
            kind=kind,
            level=level,
            direction=direction,
            detail=" ".join(detail.split())[:200],
            before=before,
            after=after,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "level": self.level,
            "direction": self.direction,
            "detail": self.detail,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaterialEvent:
        before = data.get("before")
        after = data.get("after")
        return cls(
            event_id=str(data["event_id"]),
            kind=str(data["kind"]),
            level=str(data["level"]),
            direction=str(data["direction"]),
            detail=str(data["detail"]),
            before=None if before is None else float(before),
            after=None if after is None else float(after),
        )


@dataclass(frozen=True)
class MaterialityEvaluation:
    """The verdict: the level, every event behind it, and what was withheld."""

    level: str
    events: tuple[MaterialEvent, ...]
    coverage_state: str
    #: Decline-direction event kinds that were computed and then *not* counted because
    #: the run's source coverage was incomplete. Kept so the omission is auditable.
    withheld_declines: tuple[str, ...]
    materiality_version: str = MATERIALITY_VERSION

    @property
    def coverage_degraded(self) -> bool:
        return self.coverage_state != RUN_COVERAGE_COMPLETE

    def at_least(self, minimum: str) -> bool:
        return materiality_at_least(self.level, minimum)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "events": [event.to_dict() for event in self.events],
            "coverage_state": self.coverage_state,
            "withheld_declines": list(self.withheld_declines),
            "materiality_version": self.materiality_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaterialityEvaluation:
        return cls(
            level=str(data["level"]),
            events=tuple(MaterialEvent.from_dict(item) for item in data["events"]),
            coverage_state=str(data["coverage_state"]),
            withheld_declines=tuple(str(item) for item in data["withheld_declines"]),
            materiality_version=str(data.get("materiality_version", MATERIALITY_VERSION)),
        )


# ------------------------------------------------------------------- observed state


@dataclass(frozen=True)
class SignalState:
    """One subject's evaluated state at one instant, as materiality sees it.

    Deliberately flat and free of storage concerns: the materiality engine is a pure
    function of two of these plus a coverage state, which is what makes it testable
    without a database and reproducible from stored rows.
    """

    signal_id: str
    snapshot_id: str
    signal_score: float
    relevance_score: float
    lifecycle_state: str
    velocity: float | None
    source_count: int
    counterevidence: tuple[str, ...]
    observed_at: datetime

    @classmethod
    def create(
        cls,
        *,
        signal_id: str,
        snapshot_id: str,
        signal_score: float,
        relevance_score: float,
        lifecycle_state: str,
        velocity: float | None = None,
        source_count: int = 0,
        counterevidence: Iterable[str] = (),
        observed_at: datetime,
    ) -> SignalState:
        if source_count < 0:
            raise ValidationError("source_count must not be negative")
        return cls(
            signal_id=signal_id,
            snapshot_id=snapshot_id,
            signal_score=round(float(signal_score), 3),
            relevance_score=round(float(relevance_score), 3),
            lifecycle_state=lifecycle_state,
            velocity=None if velocity is None else round(float(velocity), 4),
            source_count=source_count,
            counterevidence=tuple(sorted({str(code) for code in counterevidence if str(code)})),
            observed_at=require_aware(observed_at, "observed_at"),
        )


@dataclass(frozen=True)
class AlertBaseline:
    """The last state a tenant was actually *told about*, for one subject.

    This is the comparison point, and it only moves on a **successful** delivery. A
    failed send leaves the baseline where it was, so the retry still has something
    material to say and the tenant is not quietly skipped because of our outage.
    """

    baseline_id: str
    workspace_id: str
    watchlist_id: str
    signal_id: str
    alert_id: str
    snapshot_id: str
    signal_score: float
    relevance_score: float
    lifecycle_state: str
    velocity: float | None
    source_count: int
    counterevidence: tuple[str, ...]
    delivered_at: datetime
    materiality_version: str

    @classmethod
    def of(
        cls,
        *,
        workspace_id: str,
        watchlist_id: str,
        signal_id: str,
        alert_id: str,
        state: SignalState,
        delivered_at: datetime,
        materiality_version: str = MATERIALITY_VERSION,
    ) -> AlertBaseline:
        return cls(
            baseline_id=ids.alert_baseline_id(workspace_id, watchlist_id, signal_id),
            workspace_id=workspace_id,
            watchlist_id=watchlist_id,
            signal_id=signal_id,
            alert_id=alert_id,
            snapshot_id=state.snapshot_id,
            signal_score=state.signal_score,
            relevance_score=state.relevance_score,
            lifecycle_state=state.lifecycle_state,
            velocity=state.velocity,
            source_count=state.source_count,
            counterevidence=state.counterevidence,
            delivered_at=require_aware(delivered_at, "delivered_at"),
            materiality_version=materiality_version,
        )

    def as_state(self) -> SignalState:
        return SignalState(
            signal_id=self.signal_id,
            snapshot_id=self.snapshot_id,
            signal_score=self.signal_score,
            relevance_score=self.relevance_score,
            lifecycle_state=self.lifecycle_state,
            velocity=self.velocity,
            source_count=self.source_count,
            counterevidence=self.counterevidence,
            observed_at=self.delivered_at,
        )


# ------------------------------------------------------------------ materiality engine


class MaterialityService:
    """Deterministic ``materiality-v1``.

    Two rules carry most of the weight:

    * **Compare against the last delivered state**, not the last observed one. Slow
      drift is one story, and the tenant hears it once.
    * **Degraded coverage never manufactures a decline.** If a source did not answer,
      the numbers that source feeds go down, and the honest reading of that is "we do
      not know", not "the trend is dying". Every decline-direction event computed under
      incomplete coverage is withheld and recorded as withheld.
    """

    version = MATERIALITY_VERSION

    def evaluate(
        self,
        current: SignalState,
        baseline: AlertBaseline | None,
        *,
        coverage_state: str = RUN_COVERAGE_COMPLETE,
    ) -> MaterialityEvaluation:
        if coverage_state not in RUN_COVERAGE_STATES:
            raise ValidationError("unknown coverage_state")
        if baseline is None:
            event = MaterialEvent.create(
                snapshot_id=current.snapshot_id,
                kind=EVENT_NEW_SUBJECT,
                level=MATERIALITY_MATERIAL,
                direction=DIRECTION_RISE,
                detail="first evaluation of this signal for this watchlist",
                after=current.signal_score,
            )
            return MaterialityEvaluation(
                level=MATERIALITY_MATERIAL,
                events=(event,),
                coverage_state=coverage_state,
                withheld_declines=(),
            )

        previous = baseline.as_state()
        computed = [
            *_score_events(previous, current),
            *_lifecycle_event(previous, current),
            *_velocity_events(previous, current),
            *_corroboration_event(previous, current),
            *_counterevidence_event(previous, current),
        ]

        complete = coverage_state == RUN_COVERAGE_COMPLETE
        kept: list[MaterialEvent] = []
        withheld: list[str] = []
        for event in computed:
            if event.direction == DIRECTION_DECLINE and not complete:
                withheld.append(event.kind)
                continue
            kept.append(event)

        kept.sort(key=lambda e: (-materiality_rank(e.level), e.kind))
        level = MATERIALITY_NONE
        for event in kept:
            if materiality_rank(event.level) > materiality_rank(level):
                level = event.level
        return MaterialityEvaluation(
            level=level,
            events=tuple(kept),
            coverage_state=coverage_state,
            withheld_declines=tuple(sorted(set(withheld))),
        )


def _banded(delta: float, minor: float, material: float, major: float) -> str:
    magnitude = abs(delta)
    if magnitude >= major:
        return MATERIALITY_MAJOR
    if magnitude >= material:
        return MATERIALITY_MATERIAL
    if magnitude >= minor:
        return MATERIALITY_MINOR
    return MATERIALITY_NONE


def _direction(delta: float) -> str:
    if delta > 0:
        return DIRECTION_RISE
    if delta < 0:
        return DIRECTION_DECLINE
    return DIRECTION_NEUTRAL


def _score_events(previous: SignalState, current: SignalState) -> list[MaterialEvent]:
    events: list[MaterialEvent] = []
    signal_delta = current.signal_score - previous.signal_score
    level = _banded(signal_delta, SIGNAL_SCORE_MINOR, SIGNAL_SCORE_MATERIAL, SIGNAL_SCORE_MAJOR)
    if level != MATERIALITY_NONE:
        events.append(
            MaterialEvent.create(
                snapshot_id=current.snapshot_id,
                kind=EVENT_SIGNAL_SCORE,
                level=level,
                direction=_direction(signal_delta),
                detail=(
                    f"signal score moved {signal_delta:+.1f} "
                    f"({previous.signal_score:.1f} to {current.signal_score:.1f})"
                ),
                before=previous.signal_score,
                after=current.signal_score,
            )
        )
    relevance_delta = current.relevance_score - previous.relevance_score
    level = _banded(relevance_delta, RELEVANCE_MINOR, RELEVANCE_MATERIAL, SIGNAL_SCORE_MAJOR)
    if level != MATERIALITY_NONE:
        events.append(
            MaterialEvent.create(
                snapshot_id=current.snapshot_id,
                kind=EVENT_RELEVANCE,
                level=level,
                direction=_direction(relevance_delta),
                detail=(
                    f"relevance moved {relevance_delta:+.1f} "
                    f"({previous.relevance_score:.1f} to {current.relevance_score:.1f})"
                ),
                before=previous.relevance_score,
                after=current.relevance_score,
            )
        )
    return events


def _lifecycle_event(previous: SignalState, current: SignalState) -> list[MaterialEvent]:
    if current.lifecycle_state == previous.lifecycle_state:
        return []
    before = _LIFECYCLE_RANK.get(previous.lifecycle_state, 0)
    after = _LIFECYCLE_RANK.get(current.lifecycle_state, 0)
    # A signal coming back from dormancy is the one lifecycle move that is a story in
    # its own right rather than a matter of degree, so it outranks the others.
    level = MATERIALITY_MAJOR if current.lifecycle_state == "reactivated" else MATERIALITY_MATERIAL
    return [
        MaterialEvent.create(
            snapshot_id=current.snapshot_id,
            kind=EVENT_LIFECYCLE,
            level=level,
            direction=_direction(after - before),
            detail=f"lifecycle moved {previous.lifecycle_state} to {current.lifecycle_state}",
            before=float(before),
            after=float(after),
        )
    ]


def _velocity_events(previous: SignalState, current: SignalState) -> list[MaterialEvent]:
    if previous.velocity is None or current.velocity is None:
        return []
    delta = current.velocity - previous.velocity
    events: list[MaterialEvent] = []
    level = _banded(delta, VELOCITY_MINOR, VELOCITY_MATERIAL, VELOCITY_MATERIAL * 2)
    if level != MATERIALITY_NONE:
        events.append(
            MaterialEvent.create(
                snapshot_id=current.snapshot_id,
                kind=EVENT_VELOCITY,
                level=level,
                direction=_direction(delta),
                detail=(
                    f"velocity moved {delta:+.2f} "
                    f"({previous.velocity:.2f} to {current.velocity:.2f})"
                ),
                before=previous.velocity,
                after=current.velocity,
            )
        )
    # Two stored points give one derivative, so "acceleration" here means the narrow,
    # defensible thing: something already moving fast is moving measurably faster.
    if delta >= VELOCITY_MINOR and current.velocity >= ACCELERATION_FLOOR:
        events.append(
            MaterialEvent.create(
                snapshot_id=current.snapshot_id,
                kind=EVENT_ACCELERATION,
                level=MATERIALITY_MATERIAL,
                direction=DIRECTION_RISE,
                detail=(
                    f"already-fast signal gained {delta:+.2f} velocity (now {current.velocity:.2f})"
                ),
                before=previous.velocity,
                after=current.velocity,
            )
        )
    return events


def _corroboration_event(previous: SignalState, current: SignalState) -> list[MaterialEvent]:
    delta = current.source_count - previous.source_count
    if delta == 0:
        return []
    level = (
        MATERIALITY_MATERIAL if abs(delta) >= CORROBORATION_MATERIAL_SOURCES else MATERIALITY_MINOR
    )
    return [
        MaterialEvent.create(
            snapshot_id=current.snapshot_id,
            kind=EVENT_CORROBORATION,
            level=level,
            direction=_direction(float(delta)),
            detail=(
                f"corroborating sources moved {delta:+d} "
                f"({previous.source_count} to {current.source_count})"
            ),
            before=float(previous.source_count),
            after=float(current.source_count),
        )
    ]


def _counterevidence_event(previous: SignalState, current: SignalState) -> list[MaterialEvent]:
    before = set(previous.counterevidence)
    after = set(current.counterevidence)
    added = sorted(after - before)
    cleared = sorted(before - after)
    if added:
        return [
            MaterialEvent.create(
                snapshot_id=current.snapshot_id,
                kind=EVENT_COUNTEREVIDENCE,
                level=MATERIALITY_MATERIAL,
                direction=DIRECTION_DECLINE,
                detail=f"new counterevidence: {', '.join(added)}",
                before=float(len(before)),
                after=float(len(after)),
            )
        ]
    if cleared:
        return [
            MaterialEvent.create(
                snapshot_id=current.snapshot_id,
                kind=EVENT_COUNTEREVIDENCE,
                level=MATERIALITY_MINOR,
                direction=DIRECTION_RISE,
                detail=f"counterevidence cleared: {', '.join(cleared)}",
                before=float(len(before)),
                after=float(len(after)),
            )
        ]
    return []


DEFAULT_MATERIALITY_SERVICE = MaterialityService()


# --------------------------------------------------------------------------- policy

DEFAULT_MIN_RELEVANCE = 60.0
DEFAULT_MIN_MATERIALITY = MATERIALITY_MATERIAL
DEFAULT_COOLDOWN_HOURS = 24.0
DEFAULT_DIGEST_MAX_ITEMS = 5
DEFAULT_MAX_DELIVERY_ATTEMPTS = 3
#: The only adapter this build ships. Provider-neutral by construction: the policy
#: names a channel, the channel is resolved to a port, and nothing above the port
#: knows which provider answered.
CHANNEL_LOCAL = "local"


@dataclass(frozen=True)
class AlertPolicy:
    """One tenant's delivery preferences for one radar."""

    policy_id: str
    workspace_id: str
    radar_id: str
    enabled: bool
    immediate_alerts: bool
    daily_digest: bool
    min_relevance: float
    min_materiality: str
    cooldown_hours: float
    digest_max_items: int
    max_delivery_attempts: int
    channel: str
    policy_version: str
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        radar_id: str,
        updated_at: datetime,
        enabled: bool = True,
        immediate_alerts: bool = True,
        daily_digest: bool = True,
        min_relevance: float = DEFAULT_MIN_RELEVANCE,
        min_materiality: str = DEFAULT_MIN_MATERIALITY,
        cooldown_hours: float = DEFAULT_COOLDOWN_HOURS,
        digest_max_items: int = DEFAULT_DIGEST_MAX_ITEMS,
        max_delivery_attempts: int = DEFAULT_MAX_DELIVERY_ATTEMPTS,
        channel: str = CHANNEL_LOCAL,
    ) -> AlertPolicy:
        materiality_rank(min_materiality)
        if not 0.0 <= min_relevance <= 100.0:
            raise ValidationError("min_relevance must be between 0 and 100")
        if cooldown_hours < 0:
            raise ValidationError("cooldown_hours must not be negative")
        if not 1 <= digest_max_items <= 50:
            raise ValidationError("digest_max_items must be between 1 and 50")
        if not 1 <= max_delivery_attempts <= 10:
            raise ValidationError("max_delivery_attempts must be between 1 and 10")
        return cls(
            policy_id=ids.alert_policy_id(workspace_id, radar_id),
            workspace_id=workspace_id,
            radar_id=radar_id,
            enabled=enabled,
            immediate_alerts=immediate_alerts,
            daily_digest=daily_digest,
            min_relevance=round(float(min_relevance), 3),
            min_materiality=min_materiality,
            cooldown_hours=round(float(cooldown_hours), 3),
            digest_max_items=digest_max_items,
            max_delivery_attempts=max_delivery_attempts,
            channel=require_text(channel, "channel", limit=40),
            policy_version=ALERT_POLICY_VERSION,
            updated_at=require_aware(updated_at, "updated_at"),
        )

    @classmethod
    def default_for(cls, *, workspace_id: str, radar_id: str, updated_at: datetime) -> AlertPolicy:
        """The documented defaults, materialised rather than implied.

        A radar with no stored policy still has one; it just has not been edited. That
        keeps "unset" and "set to the default" the same thing for every reader.
        """
        return cls.create(workspace_id=workspace_id, radar_id=radar_id, updated_at=updated_at)

    @property
    def cooldown(self) -> timedelta:
        return timedelta(hours=self.cooldown_hours)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "enabled": self.enabled,
            "immediate_alerts": self.immediate_alerts,
            "daily_digest": self.daily_digest,
            "min_relevance": self.min_relevance,
            "min_materiality": self.min_materiality,
            "cooldown_hours": self.cooldown_hours,
            "digest_max_items": self.digest_max_items,
            "max_delivery_attempts": self.max_delivery_attempts,
            "channel": self.channel,
            "policy_version": self.policy_version,
            "updated_at": iso(self.updated_at),
        }


# ------------------------------------------------------------------------- candidates

CANDIDATE_QUALIFIED = "qualified"
CANDIDATE_SUPPRESSED = "suppressed"
CANDIDATE_STATUSES = (CANDIDATE_QUALIFIED, CANDIDATE_SUPPRESSED)

REASON_QUALIFIED = "qualified"
REASON_DELIVERY_DISABLED = "delivery_disabled"
REASON_MUTED = "muted"
REASON_DISMISSED = "dismissed"
REASON_BELOW_RELEVANCE = "below_relevance"
REASON_BELOW_MATERIALITY = "below_materiality"
REASON_DUPLICATE = "duplicate"
REASON_COOLDOWN = "cooldown"
#: The qualification order, stated once. Everything downstream reads it from here
#: rather than re-encoding it, so "why was this suppressed" has exactly one answer.
CANDIDATE_REASONS = (
    REASON_DELIVERY_DISABLED,
    REASON_MUTED,
    REASON_DISMISSED,
    REASON_BELOW_RELEVANCE,
    REASON_BELOW_MATERIALITY,
    REASON_DUPLICATE,
    REASON_COOLDOWN,
    REASON_QUALIFIED,
)

#: Cooldown silences an *interruption*, not the news itself: a signal held back by a
#: quiet period is exactly the sort of thing a daily digest exists to carry.
DIGEST_ELIGIBLE_REASONS = frozenset({REASON_QUALIFIED, REASON_COOLDOWN})


@dataclass(frozen=True)
class AlertCandidate:
    """One evaluated opportunity to interrupt a tenant, kept whatever we decided."""

    candidate_id: str
    workspace_id: str
    radar_id: str
    watchlist_id: str
    signal_id: str
    snapshot_id: str
    run_id: str
    subject_key: str
    status: str
    reason: str
    label: str
    relevance_score: float
    signal_score: float
    lifecycle_state: str
    velocity: float | None
    source_count: int
    counterevidence: tuple[str, ...]
    materiality: str
    materiality_version: str
    evaluation: MaterialityEvaluation
    observed_at: datetime
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        radar_id: str,
        watchlist_id: str,
        run_id: str,
        label: str,
        state: SignalState,
        evaluation: MaterialityEvaluation,
        reason: str,
        created_at: datetime,
    ) -> AlertCandidate:
        if reason not in CANDIDATE_REASONS:
            raise ValidationError(f"reason must be one of {', '.join(CANDIDATE_REASONS)}")
        return cls(
            candidate_id=ids.alert_candidate_id(
                workspace_id,
                watchlist_id,
                state.signal_id,
                state.snapshot_id,
                evaluation.materiality_version,
            ),
            workspace_id=workspace_id,
            radar_id=radar_id,
            watchlist_id=watchlist_id,
            signal_id=state.signal_id,
            snapshot_id=state.snapshot_id,
            run_id=run_id,
            subject_key=ids.alert_subject_key(workspace_id, watchlist_id, state.signal_id),
            status=CANDIDATE_QUALIFIED if reason == REASON_QUALIFIED else CANDIDATE_SUPPRESSED,
            reason=reason,
            label=" ".join(label.split())[:200],
            relevance_score=state.relevance_score,
            signal_score=state.signal_score,
            lifecycle_state=state.lifecycle_state,
            velocity=state.velocity,
            source_count=state.source_count,
            counterevidence=state.counterevidence,
            materiality=evaluation.level,
            materiality_version=evaluation.materiality_version,
            evaluation=evaluation,
            observed_at=require_aware(state.observed_at, "observed_at"),
            created_at=require_aware(created_at, "created_at"),
        )

    @property
    def qualified(self) -> bool:
        return self.status == CANDIDATE_QUALIFIED

    @property
    def digest_eligible(self) -> bool:
        return self.reason in DIGEST_ELIGIBLE_REASONS

    def as_state(self) -> SignalState:
        """The exact observed state this candidate judged.

        Carried on the row rather than reconstructed from the events, because the
        events only describe what *moved*: a baseline rebuilt from them would silently
        lose every field that happened to be unchanged, and the next comparison would
        then invent a change that never occurred.
        """
        return SignalState(
            signal_id=self.signal_id,
            snapshot_id=self.snapshot_id,
            signal_score=self.signal_score,
            relevance_score=self.relevance_score,
            lifecycle_state=self.lifecycle_state,
            velocity=self.velocity,
            source_count=self.source_count,
            counterevidence=self.counterevidence,
            observed_at=self.observed_at,
        )

    def with_reason(self, reason: str) -> AlertCandidate:
        """A re-read of the same candidate under a different decision.

        Used for the in-memory duplicate verdict only: the *stored* candidate keeps the
        reason it was first written with, because the second look at one event is not
        a second event.
        """
        if reason not in CANDIDATE_REASONS:
            raise ValidationError(f"reason must be one of {', '.join(CANDIDATE_REASONS)}")
        status = CANDIDATE_QUALIFIED if reason == REASON_QUALIFIED else CANDIDATE_SUPPRESSED
        return replace(self, reason=reason, status=status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "watchlist_id": self.watchlist_id,
            "signal_id": self.signal_id,
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "subject_key": self.subject_key,
            "status": self.status,
            "reason": self.reason,
            "label": self.label,
            "relevance_score": self.relevance_score,
            "signal_score": self.signal_score,
            "lifecycle_state": self.lifecycle_state,
            "velocity": self.velocity,
            "source_count": self.source_count,
            "counterevidence": list(self.counterevidence),
            "materiality": self.materiality,
            "materiality_version": self.materiality_version,
            "evaluation": self.evaluation.to_dict(),
            "observed_at": iso(self.observed_at),
            "created_at": iso(self.created_at),
        }


# ------------------------------------------------------------------------- payloads


@dataclass(frozen=True)
class AlertPayload:
    """Rendered, provider-neutral content. No channel, no address, no credentials."""

    subject: str
    body: str
    renderer_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "renderer_version": self.renderer_version,
        }


# --------------------------------------------------------------------------- alerts

DELIVERY_PENDING = "pending"
DELIVERY_DELIVERED = "delivered"
DELIVERY_FAILED = "failed"
DELIVERY_STATES = (DELIVERY_PENDING, DELIVERY_DELIVERED, DELIVERY_FAILED)


@dataclass(frozen=True)
class Alert:
    """What we decided to send. Its delivery state is bookkeeping, not truth about
    the signal: an undelivered alert is still a correct judgement that was made."""

    alert_id: str
    workspace_id: str
    radar_id: str
    watchlist_id: str
    signal_id: str
    snapshot_id: str
    candidate_id: str
    subject_key: str
    materiality: str
    relevance_score: float
    signal_score: float
    channel: str
    delivery_state: str
    attempt_count: int
    subject: str
    body: str
    renderer_version: str
    created_at: datetime
    delivered_at: datetime | None

    @classmethod
    def from_candidate(
        cls,
        candidate: AlertCandidate,
        *,
        payload: AlertPayload,
        channel: str,
        created_at: datetime,
    ) -> Alert:
        if not candidate.qualified:
            raise ValidationError("only a qualified candidate may become an alert")
        return cls(
            alert_id=ids.alert_id(candidate.candidate_id),
            workspace_id=candidate.workspace_id,
            radar_id=candidate.radar_id,
            watchlist_id=candidate.watchlist_id,
            signal_id=candidate.signal_id,
            snapshot_id=candidate.snapshot_id,
            candidate_id=candidate.candidate_id,
            subject_key=candidate.subject_key,
            materiality=candidate.materiality,
            relevance_score=candidate.relevance_score,
            signal_score=candidate.signal_score,
            channel=channel,
            delivery_state=DELIVERY_PENDING,
            attempt_count=0,
            subject=payload.subject,
            body=payload.body,
            renderer_version=payload.renderer_version,
            created_at=require_aware(created_at, "created_at"),
            delivered_at=None,
        )

    def delivered(self, *, attempt_count: int, delivered_at: datetime) -> Alert:
        return replace(
            self,
            delivery_state=DELIVERY_DELIVERED,
            attempt_count=attempt_count,
            delivered_at=require_aware(delivered_at, "delivered_at"),
        )

    def attempted(self, *, attempt_count: int, exhausted: bool) -> Alert:
        """Record a failed attempt. Only exhaustion is terminal.

        A pending alert with two failures behind it is not the same thing as a failed
        one, and the difference is what makes a retry legitimate rather than a second
        alert.
        """
        return replace(
            self,
            delivery_state=DELIVERY_FAILED if exhausted else DELIVERY_PENDING,
            attempt_count=attempt_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "watchlist_id": self.watchlist_id,
            "signal_id": self.signal_id,
            "snapshot_id": self.snapshot_id,
            "candidate_id": self.candidate_id,
            "subject_key": self.subject_key,
            "materiality": self.materiality,
            "relevance_score": self.relevance_score,
            "signal_score": self.signal_score,
            "channel": self.channel,
            "delivery_state": self.delivery_state,
            "attempt_count": self.attempt_count,
            "subject": self.subject,
            "renderer_version": self.renderer_version,
            "created_at": iso(self.created_at),
            "delivered_at": None if self.delivered_at is None else iso(self.delivered_at),
        }


# ------------------------------------------------------------------ delivery attempts

TARGET_ALERT = "alert"
TARGET_DIGEST = "digest"
TARGET_KINDS = (TARGET_ALERT, TARGET_DIGEST)

ATTEMPT_SUCCEEDED = "succeeded"
ATTEMPT_FAILED = "failed"
ATTEMPT_STATUSES = (ATTEMPT_SUCCEEDED, ATTEMPT_FAILED)


@dataclass(frozen=True)
class DeliveryAttempt:
    """One append-only record of what a provider did with one payload.

    This is the only place provider-specific metadata is allowed to live. The Alert
    above knows it has a channel and a delivery state; it does not know that some
    adapter called the thing a ``message_id``.
    """

    attempt_id: str
    workspace_id: str
    target_kind: str
    target_id: str
    attempt_number: int
    channel: str
    status: str
    provider: str
    provider_reference: str
    detail: str
    attempted_at: datetime

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        target_kind: str,
        target_id: str,
        attempt_number: int,
        channel: str,
        status: str,
        provider: str = "",
        provider_reference: str = "",
        detail: str = "",
        attempted_at: datetime,
    ) -> DeliveryAttempt:
        if target_kind not in TARGET_KINDS:
            raise ValidationError(f"target_kind must be one of {', '.join(TARGET_KINDS)}")
        if status not in ATTEMPT_STATUSES:
            raise ValidationError(f"attempt status must be one of {', '.join(ATTEMPT_STATUSES)}")
        if attempt_number < 1:
            raise ValidationError("attempt_number must be 1 or greater")
        return cls(
            attempt_id=ids.delivery_attempt_id(
                workspace_id, target_kind, target_id, attempt_number
            ),
            workspace_id=workspace_id,
            target_kind=target_kind,
            target_id=target_id,
            attempt_number=attempt_number,
            channel=channel,
            status=status,
            provider=provider[:80],
            provider_reference=provider_reference[:120],
            detail=" ".join(detail.split())[:200],
            attempted_at=require_aware(attempted_at, "attempted_at"),
        )

    @property
    def succeeded(self) -> bool:
        return self.status == ATTEMPT_SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "workspace_id": self.workspace_id,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "attempt_number": self.attempt_number,
            "channel": self.channel,
            "status": self.status,
            "provider": self.provider,
            "provider_reference": self.provider_reference,
            "detail": self.detail,
            "attempted_at": iso(self.attempted_at),
        }


def latest_attempt_number(attempts: Sequence[DeliveryAttempt]) -> int:
    return max((a.attempt_number for a in attempts), default=0)
