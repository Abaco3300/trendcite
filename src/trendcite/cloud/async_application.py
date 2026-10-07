"""Async application boundary for scheduled Cloud radar execution.

The synchronous CloudApplication remains the OSS/SQLite reference. This module carries
its run-level semantics into an event-loop-safe contract without pretending that the
existing synchronous repository graph can be called from a Worker.

Detailed Signal Engine output persistence lives behind AsyncExecutionPipeline. The
runner owns run identity, retry state and safe failure transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from .async_scheduler import AsyncRadarRunner, AsyncRunResult
from .domain.entitlements import CAP_RADAR_RUN, EntitlementDecision
from .domain.radar import RUN_FAILED, RUN_SUCCEEDED, RadarRun
from .errors import EntitlementDeniedError, NotFoundError, safe_error


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class AsyncRunRepository(Protocol):
    async def get_or_create_run(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        evaluation_cutoff: datetime,
        started_at: datetime,
    ) -> RadarRun:
        """Return the single logical run for (workspace, radar version, cutoff)."""
        ...

    async def get_run(self, workspace_id: str, run_id: str) -> RadarRun | None: ...

    async def update_run(self, run: RadarRun) -> None: ...


class AsyncEntitlementGate(Protocol):
    async def resolve_capability(
        self,
        workspace_id: str,
        capability_key: str,
        *,
        at: datetime,
    ) -> EntitlementDecision: ...


class AsyncExecutionPipeline(Protocol):
    async def execute_and_persist(self, run: RadarRun) -> RadarRun:
        """Execute the pinned radar version and atomically persist its durable result.

        A successful return must be a persisted succeeded RadarRun. Implementations own
        signals, snapshots, relevance, matches, coverage, usage and alert-candidate
        persistence. Delivery itself remains downstream.
        """
        ...


class AsyncCloudApplicationRunner(AsyncRadarRunner):
    """Run-level async semantics equivalent to CloudApplication.run_radar()."""

    def __init__(
        self,
        runs: AsyncRunRepository,
        pipeline: AsyncExecutionPipeline,
        entitlements: AsyncEntitlementGate | None = None,
    ) -> None:
        self.runs = runs
        self.pipeline = pipeline
        self.entitlements = entitlements

    async def run_radar(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        evaluation_cutoff: datetime,
    ) -> AsyncRunResult:
        now = utc_now()
        if self.entitlements is not None:
            decision = await self.entitlements.resolve_capability(
                workspace_id,
                CAP_RADAR_RUN,
                at=now,
            )
            if not decision.allowed:
                raise EntitlementDeniedError(f"{CAP_RADAR_RUN} denied: {decision.reason}")
        run = await self.runs.get_or_create_run(
            workspace_id=workspace_id,
            radar_id=radar_id,
            evaluation_cutoff=evaluation_cutoff,
            started_at=now,
        )

        if run.status == RUN_SUCCEEDED:
            return _result(run)

        if run.status == RUN_FAILED:
            current = await self.runs.get_run(workspace_id, run.run_id)
            if current is None:
                raise NotFoundError("radar run disappeared before retry")
            run = current.retrying(started_at=now)
            await self.runs.update_run(run)

        try:
            finished = await self.pipeline.execute_and_persist(run)
        except Exception as exc:
            code, detail = safe_error(exc)
            current = await self.runs.get_run(workspace_id, run.run_id)
            if current is None:
                raise NotFoundError("radar run disappeared after execution failure") from exc
            if current.status == RUN_SUCCEEDED:
                return _result(current)
            failed = current.failed(code=code, detail=detail, finished_at=utc_now())
            await self.runs.update_run(failed)
            return _result(failed)

        if finished.run_id != run.run_id or finished.workspace_id != workspace_id:
            raise RuntimeError("async execution pipeline returned a different logical run")
        if finished.status != RUN_SUCCEEDED:
            raise RuntimeError("async execution pipeline must persist and return a succeeded run")
        return _result(finished)


def _result(run: RadarRun) -> AsyncRunResult:
    return AsyncRunResult(
        run_id=run.run_id,
        status=run.status,
        error_code=run.error_code,
        error_detail=run.error_detail,
    )
