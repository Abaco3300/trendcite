"""Repository and UnitOfWork protocols: the only shape persistence is allowed to have.

Every method that reads or writes tenant-scoped data takes ``workspace_id`` as its
first argument. That is not a convention, it is the tenant boundary: a repository
method with no workspace parameter cannot leak across tenants, and one with it always
filters on it. There is no ``get_by_id(id)`` for tenant-scoped rows anywhere in this
file, because such a method is exactly how cross-tenant reads happen by accident.

Signals and their evaluations are the deliberate exception -- they are globally
canonical public-source records, so their repository methods take no workspace. The
tenant-scoped view of a signal is :class:`~trendcite.cloud.domain.signals.RunSignal`,
which does take one.

Services depend on these protocols only. :mod:`trendcite.cloud.db.sqlite` is one
implementation; a PostgreSQL one is a second implementation, not a rewrite.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, runtime_checkable

from .domain.alerts import (
    Alert,
    AlertBaseline,
    AlertCandidate,
    AlertPolicy,
    DeliveryAttempt,
)
from .domain.digests import Digest, DigestItem
from .domain.matches import Match, MatchEvaluation
from .domain.radar import Coverage, Radar, RadarRun, RadarVersion
from .domain.relevance import RelevanceEvaluation, WatchlistSignalMatch
from .domain.scheduling import RadarSchedule, ScheduleTick
from .domain.signals import RunSignal, StoredSignal, StoredSignalEvaluation
from .domain.usage import UsageEvent
from .domain.watchlist import Watchlist, WatchlistVersion
from .domain.workspace import Membership, Workspace


class WorkspaceRepository(Protocol):
    """Workspaces are the tenant roots, so this is the one repository without a scope."""

    def add(self, workspace: Workspace) -> None:
        """Insert a workspace. Raises ConflictError if the slug is taken."""

    def get(self, workspace_id: str) -> Workspace | None: ...

    def by_slug(self, slug: str) -> Workspace | None: ...

    def list_all(self) -> list[Workspace]:
        """Every workspace, oldest first. Administrative/diagnostic use only."""


class MembershipRepository(Protocol):
    def add(self, membership: Membership) -> None: ...

    def get(self, workspace_id: str, principal_id: str) -> Membership | None: ...

    def list_for_workspace(self, workspace_id: str) -> list[Membership]: ...


class WatchlistRepository(Protocol):
    def add(self, watchlist: Watchlist) -> None: ...

    def get(self, workspace_id: str, watchlist_id: str) -> Watchlist | None: ...

    def by_name(self, workspace_id: str, name: str) -> Watchlist | None: ...

    def list_for_workspace(self, workspace_id: str) -> list[Watchlist]: ...

    def add_version(self, version: WatchlistVersion) -> None:
        """Append an immutable version. Never updates an existing one."""

    def get_version(self, workspace_id: str, version_id: str) -> WatchlistVersion | None: ...

    def versions(self, workspace_id: str, watchlist_id: str) -> list[WatchlistVersion]:
        """Every version, lowest version number first."""

    def latest_version(self, workspace_id: str, watchlist_id: str) -> WatchlistVersion | None: ...

    def next_version_number(self, workspace_id: str, watchlist_id: str) -> int: ...


class RadarRepository(Protocol):
    def add(self, radar: Radar) -> None: ...

    def get(self, workspace_id: str, radar_id: str) -> Radar | None: ...

    def by_name(self, workspace_id: str, name: str) -> Radar | None: ...

    def list_for_workspace(self, workspace_id: str) -> list[Radar]: ...

    def add_version(self, version: RadarVersion) -> None: ...

    def get_version(self, workspace_id: str, version_id: str) -> RadarVersion | None: ...

    def versions(self, workspace_id: str, radar_id: str) -> list[RadarVersion]: ...

    def latest_version(self, workspace_id: str, radar_id: str) -> RadarVersion | None: ...

    def next_version_number(self, workspace_id: str, radar_id: str) -> int: ...


class RadarRunRepository(Protocol):
    def add(self, run: RadarRun) -> None:
        """Insert a run. The database rejects a duplicate idempotency key."""

    def update(self, run: RadarRun) -> None:
        """Persist a status transition. Never changes identity or pinning."""

    def get(self, workspace_id: str, run_id: str) -> RadarRun | None: ...

    def by_idempotency_key(self, workspace_id: str, key: str) -> RadarRun | None: ...

    def list_for_radar(self, workspace_id: str, radar_id: str) -> list[RadarRun]:
        """Runs for one radar, most recently started first."""


class CoverageRepository(Protocol):
    def replace_for_run(self, workspace_id: str, run_id: str, rows: Sequence[Coverage]) -> None:
        """Set this run's coverage.

        Replacement rather than append: a retried attempt observed the sources again,
        and two contradictory coverage rows for one source in one run would be a
        worse record than the latest attempt's.
        """

    def list_for_run(self, workspace_id: str, run_id: str) -> list[Coverage]: ...


class SignalRepository(Protocol):
    """Globally canonical signals. Deliberately *not* workspace-scoped."""

    def upsert(self, signal: StoredSignal) -> None:
        """Insert, or widen the first/last-seen window of an existing signal."""

    def get(self, signal_id: str) -> StoredSignal | None: ...

    def record_evaluation(self, evaluation: StoredSignalEvaluation) -> None:
        """Append-oriented: re-recording a content-addressed evaluation is a no-op."""

    def evaluations(self, signal_id: str) -> list[StoredSignalEvaluation]:
        """Evaluation history for one signal, oldest first."""

    def link_run(self, link: RunSignal) -> None:
        """Record that a tenant's run saw this signal, with that tenant's relevance."""

    def run_signals(self, workspace_id: str, run_id: str) -> list[RunSignal]: ...


class MatchRepository(Protocol):
    def upsert(self, match: Match) -> None:
        """Write the current state of one (workspace, radar, signal)."""

    def get(self, workspace_id: str, radar_id: str, signal_id: str) -> Match | None: ...

    def list_for_radar(
        self, workspace_id: str, radar_id: str, *, status: str | None = None
    ) -> list[Match]: ...

    def record_evaluation(self, evaluation: MatchEvaluation) -> None:
        """Append one immutable decision. Re-recording the same decision is a no-op."""

    def evaluations_for_run(self, workspace_id: str, run_id: str) -> list[MatchEvaluation]: ...

    def evaluations_for_signal(
        self, workspace_id: str, radar_id: str, signal_id: str
    ) -> list[MatchEvaluation]:
        """The full audit trail for one signal on one radar, oldest first."""


class RelevanceRepository(Protocol):
    def record_evaluation(self, evaluation: RelevanceEvaluation) -> bool: ...

    def link_run(self, evaluation_id: str, radar_run_id: str) -> None: ...

    def get_evaluation(
        self, workspace_id: str, evaluation_id: str
    ) -> RelevanceEvaluation | None: ...

    def evaluations_for_run(
        self, workspace_id: str, radar_run_id: str
    ) -> list[RelevanceEvaluation]: ...

    def evaluations_for_watchlist_signal(
        self, workspace_id: str, watchlist_id: str, signal_id: str
    ) -> list[RelevanceEvaluation]: ...

    def upsert_current(self, match: WatchlistSignalMatch) -> None: ...

    def get_current(
        self, workspace_id: str, watchlist_id: str, signal_id: str
    ) -> WatchlistSignalMatch | None: ...

    def list_for_watchlist(
        self, workspace_id: str, watchlist_id: str
    ) -> list[WatchlistSignalMatch]: ...


class AlertRepository(Protocol):
    """Alerting state. Four concerns, deliberately four sets of methods.

    Candidates, alerts, baselines and attempts are never updated through one another:
    there is no ``mark_delivered`` that also moves a baseline, because a method that
    does both is a method that will one day move a baseline on a failed send.
    """

    def upsert_policy(self, policy: AlertPolicy) -> None: ...

    def get_policy(self, workspace_id: str, radar_id: str) -> AlertPolicy | None:
        """The stored policy, or ``None`` when the radar has never been configured."""

    def add_candidate(self, candidate: AlertCandidate) -> bool:
        """Persist a judged candidate, returning ``False`` when it already existed.

        ``False`` *is* the duplicate verdict: the same event reconsidered writes
        nothing and keeps the reason it was first decided with.
        """

    def get_candidate(self, workspace_id: str, candidate_id: str) -> AlertCandidate | None: ...

    def candidates_for_run(self, workspace_id: str, run_id: str) -> list[AlertCandidate]: ...

    def candidates_in_window(
        self, workspace_id: str, radar_id: str, start: str, end: str
    ) -> list[AlertCandidate]:
        """Candidates observed in ``[start, end)`` for one radar, oldest first."""

    def add_alert(self, alert: Alert) -> bool:
        """Insert an alert, returning ``False`` when its candidate already has one."""

    def update_alert(self, alert: Alert) -> None:
        """Persist a delivery-state transition. Never changes what the alert says."""

    def get_alert(self, workspace_id: str, alert_id: str) -> Alert | None: ...

    def alert_for_candidate(self, workspace_id: str, candidate_id: str) -> Alert | None: ...

    def list_alerts(self, workspace_id: str, radar_id: str) -> list[Alert]: ...

    def upsert_baseline(self, baseline: AlertBaseline) -> None:
        """Move the last-delivered state. Only a *successful* delivery may call this."""

    def get_baseline(
        self, workspace_id: str, watchlist_id: str, signal_id: str
    ) -> AlertBaseline | None: ...

    def record_attempt(self, attempt: DeliveryAttempt) -> bool:
        """Append one attempt, returning ``False`` when that attempt number exists."""

    def attempts_for(
        self, workspace_id: str, target_kind: str, target_id: str
    ) -> list[DeliveryAttempt]:
        """Every attempt against one target, in attempt order."""


class DigestRepository(Protocol):
    def upsert(self, digest: Digest) -> None:
        """Write or rebuild one day's digest. Rebuilding is not appending."""

    def get(self, workspace_id: str, digest_id: str) -> Digest | None: ...

    def by_date(self, workspace_id: str, radar_id: str, digest_date: str) -> Digest | None: ...

    def replace_items(self, workspace_id: str, digest_id: str, items: Sequence[DigestItem]) -> None:
        """Set this digest's items.

        Replacement rather than append, for the same reason coverage is replaced: a
        rebuilt day is a restatement of that day, and two contradictory rankings for
        one digest would be a worse record than the latest one.
        """

    def items(self, workspace_id: str, digest_id: str) -> list[DigestItem]:
        """This digest's items, best-ranked first."""


class ScheduleRepository(Protocol):
    """Schedules and their ticks.

    One method here is unlike every other method in this file: :meth:`claim_tick` is a
    *conditional* write rather than a read followed by a write. That is deliberate and
    it is the whole concurrency story. Two workers that read a pending tick would both
    see it as claimable; only a single statement whose WHERE clause restates the
    precondition can make exactly one of them win. Implementations must not reduce it
    to a get-then-update.
    """

    def upsert_schedule(self, schedule: RadarSchedule) -> None:
        """Write or edit one radar's schedule. Never touches its ticks."""

    def get_schedule(self, workspace_id: str, schedule_id: str) -> RadarSchedule | None: ...

    def schedule_for_radar(self, workspace_id: str, radar_id: str) -> RadarSchedule | None: ...

    def list_schedules(self, workspace_id: str) -> list[RadarSchedule]:
        """Every schedule in one workspace, oldest first."""

    def list_enabled_schedules(self) -> list[RadarSchedule]:
        """Every enabled schedule in every workspace, oldest first.

        The one cross-tenant read in this file, and the same deliberate exception
        :meth:`WorkspaceRepository.list_all` is: a worker plane has to sweep all
        tenants to find due work. Callers that only need one tenant's schedules must
        use :meth:`list_schedules`, which cannot leak.
        """

    def add_tick(self, tick: ScheduleTick) -> bool:
        """Insert a planned tick, returning ``False`` when that boundary already has one.

        ``False`` is the idempotency verdict, not an error: re-planning a boundary is
        expected and must write nothing.
        """

    def get_tick(self, workspace_id: str, tick_id: str) -> ScheduleTick | None: ...

    def tick_by_idempotency_key(self, workspace_id: str, key: str) -> ScheduleTick | None: ...

    def ticks_for_schedule(self, workspace_id: str, schedule_id: str) -> list[ScheduleTick]:
        """One schedule's ticks, oldest cutoff first."""

    def claimable_ticks(
        self, workspace_id: str, *, now: str, limit: int = 100
    ) -> list[ScheduleTick]:
        """Ticks a worker could attempt as of ``now``, oldest cutoff first.

        Advisory. A tick listed here may be claimed by another worker before this
        caller gets to it; :meth:`claim_tick` is what settles that.
        """

    def claim_tick(
        self,
        workspace_id: str,
        tick_id: str,
        *,
        owner: str,
        now: str,
        lease_expires_at: str,
    ) -> bool:
        """Atomically take a claimable tick, returning whether this caller won it.

        Must be one conditional statement. The conditions are the contract: pending
        work is claimable, failed work is claimable while attempts remain, running work
        is claimable only once its lease has expired, and settled work is never
        claimable.
        """

    def settle_tick(self, tick: ScheduleTick, *, expected_owner: str) -> bool:
        """Persist a terminal transition, returning ``False`` if the lease moved on.

        ``expected_owner`` is what stops a worker that was presumed dead from
        overwriting the verdict of the worker that took over from it.
        """


class UsageRepository(Protocol):
    def record(self, event: UsageEvent) -> bool:
        """Record an event, returning ``False`` when it was already metered."""

    def list_for_workspace(self, workspace_id: str) -> list[UsageEvent]: ...

    def total(self, workspace_id: str, kind: str) -> int:
        """Summed quantity for one usage kind in one workspace."""


@runtime_checkable
class UnitOfWork(Protocol):
    """One transaction, and the repositories that participate in it.

    Everything a service does inside a ``with`` block either lands together or not at
    all. That is what makes a failed run leave no half-written matches behind, and it
    is why retrying a failed run cannot duplicate logical outputs: there was nothing
    to duplicate.

    Leaving the block without calling :meth:`commit` rolls back. Committing is always
    an explicit act.
    """

    workspaces: WorkspaceRepository
    memberships: MembershipRepository
    watchlists: WatchlistRepository
    radars: RadarRepository
    runs: RadarRunRepository
    coverage: CoverageRepository
    signals: SignalRepository
    matches: MatchRepository
    relevance: RelevanceRepository
    alerts: AlertRepository
    digests: DigestRepository
    schedules: ScheduleRepository
    usage: UsageRepository

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class UnitOfWorkFactory(Protocol):
    """Opens a fresh unit of work. Services hold one of these, never a connection."""

    def __call__(self) -> UnitOfWork: ...
