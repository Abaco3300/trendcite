"""Autonomous stale-work reconciliation for TC-P007."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from .domain.automation import (
    RECOVERY_EXPIRED_FINAL_TERMINAL,
    AutomationRecoveryResult,
    RecoveryCandidate,
)


class AutomationStore(Protocol):
    async def list_recovery_candidates(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int = 100,
    ) -> tuple[RecoveryCandidate, ...]: ...

    async def recovery_action_exists(self, candidate: RecoveryCandidate) -> bool: ...

    async def record_recovery_action(
        self,
        candidate: RecoveryCandidate,
        *,
        created_at: datetime,
    ) -> bool: ...

    async def terminalize_expired_final_attempt(
        self,
        candidate: RecoveryCandidate,
        *,
        now: datetime,
    ) -> bool: ...


class RecoveryQueue(Protocol):
    async def send(self, payload: dict[str, str]) -> None: ...


class AsyncAutomationReconciler:
    def __init__(
        self,
        store: AutomationStore,
        queue: RecoveryQueue,
        *,
        stale_seconds: int = 120,
    ) -> None:
        if stale_seconds < 1:
            raise ValueError("stale_seconds must be positive")
        self.store = store
        self.queue = queue
        self.stale_seconds = stale_seconds

    async def reconcile(self, *, now: datetime) -> AutomationRecoveryResult:
        candidates = await self.store.list_recovery_candidates(
            now=now,
            stale_before=now - timedelta(seconds=self.stale_seconds),
        )
        requeued = 0
        terminalized = 0
        already_recorded = 0

        for candidate in candidates:
            if await self.store.recovery_action_exists(candidate):
                already_recorded += 1
                continue

            if candidate.action == RECOVERY_EXPIRED_FINAL_TERMINAL:
                changed = await self.store.terminalize_expired_final_attempt(
                    candidate,
                    now=now,
                )
                if changed:
                    terminalized += 1
                    await self.store.record_recovery_action(
                        candidate,
                        created_at=now,
                    )
                continue
            await self.queue.send(
                {
                    "kind": "scheduled_radar_tick",
                    "workspace_id": candidate.workspace_id,
                    "tick_id": candidate.tick_id,
                    "logical_id": candidate.tick_id,
                }
            )
            await self.store.record_recovery_action(
                candidate,
                created_at=now,
            )
            requeued += 1

        return AutomationRecoveryResult(
            candidates=len(candidates),
            requeued=requeued,
            terminalized=terminalized,
            already_recorded=already_recorded,
        )