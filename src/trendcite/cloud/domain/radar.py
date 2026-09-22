"""Radar, RadarVersion, RadarRun and Coverage: pinned configuration and pinned runs.

The pinning chain is the whole point and is enforced by construction:

``RadarVersion`` -> exact ``WatchlistVersion`` ids
    A radar version references *versions*, never watchlists. "Run my radar" can never
    silently pick up a watchlist edit made after the fact.
``RadarRun`` -> exact ``RadarVersion`` + ``evaluation_cutoff``
    Configuration and time are both pinned, so a run is reproducible: the same pin
    evaluated again is the same run, which is exactly what the idempotency key says.

Coverage is recorded per source per run, and it distinguishes the two things trend
tools habitually conflate: a source that answered and had nothing (``ok``, zero
items) and a source that did not answer at all (``failed``). Only the first one means
"no activity".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from .. import ids
from ..errors import ValidationError
from ._base import iso, require_aware, require_text

# ------------------------------------------------------------------------- run status

RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_STATUSES = (RUN_PENDING, RUN_RUNNING, RUN_SUCCEEDED, RUN_FAILED)

#: A run in one of these states is finished; re-requesting it is not a retry.
TERMINAL_STATUSES = frozenset({RUN_SUCCEEDED, RUN_FAILED})

# ---------------------------------------------------------------------- source coverage

COVERAGE_OK = "ok"
COVERAGE_DEGRADED = "degraded"
COVERAGE_FAILED = "failed"
COVERAGE_SKIPPED = "skipped"
COVERAGE_STATES = (COVERAGE_OK, COVERAGE_DEGRADED, COVERAGE_FAILED, COVERAGE_SKIPPED)

# ------------------------------------------------------------------- run-level coverage

#: No coverage has been recorded yet (the run has not finished collecting).
RUN_COVERAGE_UNKNOWN = "unknown"
#: Every requested source answered.
RUN_COVERAGE_COMPLETE = "complete"
#: At least one requested source answered and at least one did not.
RUN_COVERAGE_DEGRADED = "degraded"
#: No requested source answered. The run has no basis for any claim about activity.
RUN_COVERAGE_UNAVAILABLE = "unavailable"
RUN_COVERAGE_STATES = (
    RUN_COVERAGE_UNKNOWN,
    RUN_COVERAGE_COMPLETE,
    RUN_COVERAGE_DEGRADED,
    RUN_COVERAGE_UNAVAILABLE,
)


@dataclass(frozen=True)
class Radar:
    """A named, tenant-scoped radar. Carries no configuration; its versions do."""

    radar_id: str
    workspace_id: str
    name: str
    created_at: datetime

    @classmethod
    def create(cls, *, workspace_id: str, name: str, created_at: datetime) -> Radar:
        canonical = require_text(name, "radar name")
        return cls(
            radar_id=ids.radar_id(workspace_id, canonical),
            workspace_id=workspace_id,
            name=canonical,
            created_at=require_aware(created_at, "created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "radar_id": self.radar_id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "created_at": iso(self.created_at),
        }


@dataclass(frozen=True)
class RadarVersion:
    """An immutable radar configuration pinned to exact watchlist versions."""

    version_id: str
    radar_id: str
    workspace_id: str
    version_number: int
    watchlist_version_ids: tuple[str, ...]
    sources: tuple[str, ...]
    niche: tuple[str, ...]
    top: int
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        radar_id: str,
        workspace_id: str,
        version_number: int,
        watchlist_version_ids: Iterable[str],
        sources: Iterable[str],
        niche: Iterable[str] = (),
        top: int = 5,
        created_at: datetime,
    ) -> RadarVersion:
        if version_number < 1:
            raise ValidationError("version_number must be 1 or greater")
        pinned = tuple(dict.fromkeys(str(v) for v in watchlist_version_ids if str(v).strip()))
        if not pinned:
            raise ValidationError("a radar version must pin at least one watchlist version")
        wanted = tuple(dict.fromkeys(str(s).strip().lower() for s in sources if str(s).strip()))
        if not wanted:
            raise ValidationError("a radar version must name at least one source")
        if not 1 <= top <= 50:
            raise ValidationError("top must be between 1 and 50")
        return cls(
            version_id=ids.radar_version_id(radar_id, version_number, pinned, wanted),
            radar_id=radar_id,
            workspace_id=workspace_id,
            version_number=version_number,
            watchlist_version_ids=pinned,
            sources=wanted,
            niche=tuple(dict.fromkeys(str(n).strip().lower() for n in niche if str(n).strip())),
            top=top,
            created_at=require_aware(created_at, "created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "radar_id": self.radar_id,
            "workspace_id": self.workspace_id,
            "version_number": self.version_number,
            "watchlist_version_ids": list(self.watchlist_version_ids),
            "sources": list(self.sources),
            "niche": list(self.niche),
            "top": self.top,
            "created_at": iso(self.created_at),
        }


@dataclass(frozen=True)
class Coverage:
    """What one source contributed to one run, stated rather than inferred."""

    coverage_id: str
    run_id: str
    workspace_id: str
    source: str
    state: str
    item_count: int
    detail: str
    observed_at: datetime

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        workspace_id: str,
        source: str,
        state: str,
        item_count: int,
        detail: str = "",
        observed_at: datetime,
    ) -> Coverage:
        if state not in COVERAGE_STATES:
            raise ValidationError(f"coverage state must be one of {', '.join(COVERAGE_STATES)}")
        if item_count < 0:
            raise ValidationError("item_count must not be negative")
        return cls(
            coverage_id=ids.coverage_id(run_id, source),
            run_id=run_id,
            workspace_id=workspace_id,
            source=source,
            state=state,
            item_count=item_count,
            detail=" ".join(detail.split())[:200],
            observed_at=require_aware(observed_at, "observed_at"),
        )

    @property
    def answered(self) -> bool:
        """True when the source responded at all, whatever it had to say."""
        return self.state in {COVERAGE_OK, COVERAGE_DEGRADED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_id": self.coverage_id,
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "source": self.source,
            "state": self.state,
            "item_count": self.item_count,
            "detail": self.detail,
            "observed_at": iso(self.observed_at),
        }


def summarize_coverage(coverage: Sequence[Coverage]) -> str:
    """Roll per-source coverage up to the run-level state."""
    considered = [c for c in coverage if c.state != COVERAGE_SKIPPED]
    if not considered:
        return RUN_COVERAGE_UNKNOWN
    answered = [c for c in considered if c.answered]
    if len(answered) == len(considered):
        return RUN_COVERAGE_COMPLETE
    if not answered:
        return RUN_COVERAGE_UNAVAILABLE
    return RUN_COVERAGE_DEGRADED


@dataclass(frozen=True)
class RadarRun:
    """One pinned execution of one radar version, as of one evaluation cutoff."""

    run_id: str
    workspace_id: str
    radar_id: str
    radar_version_id: str
    evaluation_cutoff: datetime
    idempotency_key: str
    status: str
    coverage_state: str
    attempt: int
    signal_count: int
    match_count: int
    error_code: str
    error_detail: str
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        radar_id: str,
        radar_version_id: str,
        evaluation_cutoff: datetime,
        started_at: datetime,
    ) -> RadarRun:
        cutoff = require_aware(evaluation_cutoff, "evaluation_cutoff")
        key = ids.run_idempotency_key(workspace_id, radar_version_id, iso(cutoff))
        return cls(
            run_id=ids.run_id(workspace_id, key),
            workspace_id=workspace_id,
            radar_id=radar_id,
            radar_version_id=radar_version_id,
            evaluation_cutoff=cutoff,
            idempotency_key=key,
            status=RUN_RUNNING,
            coverage_state=RUN_COVERAGE_UNKNOWN,
            attempt=1,
            signal_count=0,
            match_count=0,
            error_code="",
            error_detail="",
            started_at=require_aware(started_at, "started_at"),
            finished_at=None,
        )

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def retrying(self, *, started_at: datetime) -> RadarRun:
        """Re-open a failed run as the next attempt, clearing the previous error.

        The ``run_id`` is deliberately unchanged: a retry is another attempt at the
        same logical run, not a second run, which is what keeps outputs from
        duplicating when a transient failure is retried.
        """
        if self.status == RUN_SUCCEEDED:
            raise ValidationError("a succeeded run cannot be retried")
        return replace(
            self,
            status=RUN_RUNNING,
            attempt=self.attempt + 1,
            error_code="",
            error_detail="",
            coverage_state=RUN_COVERAGE_UNKNOWN,
            signal_count=0,
            match_count=0,
            started_at=require_aware(started_at, "started_at"),
            finished_at=None,
        )

    def succeeded(
        self,
        *,
        coverage_state: str,
        signal_count: int,
        match_count: int,
        finished_at: datetime,
    ) -> RadarRun:
        if coverage_state not in RUN_COVERAGE_STATES:
            raise ValidationError("unknown coverage_state")
        return replace(
            self,
            status=RUN_SUCCEEDED,
            coverage_state=coverage_state,
            signal_count=signal_count,
            match_count=match_count,
            error_code="",
            error_detail="",
            finished_at=require_aware(finished_at, "finished_at"),
        )

    def failed(self, *, code: str, detail: str, finished_at: datetime) -> RadarRun:
        return replace(
            self,
            status=RUN_FAILED,
            error_code=code[:80],
            error_detail=detail,
            finished_at=require_aware(finished_at, "finished_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "radar_version_id": self.radar_version_id,
            "evaluation_cutoff": iso(self.evaluation_cutoff),
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "coverage_state": self.coverage_state,
            "attempt": self.attempt,
            "signal_count": self.signal_count,
            "match_count": self.match_count,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "started_at": iso(self.started_at),
            "finished_at": None if self.finished_at is None else iso(self.finished_at),
        }
