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

from .domain.matches import Match, MatchEvaluation
from .domain.radar import Coverage, Radar, RadarRun, RadarVersion
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
