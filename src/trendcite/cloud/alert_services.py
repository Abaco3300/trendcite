"""Application services for deterministic alert qualification, digesting and delivery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from . import ids
from .delivery import DeliveryEnvelope, DeliveryPort
from .domain.alerts import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCEEDED,
    DELIVERY_DELIVERED,
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
    Alert,
    AlertBaseline,
    AlertCandidate,
    AlertPolicy,
    DeliveryAttempt,
    MaterialityService,
    SignalState,
    latest_attempt_number,
    materiality_at_least,
)
from .domain.digests import Digest, DigestItem, digest_window, rank_candidates
from .renderers import render_alert, render_digest
from .repositories import UnitOfWorkFactory


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class AlertService:
    """Qualify and materialize one candidate without performing delivery."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        materiality: MaterialityService | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.uow_factory = uow_factory
        self.materiality = materiality or MaterialityService()
        self.clock = clock

    def qualify(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        watchlist_id: str,
        run_id: str,
        label: str,
        state: SignalState,
        match_status: str = "active",
        coverage_state: str,
        delivery_enabled: bool = True,
        radar_enabled: bool = True,
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
            reason = self._reason(
                policy=policy,
                match_status=match_status,
                state=state,
                evaluation_level=evaluation.level,
                baseline=baseline,
                now=now,
                delivery_enabled=delivery_enabled,
                radar_enabled=radar_enabled,
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
                existing = uow.alerts.get_candidate(workspace_id, candidate.candidate_id)
                uow.commit()
                return (
                    existing.with_reason(REASON_DUPLICATE)
                    if existing is not None
                    else candidate.with_reason(REASON_DUPLICATE)
                )
            uow.commit()
            return candidate

    def materialize(
        self,
        candidate: AlertCandidate,
        *,
        watchlist_name: str = "",
    ) -> Alert | None:
        if not candidate.qualified:
            return None
        payload = render_alert(candidate, watchlist_name=watchlist_name)
        alert = Alert.from_candidate(
            candidate,
            payload=payload,
            channel="local",
            created_at=self.clock(),
        )
        with self.uow_factory() as uow:
            existing = uow.alerts.alert_for_candidate(
                candidate.workspace_id,
                candidate.candidate_id,
            )
            if existing is not None:
                uow.commit()
                return existing
            uow.alerts.add_alert(alert)
            uow.commit()
        return alert

    @staticmethod
    def _reason(
        *,
        policy: AlertPolicy,
        match_status: str,
        state: SignalState,
        evaluation_level: str,
        baseline: AlertBaseline | None,
        now: datetime,
        delivery_enabled: bool,
        radar_enabled: bool,
    ) -> str:
        if (
            not radar_enabled
            or not delivery_enabled
            or not policy.enabled
            or not policy.immediate_alerts
        ):
            return REASON_DELIVERY_DISABLED
        if match_status == "muted":
            return REASON_MUTED
        if match_status == "dismissed":
            return REASON_DISMISSED
        if state.relevance_score < policy.min_relevance:
            return REASON_BELOW_RELEVANCE
        if not materiality_at_least(evaluation_level, policy.min_materiality):
            return REASON_BELOW_MATERIALITY
        if baseline is not None and now < baseline.delivered_at + policy.cooldown:
            return REASON_COOLDOWN
        return REASON_QUALIFIED


class DeliveryService:
    """Deliver persisted Alert/Digest targets through a provider-neutral port."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        port: DeliveryPort,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.uow_factory = uow_factory
        self.port = port
        self.clock = clock

    def deliver_alert(self, workspace_id: str, alert_id: str) -> Alert:
        with self.uow_factory() as uow:
            alert = uow.alerts.get_alert(workspace_id, alert_id)
            if alert is None:
                raise LookupError("alert not found")
            if alert.delivery_state == DELIVERY_DELIVERED:
                uow.commit()
                return alert
            policy = uow.alerts.get_policy(workspace_id, alert.radar_id)
            if policy is None:
                policy = AlertPolicy.default_for(
                    workspace_id=workspace_id,
                    radar_id=alert.radar_id,
                    updated_at=self.clock(),
                )
            attempts = uow.alerts.attempts_for(workspace_id, TARGET_ALERT, alert_id)
            next_attempt = latest_attempt_number(attempts) + 1
            max_attempts = policy.max_delivery_attempts
            uow.commit()

        envelope = DeliveryEnvelope(
            workspace_id=workspace_id,
            target_kind=TARGET_ALERT,
            target_id=alert_id,
            attempt_number=next_attempt,
            subject=alert.subject,
            body=alert.body,
            renderer_version=alert.renderer_version,
        )
        result = self.port.deliver(envelope)
        attempted_at = self.clock()
        attempt = DeliveryAttempt.create(
            workspace_id=workspace_id,
            target_kind=TARGET_ALERT,
            target_id=alert_id,
            attempt_number=next_attempt,
            channel=self.port.channel,
            status=ATTEMPT_SUCCEEDED if result.ok else ATTEMPT_FAILED,
            provider=result.provider,
            provider_reference=result.reference,
            detail=result.detail,
            attempted_at=attempted_at,
        )

        with self.uow_factory() as uow:
            uow.alerts.record_attempt(attempt)
            current = uow.alerts.get_alert(workspace_id, alert_id)
            if current is None:
                raise LookupError("alert disappeared")
            if result.ok:
                updated = current.delivered(
                    attempt_count=next_attempt,
                    delivered_at=attempted_at,
                )
                uow.alerts.update_alert(updated)
                candidate = uow.alerts.get_candidate(workspace_id, current.candidate_id)
                if candidate is not None:
                    baseline = AlertBaseline.of(
                        workspace_id=workspace_id,
                        watchlist_id=current.watchlist_id,
                        signal_id=current.signal_id,
                        alert_id=current.alert_id,
                        state=candidate.as_state(),
                        delivered_at=attempted_at,
                    )
                    uow.alerts.upsert_baseline(baseline)
            else:
                updated = current.attempted(
                    attempt_count=next_attempt,
                    exhausted=next_attempt >= max_attempts,
                )
                uow.alerts.update_alert(updated)
            uow.commit()
            return updated

    def deliver_digest(self, workspace_id: str, digest_id: str) -> Digest:
        with self.uow_factory() as uow:
            digest = uow.digests.get(workspace_id, digest_id)
            if digest is None:
                raise LookupError("digest not found")
            if digest.delivery_state == DELIVERY_DELIVERED:
                uow.commit()
                return digest
            policy = uow.alerts.get_policy(workspace_id, digest.radar_id)
            if policy is None:
                policy = AlertPolicy.default_for(
                    workspace_id=workspace_id,
                    radar_id=digest.radar_id,
                    updated_at=self.clock(),
                )
            attempts = uow.alerts.attempts_for(workspace_id, TARGET_DIGEST, digest_id)
            next_attempt = latest_attempt_number(attempts) + 1
            max_attempts = policy.max_delivery_attempts
            uow.commit()

        envelope = DeliveryEnvelope(
            workspace_id=workspace_id,
            target_kind=TARGET_DIGEST,
            target_id=digest_id,
            attempt_number=next_attempt,
            subject=digest.subject,
            body=digest.body,
            renderer_version=digest.renderer_version,
        )
        result = self.port.deliver(envelope)
        attempted_at = self.clock()
        attempt = DeliveryAttempt.create(
            workspace_id=workspace_id,
            target_kind=TARGET_DIGEST,
            target_id=digest_id,
            attempt_number=next_attempt,
            channel=self.port.channel,
            status=ATTEMPT_SUCCEEDED if result.ok else ATTEMPT_FAILED,
            provider=result.provider,
            provider_reference=result.reference,
            detail=result.detail,
            attempted_at=attempted_at,
        )

        with self.uow_factory() as uow:
            uow.alerts.record_attempt(attempt)
            current = uow.digests.get(workspace_id, digest_id)
            if current is None:
                raise LookupError("digest disappeared")
            if result.ok:
                updated = current.delivered(
                    attempt_count=next_attempt,
                    delivered_at=attempted_at,
                )
            else:
                updated = current.attempted(
                    attempt_count=next_attempt,
                    exhausted=next_attempt >= max_attempts,
                )
            uow.digests.upsert(updated)
            uow.commit()
            return updated


class DigestService:
    """Build one idempotent radar/day digest from persisted alert candidates."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.uow_factory = uow_factory
        self.clock = clock

    def build(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        radar_name: str,
        day: datetime,
    ) -> Digest | None:
        start, end, date_key = digest_window(day)
        with self.uow_factory() as uow:
            policy = uow.alerts.get_policy(workspace_id, radar_id)
            if policy is None:
                policy = AlertPolicy.default_for(
                    workspace_id=workspace_id,
                    radar_id=radar_id,
                    updated_at=self.clock(),
                )
            if not policy.enabled or not policy.daily_digest:
                uow.commit()
                return None
            candidates = uow.alerts.candidates_in_window(
                workspace_id,
                radar_id,
                start.isoformat(),
                end.isoformat(),
            )
            ranked = rank_candidates(candidates, max_items=policy.digest_max_items)
            if not ranked:
                uow.commit()
                return None

            digest_id = ids.digest_id(workspace_id, radar_id, date_key)
            items = [
                DigestItem.of(candidate, digest_id=digest_id, rank=index)
                for index, candidate in enumerate(ranked, 1)
            ]
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
                created_at=self.clock(),
            )
            uow.digests.upsert(digest)
            uow.digests.replace_items(workspace_id, digest.digest_id, items)
            uow.commit()
            return digest
