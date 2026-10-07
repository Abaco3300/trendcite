from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trendcite.cloud.async_automation import AsyncAutomationReconciler
from trendcite.cloud.domain.automation import (
    RECOVERY_EXPIRED_FINAL_TERMINAL,
    RECOVERY_PENDING_REQUEUE,
    RecoveryCandidate,
)

NOW = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, payload: dict[str, str]) -> None:
        self.sent.append(dict(payload))


class FakeStore:
    def __init__(self, candidates: list[RecoveryCandidate]) -> None:
        self.candidates = tuple(candidates)
        self.recorded: set[tuple[str, int, str]] = set()
        self.terminalized: list[str] = []

    async def list_recovery_candidates(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        recovery_after: datetime,
        limit: int = 100,
    ) -> tuple[RecoveryCandidate, ...]:
        return self.candidates

    async def recovery_action_exists(self, candidate: RecoveryCandidate) -> bool:
        return (candidate.tick_id, candidate.attempt, candidate.action) in self.recorded

    async def record_recovery_action(
        self,
        candidate: RecoveryCandidate,
        *,
        created_at: datetime,
    ) -> bool:
        key = (candidate.tick_id, candidate.attempt, candidate.action)
        if key in self.recorded:
            return False
        self.recorded.add(key)
        return True

    async def terminalize_expired_final_attempt(
        self,
        candidate: RecoveryCandidate,
        *,
        now: datetime,
    ) -> bool:
        self.terminalized.append(candidate.tick_id)
        return True


def _candidate(action: str, *, attempt: int = 0, max_attempts: int = 3) -> RecoveryCandidate:
    return RecoveryCandidate(
        workspace_id="ws-a",
        tick_id="tick-a",
        schedule_id="schedule-a",
        status="running" if action == RECOVERY_EXPIRED_FINAL_TERMINAL else "pending",
        attempt=attempt,
        max_attempts=max_attempts,
        action=action,
        reason="synthetic",
    )


def test_pending_stale_tick_is_requeued_once() -> None:
    store = FakeStore([_candidate(RECOVERY_PENDING_REQUEUE)])
    queue = FakeQueue()
    reconciler = AsyncAutomationReconciler(
        store,
        queue,
        stale_seconds=120,
        recovery_after=datetime(2026, 10, 7, 21, 30, tzinfo=UTC),
    )

    first = _run(reconciler.reconcile(now=NOW))
    second = _run(reconciler.reconcile(now=NOW))

    assert first.requeued == 1
    assert first.terminalized == 0
    assert len(queue.sent) == 1
    assert queue.sent[0]["tick_id"] == "tick-a"
    assert second.requeued == 0
    assert second.already_recorded == 1
    assert len(queue.sent) == 1


def test_expired_final_attempt_becomes_terminal_without_queue_replay() -> None:
    candidate = _candidate(
        RECOVERY_EXPIRED_FINAL_TERMINAL,
        attempt=3,
        max_attempts=3,
    )
    store = FakeStore([candidate])
    queue = FakeQueue()
    reconciler = AsyncAutomationReconciler(
        store,
        queue,
        recovery_after=datetime(2026, 10, 7, 21, 30, tzinfo=UTC),
    )

    result = _run(reconciler.reconcile(now=NOW))

    assert result.terminalized == 1
    assert result.requeued == 0
    assert store.terminalized == ["tick-a"]
    assert queue.sent == []
    assert ("tick-a", 3, RECOVERY_EXPIRED_FINAL_TERMINAL) in store.recorded
