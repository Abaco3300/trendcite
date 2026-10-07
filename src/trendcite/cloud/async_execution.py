"""Async Signal Engine execution and atomic Cloud persistence.

This is the concrete AsyncExecutionPipeline used by the Cloudflare scheduler path.
Domain scoring/matching/materiality remain the canonical pure Python implementations;
only I/O boundaries are async.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from ..models import SourceStatus
from .alert_runtime import counterevidence_from
from .application import ExecutionBatch, LinkedContentEnrichment
from .domain import (
    COVERAGE_FAILED,
    COVERAGE_OK,
    COVERAGE_SKIPPED,
    DECISION_MATCHED,
    DEFAULT_RELEVANCE_SERVICE,
    RUN_SUCCEEDED,
    AlertBaseline,
    AlertCandidate,
    AlertPolicy,
    Coverage,
    Match,
    MatchEvaluation,
    RadarRun,
    RadarVersion,
    RelevanceEvaluation,
    RelevanceService,
    RelevanceTarget,
    RunSignal,
    SignalState,
    StoredSignal,
    StoredSignalEvaluation,
    UsageEvent,
    WatchlistSignalMatch,
    WatchlistVersion,
    summarize_coverage,
)
from .domain.alerts import (
    DEFAULT_MATERIALITY_SERVICE,
    REASON_BELOW_MATERIALITY,
    REASON_BELOW_RELEVANCE,
    REASON_COOLDOWN,
    REASON_DELIVERY_DISABLED,
    REASON_DISMISSED,
    REASON_MUTED,
    REASON_QUALIFIED,
    VELOCITY_COMPONENT,
    MaterialityEvaluation,
    MaterialityService,
    materiality_at_least,
)
from .domain.usage import (
    USAGE_ALERT_CANDIDATE,
    USAGE_ALERT_SUPPRESSED,
    USAGE_MATCH_RECORDED,
    USAGE_RADAR_RUN,
    USAGE_SIGNAL_EVALUATED,
    entity_dedupe_key,
)
from .errors import NotFoundError, TenantIsolationError


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class AsyncSignalExecutionService(Protocol):
    async def execute(
        self,
        radar: RadarVersion,
        *,
        evaluation_cutoff: datetime,
    ) -> ExecutionBatch: ...


class AsyncExecutionStore(Protocol):
    async def get_radar_version(
        self,
        workspace_id: str,
        version_id: str,
    ) -> RadarVersion | None: ...

    async def get_watchlist_version(
        self,
        workspace_id: str,
        version_id: str,
    ) -> WatchlistVersion | None: ...

    async def get_watchlist_signal_match(
        self,
        workspace_id: str,
        watchlist_id: str,
        signal_id: str,
    ) -> WatchlistSignalMatch | None: ...

    async def get_match(
        self,
        workspace_id: str,
        radar_id: str,
        signal_id: str,
    ) -> Match | None: ...

    async def get_alert_policy(
        self,
        workspace_id: str,
        radar_id: str,
    ) -> AlertPolicy | None: ...

    async def get_alert_baseline(
        self,
        workspace_id: str,
        watchlist_id: str,
        signal_id: str,
    ) -> AlertBaseline | None: ...

    async def persist_execution(self, bundle: ExecutionPersistenceBundle) -> RadarRun: ...


@dataclass(frozen=True)
class ExecutionPersistenceBundle:
    run: RadarRun
    signals: tuple[StoredSignal, ...]
    signal_evaluations: tuple[StoredSignalEvaluation, ...]
    relevance_evaluations: tuple[RelevanceEvaluation, ...]
    watchlist_matches: tuple[WatchlistSignalMatch, ...]
    match_evaluations: tuple[MatchEvaluation, ...]
    matches: tuple[Match, ...]
    run_signals: tuple[RunSignal, ...]
    coverage: tuple[Coverage, ...]
    usage_events: tuple[UsageEvent, ...]
    alert_candidates: tuple[AlertCandidate, ...]
    linked_content: tuple[LinkedContentEnrichment, ...] = ()


class AsyncExecutionPipelineImpl:
    """Execute one pinned radar and atomically persist its durable output."""

    def __init__(
        self,
        store: AsyncExecutionStore,
        executor: AsyncSignalExecutionService,
        *,
        relevance: RelevanceService = DEFAULT_RELEVANCE_SERVICE,
        materiality: MaterialityService = DEFAULT_MATERIALITY_SERVICE,
    ) -> None:
        self.store = store
        self.executor = executor
        self.relevance = relevance
        self.materiality = materiality

    async def execute_and_persist(self, run: RadarRun) -> RadarRun:
        version = await self.store.get_radar_version(run.workspace_id, run.radar_version_id)
        if version is None:
            raise NotFoundError("pinned radar version not found")

        watchlists: list[WatchlistVersion] = []
        for version_id in version.watchlist_version_ids:
            watchlist = await self.store.get_watchlist_version(run.workspace_id, version_id)
            if watchlist is None:
                raise TenantIsolationError("pinned watchlist version is not owned by workspace")
            watchlists.append(watchlist)

        batch = await self.executor.execute(
            version,
            evaluation_cutoff=run.evaluation_cutoff,
        )
        now = utc_now()
        coverage = _coverage_for(run, version, batch.source_status, now=now)
        coverage_state = summarize_coverage(coverage)
        policy = await self.store.get_alert_policy(run.workspace_id, run.radar_id)
        if policy is None:
            policy = AlertPolicy.default_for(
                workspace_id=run.workspace_id,
                radar_id=run.radar_id,
                updated_at=now,
            )

        signals: list[StoredSignal] = []
        signal_evaluations: list[StoredSignalEvaluation] = []
        relevance_evaluations: list[RelevanceEvaluation] = []
        watchlist_matches: list[WatchlistSignalMatch] = []
        match_evaluations: list[MatchEvaluation] = []
        matches: list[Match] = []
        run_signals: list[RunSignal] = []
        candidates: list[AlertCandidate] = []
        match_count = 0
        radar_match_state: dict[str, Match | None] = {}

        for brief in batch.signals:
            signal = StoredSignal.of(brief.signal)
            snapshot = StoredSignalEvaluation.of(brief.snapshot)
            signals.append(signal)
            signal_evaluations.append(snapshot)

            strongest = 0.0
            target = RelevanceTarget.of(brief)
            for watchlist in watchlists:
                outcome = self.relevance.evaluate_one(watchlist, target)
                relevance_evaluation = RelevanceEvaluation.create(
                    workspace_id=run.workspace_id,
                    watchlist=watchlist,
                    target=target,
                    outcome=outcome,
                    evaluated_at=now,
                    radar_id=run.radar_id,
                    radar_run_id=run.run_id,
                )
                relevance_evaluations.append(relevance_evaluation)

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
                    evaluated_at=now,
                )
                match_evaluations.append(decision)

                existing_watchlist_match = await self.store.get_watchlist_signal_match(
                    run.workspace_id,
                    watchlist.watchlist_id,
                    signal.signal_id,
                )
                if decision.decision != DECISION_MATCHED:
                    if (
                        existing_watchlist_match is not None
                        and existing_watchlist_match.status == "active"
                    ):
                        watchlist_matches.append(
                            WatchlistSignalMatch(
                                existing_watchlist_match.match_id,
                                existing_watchlist_match.workspace_id,
                                existing_watchlist_match.watchlist_id,
                                existing_watchlist_match.signal_id,
                                "stale",
                                outcome.score,
                                outcome.band,
                                outcome.confidence,
                                relevance_evaluation.evaluation_id,
                                existing_watchlist_match.first_matched_at,
                                now,
                            )
                        )
                    continue

                watchlist_match = WatchlistSignalMatch.from_evaluation(
                    relevance_evaluation,
                    matched_at=now,
                    existing=existing_watchlist_match,
                )
                watchlist_matches.append(watchlist_match)
                strength = round(outcome.score / 100.0, 4)
                strongest = max(strongest, strength)

                if signal.signal_id not in radar_match_state:
                    radar_match_state[signal.signal_id] = await self.store.get_match(
                        run.workspace_id,
                        run.radar_id,
                        signal.signal_id,
                    )
                existing_match = radar_match_state[signal.signal_id]
                if existing_match is None:
                    current_match = Match.create(
                        workspace_id=run.workspace_id,
                        radar_id=run.radar_id,
                        signal_id=signal.signal_id,
                        strength=strength,
                        watchlist_version_id=watchlist.version_id,
                        matched_at=now,
                        run_id=run.run_id,
                        matcher_version=outcome.matcher_version,
                    )
                else:
                    current_match = existing_match.reaffirmed(
                        strength=max(existing_match.strength, strength),
                        watchlist_version_id=watchlist.version_id,
                        matched_at=now,
                        run_id=run.run_id,
                    )
                radar_match_state[signal.signal_id] = current_match
                matches.append(current_match)

                baseline = await self.store.get_alert_baseline(
                    run.workspace_id,
                    watchlist.watchlist_id,
                    signal.signal_id,
                )
                state = SignalState.create(
                    signal_id=signal.signal_id,
                    snapshot_id=snapshot.snapshot_id,
                    signal_score=snapshot.score,
                    relevance_score=relevance_evaluation.score,
                    lifecycle_state=snapshot.state,
                    velocity=snapshot.component_values.get(VELOCITY_COMPONENT),
                    source_count=snapshot.source_count,
                    counterevidence=counterevidence_from(snapshot),
                    observed_at=snapshot.captured_at,
                )
                materiality = self.materiality.evaluate(
                    state,
                    baseline,
                    coverage_state=coverage_state,
                )
                reason = _qualification_reason(
                    policy=policy,
                    match_status=watchlist_match.status,
                    state=state,
                    materiality=materiality,
                    baseline=baseline,
                    now=now,
                )
                candidates.append(
                    AlertCandidate.create(
                        workspace_id=run.workspace_id,
                        radar_id=run.radar_id,
                        watchlist_id=watchlist.watchlist_id,
                        run_id=run.run_id,
                        label=signal.label,
                        state=state,
                        evaluation=materiality,
                        reason=reason,
                        created_at=now,
                    )
                )

            if strongest > 0:
                match_count += 1
            run_signals.append(
                RunSignal.create(
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    signal_id=signal.signal_id,
                    snapshot_id=snapshot.snapshot_id,
                    relevance=strongest,
                )
            )

        finished = run.succeeded(
            coverage_state=coverage_state,
            signal_count=len(batch.signals),
            match_count=match_count,
            finished_at=now,
        )
        usage = _usage_events(finished, candidates, now=now)
        bundle = ExecutionPersistenceBundle(
            run=finished,
            signals=tuple(signals),
            signal_evaluations=tuple(signal_evaluations),
            relevance_evaluations=tuple(relevance_evaluations),
            watchlist_matches=_dedupe_by_id(watchlist_matches, "match_id"),
            match_evaluations=tuple(match_evaluations),
            matches=_dedupe_by_id(matches, "match_id"),
            run_signals=tuple(run_signals),
            coverage=tuple(coverage),
            usage_events=usage,
            alert_candidates=_dedupe_by_id(candidates, "candidate_id"),
            linked_content=batch.linked_content,
        )
        persisted = await self.store.persist_execution(bundle)
        if persisted.run_id != run.run_id or persisted.status != RUN_SUCCEEDED:
            raise RuntimeError("execution persistence did not return the succeeded logical run")
        return persisted


def _coverage_for(
    run: RadarRun,
    version: RadarVersion,
    source_status: tuple[SourceStatus, ...],
    *,
    now: datetime,
) -> list[Coverage]:
    by_source = {status.source: status for status in source_status}
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
                observed_at=now,
            )
        )
    return rows


def _qualification_reason(
    *,
    policy: AlertPolicy,
    match_status: str,
    state: SignalState,
    materiality: MaterialityEvaluation,
    baseline: AlertBaseline | None,
    now: datetime,
) -> str:
    evaluation = materiality
    if not policy.enabled or not policy.immediate_alerts:
        return REASON_DELIVERY_DISABLED
    if match_status == "muted":
        return REASON_MUTED
    if match_status == "dismissed":
        return REASON_DISMISSED
    if state.relevance_score < policy.min_relevance:
        return REASON_BELOW_RELEVANCE
    if not materiality_at_least(evaluation.level, policy.min_materiality):
        return REASON_BELOW_MATERIALITY
    if baseline is not None and now < baseline.delivered_at + policy.cooldown:
        return REASON_COOLDOWN
    return REASON_QUALIFIED


def _usage_events(
    run: RadarRun,
    candidates: list[AlertCandidate],
    *,
    now: datetime,
) -> tuple[UsageEvent, ...]:
    rows = [
        UsageEvent.create(
            workspace_id=run.workspace_id,
            kind=USAGE_RADAR_RUN,
            quantity=1,
            occurred_at=now,
            run_id=run.run_id,
        ),
        UsageEvent.create(
            workspace_id=run.workspace_id,
            kind=USAGE_SIGNAL_EVALUATED,
            quantity=run.signal_count,
            occurred_at=now,
            run_id=run.run_id,
        ),
        UsageEvent.create(
            workspace_id=run.workspace_id,
            kind=USAGE_MATCH_RECORDED,
            quantity=run.match_count,
            occurred_at=now,
            run_id=run.run_id,
        ),
    ]
    for candidate in candidates:
        rows.append(
            UsageEvent.create(
                workspace_id=run.workspace_id,
                kind=USAGE_ALERT_CANDIDATE,
                quantity=1,
                occurred_at=now,
                run_id=run.run_id,
                dedupe_key=entity_dedupe_key(
                    USAGE_ALERT_CANDIDATE,
                    candidate.candidate_id,
                ),
            )
        )
        if not candidate.qualified:
            rows.append(
                UsageEvent.create(
                    workspace_id=run.workspace_id,
                    kind=USAGE_ALERT_SUPPRESSED,
                    quantity=1,
                    occurred_at=now,
                    run_id=run.run_id,
                    dedupe_key=entity_dedupe_key(
                        USAGE_ALERT_SUPPRESSED,
                        candidate.candidate_id,
                    ),
                )
            )
    return tuple(rows)


T = TypeVar("T")


def _dedupe_by_id(values: list[T], field: str) -> tuple[T, ...]:
    latest: dict[str, T] = {}
    for value in values:
        latest[str(getattr(value, field))] = value
    return tuple(latest.values())
