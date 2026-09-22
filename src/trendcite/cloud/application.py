"""Transport-independent application services for TrendCite Cloud Foundation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ..models import SourceStatus
from ..signal import SignalBrief
from .domain import (
    COVERAGE_FAILED,
    COVERAGE_OK,
    COVERAGE_SKIPPED,
    DECISION_MATCHED,
    DEFAULT_RELEVANCE_SERVICE,
    ROLE_OWNER,
    Coverage,
    Match,
    MatchEvaluation,
    Membership,
    Radar,
    RadarRun,
    RadarVersion,
    RelevanceEvaluation,
    RelevanceService,
    RelevanceTarget,
    RunSignal,
    StoredSignal,
    StoredSignalEvaluation,
    UsageEvent,
    Watchlist,
    WatchlistSignalMatch,
    WatchlistVersion,
    Workspace,
    summarize_coverage,
)
from .domain.usage import USAGE_MATCH_RECORDED, USAGE_RADAR_RUN, USAGE_SIGNAL_EVALUATED
from .errors import NotFoundError, TenantIsolationError, safe_error
from .matcher import DEFAULT_MATCHER, WatchlistMatcher
from .repositories import UnitOfWork, UnitOfWorkFactory


class SignalExecutionService(Protocol):
    """Cloud boundary around the existing Signal Engine."""

    def execute(self, radar: RadarVersion, *, evaluation_cutoff: datetime) -> ExecutionBatch: ...


@dataclass(frozen=True)
class ExecutionBatch:
    """One deterministic Signal Engine result plus explicit source coverage."""

    signals: tuple[SignalBrief, ...]
    source_status: tuple[SourceStatus, ...]


Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class CloudApplication:
    """Use-case layer. It owns orchestration, never Signal Engine truth."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        executor: SignalExecutionService,
        matcher: WatchlistMatcher = DEFAULT_MATCHER,
        relevance: RelevanceService = DEFAULT_RELEVANCE_SERVICE,
        clock: Clock = utc_now,
    ) -> None:
        self.uow_factory = uow_factory
        self.executor = executor
        self.matcher = matcher
        self.relevance = relevance
        self.clock = clock

    # ---------------------------------------------------------------- workspace

    def create_workspace(self, *, slug: str, name: str, owner_principal_id: str) -> Workspace:
        now = self.clock()
        workspace = Workspace.create(slug=slug, name=name, created_at=now)
        membership = Membership.create(
            workspace_id=workspace.workspace_id,
            principal_id=owner_principal_id,
            role=ROLE_OWNER,
            created_at=now,
        )
        with self.uow_factory() as uow:
            uow.workspaces.add(workspace)
            uow.memberships.add(membership)
            uow.commit()
        return workspace

    def add_member(self, *, workspace_id: str, principal_id: str, role: str) -> Membership:
        with self.uow_factory() as uow:
            if uow.workspaces.get(workspace_id) is None:
                raise NotFoundError("workspace not found")
            value = Membership.create(
                workspace_id=workspace_id,
                principal_id=principal_id,
                role=role,
                created_at=self.clock(),
            )
            uow.memberships.add(value)
            uow.commit()
            return value

    # ---------------------------------------------------------------- watchlists

    def create_watchlist(
        self,
        *,
        workspace_id: str,
        name: str,
        include_terms: Sequence[str],
        exclude_terms: Sequence[str] = (),
        match_mode: str = "any",
        entities: Sequence[str] = (),
        domains: Sequence[str] = (),
    ) -> tuple[Watchlist, WatchlistVersion]:
        now = self.clock()
        watchlist = Watchlist.create(workspace_id=workspace_id, name=name, created_at=now)
        version = WatchlistVersion.create(
            watchlist_id=watchlist.watchlist_id,
            workspace_id=workspace_id,
            version_number=1,
            include_terms=include_terms,
            exclude_terms=exclude_terms,
            match_mode=match_mode,
            created_at=now,
            entities=entities,
            domains=domains,
        )
        with self.uow_factory() as uow:
            if uow.workspaces.get(workspace_id) is None:
                raise NotFoundError("workspace not found")
            uow.watchlists.add(watchlist)
            uow.watchlists.add_version(version)
            uow.commit()
        return watchlist, version

    def update_watchlist(
        self,
        *,
        workspace_id: str,
        watchlist_id: str,
        include_terms: Sequence[str],
        exclude_terms: Sequence[str] = (),
        match_mode: str = "any",
        entities: Sequence[str] = (),
        domains: Sequence[str] = (),
    ) -> WatchlistVersion:
        with self.uow_factory() as uow:
            watchlist = uow.watchlists.get(workspace_id, watchlist_id)
            if watchlist is None:
                raise NotFoundError("watchlist not found in workspace")
            version = WatchlistVersion.create(
                watchlist_id=watchlist.watchlist_id,
                workspace_id=workspace_id,
                version_number=uow.watchlists.next_version_number(workspace_id, watchlist_id),
                include_terms=include_terms,
                exclude_terms=exclude_terms,
                match_mode=match_mode,
                created_at=self.clock(),
                entities=entities,
                domains=domains,
            )
            uow.watchlists.add_version(version)
            uow.commit()
            return version

    # ---------------------------------------------------------------- radars

    def create_radar(
        self,
        *,
        workspace_id: str,
        name: str,
        watchlist_ids: Sequence[str],
        sources: Sequence[str],
        niche: Sequence[str] = (),
        top: int = 5,
    ) -> tuple[Radar, RadarVersion]:
        now = self.clock()
        with self.uow_factory() as uow:
            if uow.workspaces.get(workspace_id) is None:
                raise NotFoundError("workspace not found")
            pinned = self._resolve_watchlist_versions(uow, workspace_id, watchlist_ids)
            radar = Radar.create(workspace_id=workspace_id, name=name, created_at=now)
            version = RadarVersion.create(
                radar_id=radar.radar_id,
                workspace_id=workspace_id,
                version_number=1,
                watchlist_version_ids=[v.version_id for v in pinned],
                sources=sources,
                niche=niche,
                top=top,
                created_at=now,
            )
            uow.radars.add(radar)
            uow.radars.add_version(version)
            uow.commit()
            return radar, version

    def update_radar(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        watchlist_ids: Sequence[str],
        sources: Sequence[str],
        niche: Sequence[str] = (),
        top: int = 5,
    ) -> RadarVersion:
        with self.uow_factory() as uow:
            radar = uow.radars.get(workspace_id, radar_id)
            if radar is None:
                raise NotFoundError("radar not found in workspace")
            pinned = self._resolve_watchlist_versions(uow, workspace_id, watchlist_ids)
            version = RadarVersion.create(
                radar_id=radar_id,
                workspace_id=workspace_id,
                version_number=uow.radars.next_version_number(workspace_id, radar_id),
                watchlist_version_ids=[v.version_id for v in pinned],
                sources=sources,
                niche=niche,
                top=top,
                created_at=self.clock(),
            )
            uow.radars.add_version(version)
            uow.commit()
            return version

    @staticmethod
    def _resolve_watchlist_versions(
        uow: UnitOfWork, workspace_id: str, watchlist_ids: Sequence[str]
    ) -> list[WatchlistVersion]:
        # UnitOfWork is a Protocol; keeping the helper structurally typed avoids
        # exposing persistence classes to this module.
        repo = uow.watchlists
        result: list[WatchlistVersion] = []
        for watchlist_id in watchlist_ids:
            watchlist = repo.get(workspace_id, watchlist_id)
            if watchlist is None:
                raise TenantIsolationError("watchlist is not owned by this workspace")
            version = repo.latest_version(workspace_id, watchlist_id)
            if version is None:
                raise NotFoundError("watchlist has no version")
            result.append(version)
        if not result:
            raise NotFoundError("radar needs at least one watchlist")
        return result

    # ---------------------------------------------------------------- runs

    def create_run(
        self, *, workspace_id: str, radar_id: str, evaluation_cutoff: datetime
    ) -> RadarRun:
        with self.uow_factory() as uow:
            radar = uow.radars.get(workspace_id, radar_id)
            if radar is None:
                raise NotFoundError("radar not found in workspace")
            version = uow.radars.latest_version(workspace_id, radar_id)
            if version is None:
                raise NotFoundError("radar has no version")
            candidate = RadarRun.create(
                workspace_id=workspace_id,
                radar_id=radar_id,
                radar_version_id=version.version_id,
                evaluation_cutoff=evaluation_cutoff,
                started_at=self.clock(),
            )
            existing = uow.runs.by_idempotency_key(workspace_id, candidate.idempotency_key)
            if existing is not None:
                return existing
            uow.runs.add(candidate)
            uow.commit()
            return candidate

    def run_radar(
        self, *, workspace_id: str, radar_id: str, evaluation_cutoff: datetime
    ) -> RadarRun:
        run = self.create_run(
            workspace_id=workspace_id,
            radar_id=radar_id,
            evaluation_cutoff=evaluation_cutoff,
        )
        if run.status == "succeeded":
            return run

        if run.status == "failed":
            with self.uow_factory() as uow:
                current = uow.runs.get(workspace_id, run.run_id)
                assert current is not None
                run = current.retrying(started_at=self.clock())
                uow.runs.update(run)
                uow.commit()

        try:
            return self._execute_run(run)
        except Exception as exc:
            code, detail = safe_error(exc)
            with self.uow_factory() as uow:
                current = uow.runs.get(workspace_id, run.run_id)
                if current is not None and current.status != "succeeded":
                    failed = current.failed(code=code, detail=detail, finished_at=self.clock())
                    uow.runs.update(failed)
                    uow.commit()
                    return failed
            raise

    def _execute_run(self, run: RadarRun) -> RadarRun:
        with self.uow_factory() as uow:
            version = uow.radars.get_version(run.workspace_id, run.radar_version_id)
            if version is None:
                raise NotFoundError("pinned radar version not found")
            watchlists = [
                self._require_watchlist_version(uow, run.workspace_id, version_id)
                for version_id in version.watchlist_version_ids
            ]

        batch = self.executor.execute(version, evaluation_cutoff=run.evaluation_cutoff)
        coverage = self._coverage_for(run, version, batch.source_status)
        match_count = 0

        with self.uow_factory() as uow:
            for brief in batch.signals:
                signal = StoredSignal.of(brief.signal)
                evaluation = StoredSignalEvaluation.of(brief.snapshot)
                uow.signals.upsert(signal)
                uow.signals.record_evaluation(evaluation)

                strongest = 0.0
                target = RelevanceTarget.of(brief)
                for watchlist in watchlists:
                    outcome = self.relevance.evaluate_one(watchlist, target)
                    relevance_evaluation = RelevanceEvaluation.create(
                        workspace_id=run.workspace_id,
                        watchlist=watchlist,
                        target=target,
                        outcome=outcome,
                        evaluated_at=self.clock(),
                        radar_id=run.radar_id,
                        radar_run_id=run.run_id,
                    )
                    uow.relevance.record_evaluation(relevance_evaluation)
                    uow.relevance.link_run(relevance_evaluation.evaluation_id, run.run_id)

                    positive = tuple(
                        reason.value for reason in outcome.reasons if reason.polarity == "positive"
                    )
                    negative = tuple(
                        reason.value for reason in outcome.reasons if reason.polarity == "negative"
                    )
                    fields = tuple(dict.fromkeys(reason.field for reason in outcome.reasons))
                    decision = MatchEvaluation.create(
                        workspace_id=run.workspace_id,
                        radar_id=run.radar_id,
                        run_id=run.run_id,
                        watchlist_version_id=watchlist.version_id,
                        signal_id=signal.signal_id,
                        decision=outcome.decision,
                        strength=round(outcome.score / 100.0, 4),
                        matched_terms=positive,
                        excluded_terms=negative,
                        matched_fields=fields,
                        explanation=(
                            f"relevance={outcome.score:.1f}/100 "
                            f"band={outcome.band} confidence={outcome.confidence}"
                        ),
                        matcher_version=outcome.matcher_version,
                        evaluated_at=relevance_evaluation.evaluated_at,
                    )
                    uow.matches.record_evaluation(decision)

                    current_watchlist_match = uow.relevance.get_current(
                        run.workspace_id,
                        watchlist.watchlist_id,
                        signal.signal_id,
                    )
                    if decision.decision != DECISION_MATCHED:
                        if (
                            current_watchlist_match is not None
                            and current_watchlist_match.status == "active"
                        ):
                            stale = WatchlistSignalMatch(
                                current_watchlist_match.match_id,
                                current_watchlist_match.workspace_id,
                                current_watchlist_match.watchlist_id,
                                current_watchlist_match.signal_id,
                                "stale",
                                outcome.score,
                                outcome.band,
                                outcome.confidence,
                                relevance_evaluation.evaluation_id,
                                current_watchlist_match.first_matched_at,
                                self.clock(),
                            )
                            uow.relevance.upsert_current(stale)
                        continue

                    watchlist_match = WatchlistSignalMatch.from_evaluation(
                        relevance_evaluation,
                        matched_at=self.clock(),
                        existing=current_watchlist_match,
                    )
                    uow.relevance.upsert_current(watchlist_match)
                    strength = round(outcome.score / 100.0, 4)
                    strongest = max(strongest, strength)

                    current = uow.matches.get(
                        run.workspace_id,
                        run.radar_id,
                        signal.signal_id,
                    )
                    if current is None:
                        current = Match.create(
                            workspace_id=run.workspace_id,
                            radar_id=run.radar_id,
                            signal_id=signal.signal_id,
                            strength=strength,
                            watchlist_version_id=watchlist.version_id,
                            matched_at=self.clock(),
                            run_id=run.run_id,
                            matcher_version=outcome.matcher_version,
                        )
                    else:
                        current = current.reaffirmed(
                            strength=max(current.strength, strength),
                            watchlist_version_id=watchlist.version_id,
                            matched_at=self.clock(),
                            run_id=run.run_id,
                        )
                    uow.matches.upsert(current)

                if strongest > 0:
                    match_count += 1
                uow.signals.link_run(
                    RunSignal.create(
                        run_id=run.run_id,
                        workspace_id=run.workspace_id,
                        signal_id=signal.signal_id,
                        snapshot_id=evaluation.snapshot_id,
                        relevance=strongest,
                    )
                )

            uow.coverage.replace_for_run(run.workspace_id, run.run_id, coverage)
            finished = run.succeeded(
                coverage_state=summarize_coverage(coverage),
                signal_count=len(batch.signals),
                match_count=match_count,
                finished_at=self.clock(),
            )
            uow.runs.update(finished)
            self._record_usage(uow, finished)
            uow.commit()
            return finished

    @staticmethod
    def _require_watchlist_version(
        uow: UnitOfWork, workspace_id: str, version_id: str
    ) -> WatchlistVersion:
        version = uow.watchlists.get_version(workspace_id, version_id)
        if version is None:
            raise TenantIsolationError("pinned watchlist version is not owned by workspace")
        return version

    def _coverage_for(
        self,
        run: RadarRun,
        version: RadarVersion,
        source_status: Sequence[SourceStatus],
    ) -> list[Coverage]:
        by_source = {s.source: s for s in source_status}
        rows: list[Coverage] = []
        for source in version.sources:
            status = by_source.get(source)
            if status is None:
                state, count, detail = COVERAGE_SKIPPED, 0, "source not returned by executor"
            elif status.ok:
                state, count, detail = COVERAGE_OK, status.items, status.message
            else:
                state, count, detail = COVERAGE_FAILED, 0, status.message
            rows.append(
                Coverage.create(
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    source=source,
                    state=state,
                    item_count=count,
                    detail=detail,
                    observed_at=self.clock(),
                )
            )
        return rows

    def _record_usage(self, uow: UnitOfWork, run: RadarRun) -> None:
        repo = uow.usage
        now = self.clock()
        for kind, quantity in (
            (USAGE_RADAR_RUN, 1),
            (USAGE_SIGNAL_EVALUATED, run.signal_count),
            (USAGE_MATCH_RECORDED, run.match_count),
        ):
            repo.record(
                UsageEvent.create(
                    workspace_id=run.workspace_id,
                    kind=kind,
                    quantity=quantity,
                    occurred_at=now,
                    run_id=run.run_id,
                )
            )
