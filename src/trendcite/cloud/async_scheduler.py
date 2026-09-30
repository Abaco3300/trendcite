"""Async scheduled execution for the Cloudflare worker plane.

This module mirrors the semantics of :mod:`trendcite.cloud.orchestration` without
wrapping the synchronous SQLite application in an active event loop.

The database tick is the idempotency authority for scheduled work. Queue delivery is
at-least-once, so a duplicate message is harmless: only one worker can win the atomic
tick claim. A worker that loses a claim for unfinished work asks the transport to retry
later; it must not ACK the message merely because another live lease exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .domain.radar import RUN_SUCCEEDED
from .domain.scheduling import (
    SKIP_SCHEDULE_DISABLED,
    DuePlan,
    RadarSchedule,
    ScheduleTick,
    plan_due,
)
from .errors import NotFoundError, safe_error


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class AsyncQueuePublisher(Protocol):
    async def send(self, payload: dict[str, str]) -> None: ...


class AsyncRadarRunner(Protocol):
    """Persist one logical radar run and return its durable verdict.

    Implementations own RadarRun idempotency and the persistence of signals, matches,
    relevance, usage and alert candidates. The scheduler deliberately knows none of
    those details.
    """

    async def run_radar(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        evaluation_cutoff: datetime,
    ) -> AsyncRunResult: ...


class AsyncScheduleStore(Protocol):
    async def list_enabled_schedules(self) -> tuple[RadarSchedule, ...]: ...

    async def persist_plan(
        self,
        schedule: RadarSchedule,
        plan: DuePlan,
        *,
        now: datetime,
    ) -> tuple[ScheduleTick, ...]:
        """Persist due/skipped ticks and return only newly-created pending ticks."""
        ...

    async def get_tick(self, workspace_id: str, tick_id: str) -> ScheduleTick | None: ...

    async def get_schedule(self, workspace_id: str, schedule_id: str) -> RadarSchedule | None: ...

    async def claim_tick(
        self,
        *,
        workspace_id: str,
        tick_id: str,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...

    async def settle_tick(
        self,
        tick: ScheduleTick,
        *,
        expected_owner: str,
    ) -> bool: ...


@dataclass(frozen=True)
class AsyncRunResult:
    run_id: str
    status: str
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class PlannedSchedule:
    schedule_id: str
    workspace_id: str
    radar_id: str
    created_tick_ids: tuple[str, ...]
    skipped_count: int


@dataclass(frozen=True)
class AsyncPlanningResult:
    schedules: tuple[PlannedSchedule, ...]
    enqueued: int


@dataclass(frozen=True)
class AsyncTickOutcome:
    tick_id: str
    workspace_id: str
    claimed: bool
    status: str
    run_id: str = ""
    settled: bool = True
    retry_transport: bool = False
    requeued: bool = False

    @property
    def terminal(self) -> bool:
        return self.status in {"succeeded", "skipped"} or (
            self.status == "failed" and not self.requeued
        )


class AsyncScheduledCoordinator:
    """Plan, enqueue, claim, execute, settle and retry scheduled radar work."""

    def __init__(
        self,
        store: AsyncScheduleStore,
        queue: AsyncQueuePublisher,
        runner: AsyncRadarRunner,
        *,
        worker_id: str,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id is required")
        self.store = store
        self.queue = queue
        self.runner = runner
        self.worker_id = worker_id

    async def plan_and_enqueue(self, *, now: datetime | None = None) -> AsyncPlanningResult:
        instant = now if now is not None else utc_now()
        summaries: list[PlannedSchedule] = []
        enqueued = 0

        for schedule in await self.store.list_enabled_schedules():
            plan = plan_due(schedule, now=instant)
            created = await self.store.persist_plan(schedule, plan, now=instant)
            for tick in created:
                await self.queue.send(_tick_payload(tick))
                enqueued += 1
            summaries.append(
                PlannedSchedule(
                    schedule_id=schedule.schedule_id,
                    workspace_id=schedule.workspace_id,
                    radar_id=schedule.radar_id,
                    created_tick_ids=tuple(t.tick_id for t in created),
                    skipped_count=len(plan.skipped),
                )
            )

        return AsyncPlanningResult(schedules=tuple(summaries), enqueued=enqueued)

    async def execute_message(
        self,
        payload: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> AsyncTickOutcome:
        workspace_id = _required(payload, "workspace_id")
        tick_id = _required(payload, "tick_id")
        instant = now if now is not None else utc_now()

        tick = await self.store.get_tick(workspace_id, tick_id)
        if tick is None:
            raise NotFoundError("schedule tick not found in workspace")

        if tick.finished:
            return AsyncTickOutcome(
                tick_id=tick.tick_id,
                workspace_id=workspace_id,
                claimed=False,
                status=tick.status,
                run_id=tick.run_id,
            )

        schedule = await self.store.get_schedule(workspace_id, tick.schedule_id)
        if schedule is None:
            raise NotFoundError("schedule tick has no schedule in this workspace")

        won = await self.store.claim_tick(
            workspace_id=workspace_id,
            tick_id=tick.tick_id,
            owner=self.worker_id,
            now=instant,
            lease_expires_at=instant + schedule.lease,
        )
        if not won:
            # An unfinished tick may be running under another worker. ACKing here could
            # lose the only transport delivery if that worker dies before settlement.
            latest = await self.store.get_tick(workspace_id, tick_id)
            if latest is not None and latest.finished:
                return AsyncTickOutcome(
                    tick_id=tick_id,
                    workspace_id=workspace_id,
                    claimed=False,
                    status=latest.status,
                    run_id=latest.run_id,
                )
            return AsyncTickOutcome(
                tick_id=tick_id,
                workspace_id=workspace_id,
                claimed=False,
                status=tick.status,
                retry_transport=True,
                settled=False,
            )

        claimed = tick.claimed(owner=self.worker_id, now=instant, lease=schedule.lease)

        if not schedule.enabled:
            settled_tick = claimed.skipped(reason=SKIP_SCHEDULE_DISABLED, now=instant)
            persisted = await self.store.settle_tick(
                settled_tick,
                expected_owner=self.worker_id,
            )
            return AsyncTickOutcome(
                tick_id=tick_id,
                workspace_id=workspace_id,
                claimed=True,
                status=settled_tick.status,
                settled=persisted,
                retry_transport=not persisted,
            )

        try:
            run = await self.runner.run_radar(
                workspace_id=workspace_id,
                radar_id=claimed.radar_id,
                evaluation_cutoff=claimed.evaluation_cutoff,
            )
        except Exception as exc:
            code, detail = safe_error(exc)
            failed = claimed.failed(code=code, detail=detail, now=instant)
            return await self._settle_failure(failed)

        if run.status == RUN_SUCCEEDED:
            settled_tick = claimed.succeeded(run_id=run.run_id, now=instant)
            persisted = await self.store.settle_tick(
                settled_tick,
                expected_owner=self.worker_id,
            )
            return AsyncTickOutcome(
                tick_id=tick_id,
                workspace_id=workspace_id,
                claimed=True,
                status=settled_tick.status,
                run_id=run.run_id,
                settled=persisted,
                retry_transport=not persisted,
            )

        failed = claimed.failed(
            code=run.error_code or "RunNotSucceeded",
            detail=run.error_detail or f"radar run ended {run.status}",
            run_id=run.run_id,
            now=instant,
        )
        return await self._settle_failure(failed)

    async def _settle_failure(self, failed: ScheduleTick) -> AsyncTickOutcome:
        persisted = await self.store.settle_tick(
            failed,
            expected_owner=self.worker_id,
        )
        if not persisted:
            return AsyncTickOutcome(
                tick_id=failed.tick_id,
                workspace_id=failed.workspace_id,
                claimed=True,
                status=failed.status,
                run_id=failed.run_id,
                settled=False,
                retry_transport=True,
            )

        requeued = False
        if failed.retryable:
            await self.queue.send(_tick_payload(failed))
            requeued = True

        return AsyncTickOutcome(
            tick_id=failed.tick_id,
            workspace_id=failed.workspace_id,
            claimed=True,
            status=failed.status,
            run_id=failed.run_id,
            settled=True,
            requeued=requeued,
        )


def _tick_payload(tick: ScheduleTick) -> dict[str, str]:
    return {
        "kind": "scheduled_radar_tick",
        "workspace_id": tick.workspace_id,
        "tick_id": tick.tick_id,
        "logical_id": tick.tick_id,
    }


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"missing queue field: {key}")
    return value
