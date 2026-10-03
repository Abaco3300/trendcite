"""Async alert/digest materialization and delivery orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from .async_delivery import AsyncDeliveryPort
from .delivery import DeliveryEnvelope
from .domain.alerts import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCEEDED,
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    REASON_QUALIFIED,
    TARGET_ALERT,
    TARGET_DIGEST,
    Alert,
    AlertBaseline,
    AlertCandidate,
    AlertPolicy,
    DeliveryAttempt,
    latest_attempt_number,
)
from .domain.digests import Digest, DigestItem, digest_window, rank_candidates
from .renderers import render_alert, render_digest


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class AsyncDeliveryStore(Protocol):
    async def get_policy(self, workspace_id: str, radar_id: str) -> AlertPolicy | None: ...

    async def get_candidate(
        self, workspace_id: str, candidate_id: str
    ) -> AlertCandidate | None: ...

    async def candidates_for_run(
        self,
        workspace_id: str,
        run_id: str,
    ) -> tuple[AlertCandidate, ...]: ...

    async def candidates_in_window(
        self,
        workspace_id: str,
        radar_id: str,
        start: str,
        end: str,
    ) -> tuple[AlertCandidate, ...]: ...

    async def get_alert(self, workspace_id: str, alert_id: str) -> Alert | None: ...

    async def add_alert(self, alert: Alert) -> Alert: ...

    async def update_alert(self, alert: Alert) -> None: ...

    async def attempts_for(
        self,
        workspace_id: str,
        target_kind: str,
        target_id: str,
    ) -> tuple[DeliveryAttempt, ...]: ...

    async def record_attempt(self, attempt: DeliveryAttempt) -> bool: ...

    async def upsert_baseline(self, baseline: AlertBaseline) -> None: ...

    async def get_digest(self, workspace_id: str, digest_id: str) -> Digest | None: ...

    async def get_digest_by_date(
        self,
        workspace_id: str,
        radar_id: str,
        digest_date: str,
    ) -> Digest | None: ...

    async def upsert_digest(self, digest: Digest) -> None: ...

    async def replace_digest_items(
        self,
        workspace_id: str,
        digest_id: str,
        items: tuple[DigestItem, ...],
    ) -> None: ...


class AsyncDeliveryService:
    def __init__(
        self,
        store: AsyncDeliveryStore,
        port: AsyncDeliveryPort,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.store = store
        self.port = port
        self.clock = clock

    async def materialize_run_alerts(
        self,
        workspace_id: str,
        run_id: str,
    ) -> tuple[Alert, ...]:
        candidates = await self.store.candidates_for_run(workspace_id, run_id)
        alerts: list[Alert] = []
        for candidate in candidates:
            alert = await self.materialize_alert(workspace_id, candidate.candidate_id)
            if alert is not None:
                alerts.append(alert)
        return tuple(alerts)

    async def process_run_alerts(
        self,
        workspace_id: str,
        run_id: str,
    ) -> tuple[Alert, ...]:
        alerts = await self.materialize_run_alerts(workspace_id, run_id)
        delivered: list[Alert] = []
        for alert in alerts:
            delivered.append(await self.deliver_alert(workspace_id, alert.alert_id))
        return tuple(delivered)

    async def materialize_alert(
        self,
        workspace_id: str,
        candidate_id: str,
        *,
        watchlist_name: str = "",
    ) -> Alert | None:
        candidate = await self.store.get_candidate(workspace_id, candidate_id)
        if candidate is None:
            raise LookupError("alert candidate not found")
        if candidate.reason != REASON_QUALIFIED:
            return None

        policy = await self._policy(workspace_id, candidate.radar_id)
        if not policy.enabled or not policy.immediate_alerts:
            return None

        payload = render_alert(candidate, watchlist_name=watchlist_name)
        alert = Alert.from_candidate(
            candidate,
            payload=payload,
            channel=self.port.channel,
            created_at=self.clock(),
        )
        return await self.store.add_alert(alert)

    async def deliver_alert(self, workspace_id: str, alert_id: str) -> Alert:
        alert = await self.store.get_alert(workspace_id, alert_id)
        if alert is None:
            raise LookupError("alert not found")
        if alert.delivery_state in {DELIVERY_DELIVERED, DELIVERY_FAILED}:
            return alert

        policy = await self._policy(workspace_id, alert.radar_id)
        attempts = await self.store.attempts_for(workspace_id, TARGET_ALERT, alert_id)
        attempt_number = latest_attempt_number(attempts) + 1
        if attempt_number > policy.max_delivery_attempts:
            exhausted = alert.attempted(
                attempt_count=policy.max_delivery_attempts,
                exhausted=True,
            )
            await self.store.update_alert(exhausted)
            return exhausted

        envelope = DeliveryEnvelope(
            workspace_id=workspace_id,
            target_kind=TARGET_ALERT,
            target_id=alert_id,
            attempt_number=attempt_number,
            subject=alert.subject,
            body=alert.body,
            renderer_version=alert.renderer_version,
        )
        result = await self.port.deliver(envelope)
        attempted_at = self.clock()
        attempt = DeliveryAttempt.create(
            workspace_id=workspace_id,
            target_kind=TARGET_ALERT,
            target_id=alert_id,
            attempt_number=attempt_number,
            channel=self.port.channel,
            status=ATTEMPT_SUCCEEDED if result.ok else ATTEMPT_FAILED,
            provider=result.provider,
            provider_reference=result.reference,
            detail=result.detail,
            attempted_at=attempted_at,
        )
        inserted = await self.store.record_attempt(attempt)
        if not inserted:
            current = await self.store.get_alert(workspace_id, alert_id)
            if current is None:
                raise LookupError("alert disappeared")
            return current

        current = await self.store.get_alert(workspace_id, alert_id)
        if current is None:
            raise LookupError("alert disappeared")

        if result.ok:
            updated = current.delivered(
                attempt_count=attempt_number,
                delivered_at=attempted_at,
            )
            await self.store.update_alert(updated)
            candidate = await self.store.get_candidate(workspace_id, current.candidate_id)
            if candidate is not None:
                baseline = AlertBaseline.of(
                    workspace_id=workspace_id,
                    watchlist_id=current.watchlist_id,
                    signal_id=current.signal_id,
                    alert_id=current.alert_id,
                    state=candidate.as_state(),
                    delivered_at=attempted_at,
                )
                await self.store.upsert_baseline(baseline)
            return updated

        updated = current.attempted(
            attempt_count=attempt_number,
            exhausted=attempt_number >= policy.max_delivery_attempts,
        )
        await self.store.update_alert(updated)
        return updated

    async def build_digest(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        radar_name: str,
        day: datetime,
    ) -> Digest | None:
        policy = await self._policy(workspace_id, radar_id)
        if not policy.enabled or not policy.daily_digest:
            return None

        start, end, date_key = digest_window(day)
        candidates = await self.store.candidates_in_window(
            workspace_id,
            radar_id,
            start.isoformat(),
            end.isoformat(),
        )
        ranked = rank_candidates(candidates, max_items=policy.digest_max_items)
        if not ranked:
            return None

        existing = await self.store.get_digest_by_date(workspace_id, radar_id, date_key)
        digest_id = _digest_id(workspace_id, radar_id, date_key)
        items = tuple(
            DigestItem.of(candidate, digest_id=digest_id, rank=index)
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
            channel=self.port.channel,
            created_at=self.clock() if existing is None else existing.created_at,
        )
        if existing is not None:
            digest = digest.attempted(
                attempt_count=existing.attempt_count,
                exhausted=existing.delivery_state == DELIVERY_FAILED,
            )
            if existing.delivery_state == DELIVERY_DELIVERED and existing.delivered_at is not None:
                digest = digest.delivered(
                    attempt_count=existing.attempt_count,
                    delivered_at=existing.delivered_at,
                )

        await self.store.upsert_digest(digest)
        await self.store.replace_digest_items(workspace_id, digest.digest_id, items)
        return digest

    async def deliver_digest(self, workspace_id: str, digest_id: str) -> Digest:
        digest = await self.store.get_digest(workspace_id, digest_id)
        if digest is None:
            raise LookupError("digest not found")
        if digest.delivery_state in {DELIVERY_DELIVERED, DELIVERY_FAILED}:
            return digest

        policy = await self._policy(workspace_id, digest.radar_id)
        attempts = await self.store.attempts_for(workspace_id, TARGET_DIGEST, digest_id)
        attempt_number = latest_attempt_number(attempts) + 1
        if attempt_number > policy.max_delivery_attempts:
            exhausted = digest.attempted(
                attempt_count=policy.max_delivery_attempts,
                exhausted=True,
            )
            await self.store.upsert_digest(exhausted)
            return exhausted

        envelope = DeliveryEnvelope(
            workspace_id=workspace_id,
            target_kind=TARGET_DIGEST,
            target_id=digest_id,
            attempt_number=attempt_number,
            subject=digest.subject,
            body=digest.body,
            renderer_version=digest.renderer_version,
        )
        result = await self.port.deliver(envelope)
        attempted_at = self.clock()
        attempt = DeliveryAttempt.create(
            workspace_id=workspace_id,
            target_kind=TARGET_DIGEST,
            target_id=digest_id,
            attempt_number=attempt_number,
            channel=self.port.channel,
            status=ATTEMPT_SUCCEEDED if result.ok else ATTEMPT_FAILED,
            provider=result.provider,
            provider_reference=result.reference,
            detail=result.detail,
            attempted_at=attempted_at,
        )
        inserted = await self.store.record_attempt(attempt)
        if not inserted:
            current = await self.store.get_digest(workspace_id, digest_id)
            if current is None:
                raise LookupError("digest disappeared")
            return current

        current = await self.store.get_digest(workspace_id, digest_id)
        if current is None:
            raise LookupError("digest disappeared")
        updated = (
            current.delivered(
                attempt_count=attempt_number,
                delivered_at=attempted_at,
            )
            if result.ok
            else current.attempted(
                attempt_count=attempt_number,
                exhausted=attempt_number >= policy.max_delivery_attempts,
            )
        )
        await self.store.upsert_digest(updated)
        return updated

    async def _policy(self, workspace_id: str, radar_id: str) -> AlertPolicy:
        policy = await self.store.get_policy(workspace_id, radar_id)
        if policy is not None:
            return policy
        return AlertPolicy.default_for(
            workspace_id=workspace_id,
            radar_id=radar_id,
            updated_at=self.clock(),
        )


def _digest_id(workspace_id: str, radar_id: str, date_key: str) -> str:
    from .ids import digest_id

    return digest_id(workspace_id, radar_id, date_key)
