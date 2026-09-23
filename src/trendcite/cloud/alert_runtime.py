"""Application orchestration for PC-06B alert, digest and delivery runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .delivery import DeliveryEnvelope, DeliveryPort
from .domain.alerts import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCEEDED,
    DEFAULT_MATERIALITY_SERVICE,
    DEFAULT_MAX_DELIVERY_ATTEMPTS,
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    REASON_BELOW_MATERIALITY,
    REASON_BELOW_RELEVANCE,
    REASON_COOLDOWN,
    REASON_DELIVERY_DISABLED,
    REASON_DISMISSED,
    REASON_DUPLICATE,
    REASON_MUTED,
    REASON_QUALIFIED,
    TARGET_ALERT,
    TARGET_DIGEST,
    VELOCITY_COMPONENT,
    Alert,
    AlertBaseline,
    AlertCandidate,
    AlertPolicy,
    DeliveryAttempt,
    MaterialityEvaluation,
    MaterialityService,
    SignalState,
    latest_attempt_number,
    materiality_at_least,
)
from .domain.digests import Digest, DigestItem, digest_window, rank_candidates
from .domain.matches import DECISION_MATCHED
from .domain.radar import RUN_COVERAGE_COMPLETE, RUN_SUCCEEDED
from .domain.relevance import MATCH_ACTIVE
from .domain.signals import StoredSignalEvaluation
from .domain.usage import (
    USAGE_ALERT_CANDIDATE,
    USAGE_ALERT_CREATED,
    USAGE_ALERT_SUPPRESSED,
    USAGE_DELIVERY_ATTEMPT,
    USAGE_DELIVERY_FAILURE,
    USAGE_DELIVERY_SUCCESS,
    USAGE_DIGEST_CREATED,
    UsageEvent,
    entity_dedupe_key,
)
from .errors import NotFoundError
from .ids import digest_id
from .renderers import render_alert, render_digest
from .repositories import UnitOfWork, UnitOfWorkFactory

Clock = Callable[[], datetime]

# Counterevidence codes this layer can restate exactly from a stored snapshot. The
# core records more of them (stale evidence, contradiction, incohesion) but those need
# the observations themselves, which Cloud does not keep. Rather than approximate a
# code and silently change what it means, only the four that are exactly reproducible
# from stored fields are derived here.
CE_SINGLE_SOURCE = "single_source"
CE_SYNDICATED_ECHO = "syndicated_echo"
CE_SMALL_SAMPLE = "small_sample"
CE_NO_ENGAGEMENT_METRICS = "no_engagement_metrics"

#: The engagement component, by the name the core evaluation gives it.
ENGAGEMENT_COMPONENT = "engagement_strength"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def counterevidence_from(snapshot: StoredSignalEvaluation) -> tuple[str, ...]:
    """Restate the counterevidence a stored snapshot still carries evidence for.

    Each rule below is the core's own rule evaluated over the counts the snapshot
    preserves, so a code means here exactly what it means in a brief. Codes the
    snapshot cannot support are simply absent rather than guessed at.
    """
    codes: list[str] = []
    if snapshot.source_count <= 1:
        codes.append(CE_SINGLE_SOURCE)
    if snapshot.observation_count > snapshot.story_count:
        codes.append(CE_SYNDICATED_ECHO)
    if snapshot.story_count <= 2:
        codes.append(CE_SMALL_SAMPLE)
    if snapshot.component_values.get(ENGAGEMENT_COMPONENT) is None:
        codes.append(CE_NO_ENGAGEMENT_METRICS)
    return tuple(sorted(codes))


@dataclass(frozen=True)
class AlertingOutcome:
    """What one pass over a run decided, and what it managed to send."""

    run_id: str
    candidates: tuple[AlertCandidate, ...]
    alerts: tuple[Alert, ...]

    @property
    def qualified(self) -> tuple[AlertCandidate, ...]:
        return tuple(c for c in self.candidates if c.reason == REASON_QUALIFIED)

    @property
    def delivered(self) -> tuple[Alert, ...]:
        return tuple(a for a in self.alerts if a.delivery_state == DELIVERY_DELIVERED)


@dataclass(frozen=True)
class _Subject:
    """One (watchlist, signal) pair a run matched, with everything needed to judge it."""

    watchlist_id: str
    watchlist_name: str
    label: str
    state: SignalState
    match_status: str


class AlertDigestRuntime:
    """Transport-independent Alert/Digest application service."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        delivery_port: DeliveryPort,
        *,
        materiality: MaterialityService = DEFAULT_MATERIALITY_SERVICE,
        clock: Clock = utc_now,
    ) -> None:
        self.uow_factory = uow_factory
        self.delivery_port = delivery_port
        self.materiality = materiality
        self.clock = clock

    def set_policy(self, policy: AlertPolicy) -> None:
        with self.uow_factory() as uow:
            uow.alerts.upsert_policy(policy)
            uow.commit()

    def evaluate(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        watchlist_id: str,
        run_id: str,
        label: str,
        state: SignalState,
        match_status: str = "active",
        coverage_state: str = RUN_COVERAGE_COMPLETE,
    ) -> AlertCandidate:
        now = self.clock()
        with self.uow_factory() as uow:
            policy = uow.alerts.get_policy(workspace_id, radar_id)
            if policy is None:
                policy = AlertPolicy.default_for(
                    workspace_id=workspace_id,
                    radar_id=radar_id,
                    updated_at=now,
                )
            baseline = uow.alerts.get_baseline(workspace_id, watchlist_id, state.signal_id)
            evaluation = self.materiality.evaluate(
                state,
                baseline,
                coverage_state=coverage_state,
            )
            reason = self._qualification_reason(
                policy=policy,
                match_status=match_status,
                state=state,
                evaluation=evaluation,
                baseline=baseline,
                now=now,
            )
            candidate = AlertCandidate.create(
                workspace_id=workspace_id,
                radar_id=radar_id,
                watchlist_id=watchlist_id,
                run_id=run_id,
                label=label,
                state=state,
                evaluation=evaluation,
                reason=reason,
                created_at=now,
            )
            inserted = uow.alerts.add_candidate(candidate)
            if not inserted:
                return candidate.with_reason(REASON_DUPLICATE)

            self._meter(
                uow,
                workspace_id=workspace_id,
                kind=USAGE_ALERT_CANDIDATE,
                entity_id=candidate.candidate_id,
                run_id=run_id,
                when=now,
            )
            if not candidate.qualified:
                self._meter(
                    uow,
                    workspace_id=workspace_id,
                    kind=USAGE_ALERT_SUPPRESSED,
                    entity_id=candidate.candidate_id,
                    run_id=run_id,
                    when=now,
                )
                uow.commit()
                return candidate

            payload = render_alert(candidate)
            alert = Alert.from_candidate(
                candidate,
                payload=payload,
                channel=policy.channel,
                created_at=now,
            )
            uow.alerts.add_alert(alert)
            self._meter(
                uow,
                workspace_id=workspace_id,
                kind=USAGE_ALERT_CREATED,
                entity_id=alert.alert_id,
                run_id=run_id,
                when=now,
            )
            uow.commit()
            return candidate

    def alert_for_candidate(self, workspace_id: str, candidate_id: str) -> Alert | None:
        with self.uow_factory() as uow:
            return uow.alerts.alert_for_candidate(workspace_id, candidate_id)

    def deliver_alert(self, workspace_id: str, alert_id: str) -> Alert:
        alert, candidate, policy, attempt_number = self._load_alert_delivery(workspace_id, alert_id)
        if alert.delivery_state == DELIVERY_DELIVERED:
            return alert
        if attempt_number > policy.max_delivery_attempts:
            # The budget is spent. Settle the stored row rather than returning an
            # in-memory verdict a later reader would never see.
            exhausted_alert = alert.attempted(
                attempt_count=policy.max_delivery_attempts,
                exhausted=True,
            )
            with self.uow_factory() as uow:
                uow.alerts.update_alert(exhausted_alert)
                uow.commit()
            return exhausted_alert

        envelope = DeliveryEnvelope(
            workspace_id=workspace_id,
            target_kind=TARGET_ALERT,
            target_id=alert.alert_id,
            attempt_number=attempt_number,
            subject=alert.subject,
            body=alert.body,
            renderer_version=alert.renderer_version,
        )
        result = self.delivery_port.deliver(envelope)
        now = self.clock()
        attempt = DeliveryAttempt.create(
            workspace_id=workspace_id,
            target_kind=TARGET_ALERT,
            target_id=alert.alert_id,
            attempt_number=attempt_number,
            channel=self.delivery_port.channel,
            status=ATTEMPT_SUCCEEDED if result.ok else ATTEMPT_FAILED,
            provider=result.provider,
            provider_reference=result.reference,
            detail=result.detail,
            attempted_at=now,
        )
        exhausted = attempt_number >= policy.max_delivery_attempts
        updated = (
            alert.delivered(attempt_count=attempt_number, delivered_at=now)
            if result.ok
            else alert.attempted(
                attempt_count=attempt_number,
                exhausted=exhausted,
            )
        )
        with self.uow_factory() as uow:
            uow.alerts.record_attempt(attempt)
            uow.alerts.update_alert(updated)
            self._meter_delivery(
                uow,
                workspace_id=workspace_id,
                attempt=attempt,
                run_id=candidate.run_id,
            )
            if result.ok:
                baseline = AlertBaseline.of(
                    workspace_id=workspace_id,
                    watchlist_id=alert.watchlist_id,
                    signal_id=alert.signal_id,
                    alert_id=alert.alert_id,
                    state=candidate.as_state(),
                    delivered_at=now,
                )
                uow.alerts.upsert_baseline(baseline)
            uow.commit()
        return updated

    def build_digest(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        radar_name: str,
        day: datetime,
    ) -> Digest | None:
        now = self.clock()
        start, end, date_key = digest_window(day)
        with self.uow_factory() as uow:
            policy = uow.alerts.get_policy(workspace_id, radar_id)
            if policy is None:
                policy = AlertPolicy.default_for(
                    workspace_id=workspace_id,
                    radar_id=radar_id,
                    updated_at=now,
                )
            if not policy.enabled or not policy.daily_digest:
                return None
            candidates = uow.alerts.candidates_in_window(
                workspace_id,
                radar_id,
                start.isoformat(),
                end.isoformat(),
            )
            ranked = rank_candidates(
                candidates,
                max_items=policy.digest_max_items,
            )
            if not ranked:
                return None
            existing = uow.digests.by_date(workspace_id, radar_id, date_key)

            did = digest_id(workspace_id, radar_id, date_key)
            items = tuple(
                DigestItem.of(candidate, digest_id=did, rank=index)
                for index, candidate in enumerate(ranked, 1)
            )
            payload = render_digest(
                items,
                radar_name=radar_name,
                digest_date=date_key,
            )
            digest = Digest.create(
                workspace_id=workspace_id,
                radar_id=radar_id,
                day=day,
                items=items,
                payload=payload,
                channel=policy.channel,
                created_at=now if existing is None else existing.created_at,
            )
            if existing is not None:
                # A rebuild restates the day's content; it does not un-send it.
                # Carrying the delivery state across is what keeps "rebuild" from
                # quietly becoming "send again".
                digest = digest.attempted(
                    attempt_count=existing.attempt_count,
                    exhausted=existing.delivery_state == DELIVERY_FAILED,
                )
                if (
                    existing.delivery_state == DELIVERY_DELIVERED
                    and existing.delivered_at is not None
                ):
                    digest = digest.delivered(
                        attempt_count=existing.attempt_count,
                        delivered_at=existing.delivered_at,
                    )
            uow.digests.upsert(digest)
            uow.digests.replace_items(workspace_id, digest.digest_id, items)
            self._meter(
                uow,
                workspace_id=workspace_id,
                kind=USAGE_DIGEST_CREATED,
                entity_id=digest.digest_id,
                run_id="",
                when=now,
            )
            uow.commit()
            return digest

    def deliver_digest(self, workspace_id: str, digest_id_value: str) -> Digest:
        with self.uow_factory() as uow:
            digest = uow.digests.get(workspace_id, digest_id_value)
            if digest is None:
                raise NotFoundError("digest not found in workspace")
            policy = uow.alerts.get_policy(workspace_id, digest.radar_id)
            if policy is None:
                policy = AlertPolicy.default_for(
                    workspace_id=workspace_id,
                    radar_id=digest.radar_id,
                    updated_at=self.clock(),
                )
            attempts = uow.alerts.attempts_for(
                workspace_id,
                TARGET_DIGEST,
                digest.digest_id,
            )
            attempt_number = latest_attempt_number(attempts) + 1

        if digest.delivery_state == DELIVERY_DELIVERED:
            return digest
        if attempt_number > policy.max_delivery_attempts:
            exhausted_digest = digest.attempted(
                attempt_count=policy.max_delivery_attempts,
                exhausted=True,
            )
            with self.uow_factory() as uow:
                uow.digests.upsert(exhausted_digest)
                uow.commit()
            return exhausted_digest
        envelope = DeliveryEnvelope(
            workspace_id=workspace_id,
            target_kind=TARGET_DIGEST,
            target_id=digest.digest_id,
            attempt_number=attempt_number,
            subject=digest.subject,
            body=digest.body,
            renderer_version=digest.renderer_version,
        )
        result = self.delivery_port.deliver(envelope)
        now = self.clock()
        attempt = DeliveryAttempt.create(
            workspace_id=workspace_id,
            target_kind=TARGET_DIGEST,
            target_id=digest.digest_id,
            attempt_number=attempt_number,
            channel=self.delivery_port.channel,
            status=ATTEMPT_SUCCEEDED if result.ok else ATTEMPT_FAILED,
            provider=result.provider,
            provider_reference=result.reference,
            detail=result.detail,
            attempted_at=now,
        )
        exhausted = attempt_number >= policy.max_delivery_attempts
        updated = (
            digest.delivered(attempt_count=attempt_number, delivered_at=now)
            if result.ok
            else digest.attempted(
                attempt_count=attempt_number,
                exhausted=exhausted,
            )
        )
        with self.uow_factory() as uow:
            uow.alerts.record_attempt(attempt)
            uow.digests.upsert(updated)
            self._meter_delivery(
                uow,
                workspace_id=workspace_id,
                attempt=attempt,
                run_id="",
            )
            uow.commit()
        return updated

    def process_run(self, *, workspace_id: str, run_id: str) -> AlertingOutcome:
        """Judge everything one succeeded run matched, then deliver what qualified.

        This is the bridge between a RadarRun and the alerting layer, and it is
        deliberately replayable: every candidate id is a function of the snapshot it
        judged, so a retried run, a re-run or a second pass re-decides in memory and
        writes nothing. That is what keeps "the collector failed once" from turning
        into two alerts about one event.
        """
        with self.uow_factory() as uow:
            run = uow.runs.get(workspace_id, run_id)
        if run is None:
            raise NotFoundError("run not found in workspace")
        if run.status != RUN_SUCCEEDED:
            return AlertingOutcome(run_id=run_id, candidates=(), alerts=())

        candidates: list[AlertCandidate] = []
        deliverable: list[str] = []
        for subject in self._subjects_for_run(workspace_id=workspace_id, run_id=run_id):
            candidate = self.evaluate(
                workspace_id=workspace_id,
                radar_id=run.radar_id,
                watchlist_id=subject.watchlist_id,
                run_id=run_id,
                label=subject.label,
                state=subject.state,
                match_status=subject.match_status,
                coverage_state=run.coverage_state,
            )
            candidates.append(candidate)
            if candidate.reason != REASON_QUALIFIED:
                continue
            alert = self.alert_for_candidate(workspace_id, candidate.candidate_id)
            if alert is not None and alert.delivery_state != DELIVERY_DELIVERED:
                deliverable.append(alert.alert_id)

        # Delivery runs only once every judgement has been committed, so no port call
        # can be holding a write the next judgement needs.
        alerts = [self.deliver_until_settled(workspace_id, alert_id) for alert_id in deliverable]
        return AlertingOutcome(
            run_id=run_id,
            candidates=tuple(candidates),
            alerts=tuple(alerts),
        )

    def deliver_until_settled(self, workspace_id: str, alert_id: str) -> Alert:
        """Attempt delivery until it succeeds or the attempt budget is spent.

        The budget belongs to the alert's stored history rather than to this call, so
        calling it again on an exhausted alert adds no attempts. The loop is bounded by
        that same budget, which is what stops a port that always refuses from becoming
        an infinite retry.
        """
        alert = self.deliver_alert(workspace_id, alert_id)
        budget = self._attempt_budget(workspace_id, alert.radar_id)
        while alert.delivery_state == DELIVERY_PENDING and alert.attempt_count < budget:
            alert = self.deliver_alert(workspace_id, alert_id)
        return alert

    def _attempt_budget(self, workspace_id: str, radar_id: str) -> int:
        with self.uow_factory() as uow:
            policy = uow.alerts.get_policy(workspace_id, radar_id)
        if policy is not None:
            return policy.max_delivery_attempts
        return DEFAULT_MAX_DELIVERY_ATTEMPTS

    def _subjects_for_run(self, *, workspace_id: str, run_id: str) -> list[_Subject]:
        """Read, in one transaction, everything the judging loop will need.

        Only evaluations the matcher called ``matched`` become subjects. A signal the
        watchlist never described, or one it explicitly excluded, was never an
        opportunity to alert, and the match log already records why -- restating that
        here would be a second copy of the same decision under a different name.
        """
        subjects: list[_Subject] = []
        with self.uow_factory() as uow:
            snapshots: dict[str, StoredSignalEvaluation] = {}
            watchlist_names: dict[str, str] = {}
            for evaluation in uow.relevance.evaluations_for_run(workspace_id, run_id):
                if evaluation.decision != DECISION_MATCHED:
                    continue
                if evaluation.watchlist_id not in watchlist_names:
                    watchlist = uow.watchlists.get(workspace_id, evaluation.watchlist_id)
                    watchlist_names[evaluation.watchlist_id] = (
                        "" if watchlist is None else watchlist.name
                    )
                if evaluation.snapshot_id not in snapshots:
                    for stored in uow.signals.evaluations(evaluation.signal_id):
                        snapshots[stored.snapshot_id] = stored
                snapshot = snapshots.get(evaluation.snapshot_id)
                if snapshot is None:
                    continue
                signal = uow.signals.get(evaluation.signal_id)
                current = uow.relevance.get_current(
                    workspace_id, evaluation.watchlist_id, evaluation.signal_id
                )
                subjects.append(
                    _Subject(
                        watchlist_id=evaluation.watchlist_id,
                        watchlist_name=watchlist_names[evaluation.watchlist_id],
                        label="" if signal is None else signal.label,
                        state=SignalState.create(
                            signal_id=evaluation.signal_id,
                            snapshot_id=evaluation.snapshot_id,
                            signal_score=snapshot.score,
                            relevance_score=evaluation.score,
                            lifecycle_state=snapshot.state,
                            velocity=snapshot.component_values.get(VELOCITY_COMPONENT),
                            source_count=snapshot.source_count,
                            counterevidence=counterevidence_from(snapshot),
                            observed_at=snapshot.captured_at,
                        ),
                        match_status=MATCH_ACTIVE if current is None else current.status,
                    )
                )
        return subjects

    def _load_alert_delivery(
        self, workspace_id: str, alert_id: str
    ) -> tuple[Alert, AlertCandidate, AlertPolicy, int]:
        with self.uow_factory() as uow:
            alert = uow.alerts.get_alert(workspace_id, alert_id)
            if alert is None:
                raise NotFoundError("alert not found in workspace")
            candidate = uow.alerts.get_candidate(
                workspace_id,
                alert.candidate_id,
            )
            if candidate is None:
                raise NotFoundError("alert candidate not found in workspace")
            policy = uow.alerts.get_policy(workspace_id, alert.radar_id)
            if policy is None:
                policy = AlertPolicy.default_for(
                    workspace_id=workspace_id,
                    radar_id=alert.radar_id,
                    updated_at=self.clock(),
                )
            attempts = uow.alerts.attempts_for(
                workspace_id,
                TARGET_ALERT,
                alert.alert_id,
            )
            return (
                alert,
                candidate,
                policy,
                latest_attempt_number(attempts) + 1,
            )

    @staticmethod
    def _qualification_reason(
        *,
        policy: AlertPolicy,
        match_status: str,
        state: SignalState,
        evaluation: MaterialityEvaluation,
        baseline: AlertBaseline | None,
        now: datetime,
    ) -> str:
        if not policy.enabled or not policy.immediate_alerts:
            return REASON_DELIVERY_DISABLED
        if match_status == "muted":
            return REASON_MUTED
        if match_status == "dismissed":
            return REASON_DISMISSED
        if state.relevance_score < policy.min_relevance:
            return REASON_BELOW_RELEVANCE
        if not materiality_at_least(
            evaluation.level,
            policy.min_materiality,
        ):
            return REASON_BELOW_MATERIALITY
        if baseline is not None and now < baseline.delivered_at + policy.cooldown:
            return REASON_COOLDOWN
        return REASON_QUALIFIED

    @staticmethod
    def _meter(
        uow: UnitOfWork,
        *,
        workspace_id: str,
        kind: str,
        entity_id: str,
        run_id: str,
        when: datetime,
    ) -> None:
        uow.usage.record(
            UsageEvent.create(
                workspace_id=workspace_id,
                kind=kind,
                quantity=1,
                occurred_at=when,
                run_id=run_id,
                dedupe_key=entity_dedupe_key(kind, entity_id),
            )
        )

    def _meter_delivery(
        self,
        uow: UnitOfWork,
        *,
        workspace_id: str,
        attempt: DeliveryAttempt,
        run_id: str,
    ) -> None:
        self._meter(
            uow,
            workspace_id=workspace_id,
            kind=USAGE_DELIVERY_ATTEMPT,
            entity_id=attempt.attempt_id,
            run_id=run_id,
            when=attempt.attempted_at,
        )
        self._meter(
            uow,
            workspace_id=workspace_id,
            kind=(USAGE_DELIVERY_SUCCESS if attempt.succeeded else USAGE_DELIVERY_FAILURE),
            entity_id=attempt.attempt_id,
            run_id=run_id,
            when=attempt.attempted_at,
        )
