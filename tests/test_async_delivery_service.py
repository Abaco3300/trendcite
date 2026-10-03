from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from trendcite.cloud.async_delivery_service import AsyncDeliveryService
from trendcite.cloud.delivery import DeliveryResult
from trendcite.cloud.domain.alerts import (
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    REASON_QUALIFIED,
    Alert,
    AlertBaseline,
    AlertCandidate,
    AlertPolicy,
    DeliveryAttempt,
    MaterialityService,
    SignalState,
)
from trendcite.cloud.domain.digests import Digest, DigestItem

NOW = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


class FakeAsyncPort:
    channel = "email"

    def __init__(self, results: list[DeliveryResult]) -> None:
        self.results = list(results)
        self.calls = 0

    async def deliver(self, envelope):
        self.calls += 1
        return self.results.pop(0)


class FakeStore:
    def __init__(self, candidate: AlertCandidate, policy: AlertPolicy) -> None:
        self.policy = policy
        self.candidates = {candidate.candidate_id: candidate}
        self.alerts: dict[str, Alert] = {}
        self.attempts: list[DeliveryAttempt] = []
        self.baselines: dict[tuple[str, str, str], AlertBaseline] = {}
        self.digests: dict[str, Digest] = {}
        self.digest_items: dict[str, tuple[DigestItem, ...]] = {}

    async def get_policy(self, workspace_id: str, radar_id: str):
        return self.policy

    async def get_candidate(self, workspace_id: str, candidate_id: str):
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate.workspace_id != workspace_id:
            return None
        return candidate

    async def candidates_for_run(self, workspace_id: str, run_id: str):
        return tuple(
            candidate
            for candidate in self.candidates.values()
            if candidate.workspace_id == workspace_id and candidate.run_id == run_id
        )

    async def candidates_in_window(self, workspace_id: str, radar_id: str, start: str, end: str):
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        return tuple(
            candidate
            for candidate in self.candidates.values()
            if candidate.workspace_id == workspace_id
            and candidate.radar_id == radar_id
            and start_dt <= candidate.observed_at < end_dt
        )

    async def get_alert(self, workspace_id: str, alert_id: str):
        alert = self.alerts.get(alert_id)
        if alert is None or alert.workspace_id != workspace_id:
            return None
        return alert

    async def add_alert(self, alert: Alert):
        existing = next(
            (value for value in self.alerts.values() if value.candidate_id == alert.candidate_id),
            None,
        )
        if existing is not None:
            return existing
        self.alerts[alert.alert_id] = alert
        return alert

    async def update_alert(self, alert: Alert):
        self.alerts[alert.alert_id] = alert

    async def attempts_for(self, workspace_id: str, target_kind: str, target_id: str):
        return tuple(
            attempt
            for attempt in self.attempts
            if attempt.workspace_id == workspace_id
            and attempt.target_kind == target_kind
            and attempt.target_id == target_id
        )

    async def record_attempt(self, attempt: DeliveryAttempt):
        key = (
            attempt.workspace_id,
            attempt.target_kind,
            attempt.target_id,
            attempt.attempt_number,
        )
        if any(
            (
                item.workspace_id,
                item.target_kind,
                item.target_id,
                item.attempt_number,
            )
            == key
            for item in self.attempts
        ):
            return False
        self.attempts.append(attempt)
        return True

    async def upsert_baseline(self, baseline: AlertBaseline):
        self.baselines[(baseline.workspace_id, baseline.watchlist_id, baseline.signal_id)] = (
            baseline
        )

    async def get_digest(self, workspace_id: str, digest_id: str):
        digest = self.digests.get(digest_id)
        if digest is None or digest.workspace_id != workspace_id:
            return None
        return digest

    async def get_digest_by_date(self, workspace_id: str, radar_id: str, digest_date: str):
        return next(
            (
                digest
                for digest in self.digests.values()
                if digest.workspace_id == workspace_id
                and digest.radar_id == radar_id
                and digest.digest_date == digest_date
            ),
            None,
        )

    async def upsert_digest(self, digest: Digest):
        self.digests[digest.digest_id] = digest

    async def replace_digest_items(
        self,
        workspace_id: str,
        digest_id: str,
        items: tuple[DigestItem, ...],
    ):
        self.digest_items[digest_id] = items


def candidate() -> AlertCandidate:
    state = SignalState.create(
        signal_id="signal-1",
        snapshot_id="snapshot-1",
        signal_score=82,
        relevance_score=91,
        lifecycle_state="emerging",
        velocity=0.7,
        source_count=3,
        counterevidence=(),
        observed_at=NOW,
    )
    evaluation = MaterialityService().evaluate(state, None)
    return AlertCandidate.create(
        workspace_id="workspace-1",
        radar_id="radar-1",
        watchlist_id="watchlist-1",
        run_id="run-1",
        label="AI agent adoption",
        state=state,
        evaluation=evaluation,
        reason=REASON_QUALIFIED,
        created_at=NOW,
    )


def policy(*, max_attempts: int = 3) -> AlertPolicy:
    return AlertPolicy.create(
        workspace_id="workspace-1",
        radar_id="radar-1",
        updated_at=NOW,
        channel="email",
        max_delivery_attempts=max_attempts,
    )


def test_failed_alert_delivery_does_not_move_baseline_then_retry_succeeds() -> None:
    item = candidate()
    store = FakeStore(item, policy())
    port = FakeAsyncPort(
        [
            DeliveryResult(ok=False, provider="postmark", detail="temporary"),
            DeliveryResult(ok=True, provider="postmark", reference="message-2"),
        ]
    )
    service = AsyncDeliveryService(store, port, clock=Clock())

    alert = _run(service.materialize_alert("workspace-1", item.candidate_id))
    assert alert is not None

    first = _run(service.deliver_alert("workspace-1", alert.alert_id))
    assert first.delivery_state == DELIVERY_PENDING
    assert store.baselines == {}

    second = _run(service.deliver_alert("workspace-1", alert.alert_id))
    assert second.delivery_state == DELIVERY_DELIVERED
    assert len(store.attempts) == 2
    assert len(store.baselines) == 1
    assert port.calls == 2


def test_attempt_budget_is_hard_stop_and_never_sends_extra_attempt() -> None:
    item = candidate()
    store = FakeStore(item, policy(max_attempts=2))
    port = FakeAsyncPort(
        [
            DeliveryResult(ok=False, provider="postmark", detail="failure-1"),
            DeliveryResult(ok=False, provider="postmark", detail="failure-2"),
            DeliveryResult(ok=True, provider="postmark", reference="must-not-send"),
        ]
    )
    service = AsyncDeliveryService(store, port, clock=Clock())

    alert = _run(service.materialize_alert("workspace-1", item.candidate_id))
    assert alert is not None
    _run(service.deliver_alert("workspace-1", alert.alert_id))
    exhausted = _run(service.deliver_alert("workspace-1", alert.alert_id))
    assert exhausted.delivery_state == DELIVERY_FAILED

    replay = _run(service.deliver_alert("workspace-1", alert.alert_id))
    assert replay.delivery_state == DELIVERY_FAILED
    assert port.calls == 2
    assert len(store.attempts) == 2


def test_digest_build_is_idempotent_and_delivery_retries() -> None:
    item = candidate()
    store = FakeStore(item, policy())
    port = FakeAsyncPort(
        [
            DeliveryResult(ok=False, provider="postmark", detail="temporary"),
            DeliveryResult(ok=True, provider="postmark", reference="digest-message"),
        ]
    )
    service = AsyncDeliveryService(store, port, clock=Clock())

    digest = _run(
        service.build_digest(
            workspace_id="workspace-1",
            radar_id="radar-1",
            radar_name="Trend Radar",
            day=NOW,
        )
    )
    assert digest is not None
    rebuilt = _run(
        service.build_digest(
            workspace_id="workspace-1",
            radar_id="radar-1",
            radar_name="Trend Radar",
            day=NOW,
        )
    )
    assert rebuilt is not None
    assert rebuilt.digest_id == digest.digest_id
    assert len(store.digest_items[digest.digest_id]) == 1

    first = _run(service.deliver_digest("workspace-1", digest.digest_id))
    assert first.delivery_state == DELIVERY_PENDING
    second = _run(service.deliver_digest("workspace-1", digest.digest_id))
    assert second.delivery_state == DELIVERY_DELIVERED
    assert port.calls == 2
