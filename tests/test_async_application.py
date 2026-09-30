from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trendcite.cloud.async_application import AsyncCloudApplicationRunner
from trendcite.cloud.domain.radar import (
    RUN_COVERAGE_COMPLETE,
    RUN_FAILED,
    RUN_SUCCEEDED,
    RadarRun,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


class FakeRuns:
    def __init__(self) -> None:
        self.run: RadarRun | None = None
        self.updates: list[RadarRun] = []

    async def get_or_create_run(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        evaluation_cutoff: datetime,
        started_at: datetime,
    ) -> RadarRun:
        if self.run is None:
            self.run = RadarRun.create(
                workspace_id=workspace_id,
                radar_id=radar_id,
                radar_version_id="radar-version-1",
                evaluation_cutoff=evaluation_cutoff,
                started_at=started_at,
            )
        return self.run

    async def get_run(self, workspace_id: str, run_id: str) -> RadarRun | None:
        if self.run is None:
            return None
        if self.run.workspace_id != workspace_id or self.run.run_id != run_id:
            return None
        return self.run

    async def update_run(self, run: RadarRun) -> None:
        self.run = run
        self.updates.append(run)


class FakePipeline:
    def __init__(self, outcomes: list[str | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    async def execute_and_persist(self, run: RadarRun) -> RadarRun:
        self.calls.append(run.run_id)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "success":
            finished = run.succeeded(
                coverage_state=RUN_COVERAGE_COMPLETE,
                signal_count=3,
                match_count=2,
                finished_at=NOW,
            )
            return finished
        raise AssertionError(f"unknown fake outcome: {outcome}")


def test_successful_run_is_not_executed_twice() -> None:
    runs = FakeRuns()
    pipeline = FakePipeline(["success"])
    runner = AsyncCloudApplicationRunner(runs, pipeline)

    first = _run(
        runner.run_radar(
            workspace_id="ws-1",
            radar_id="radar-1",
            evaluation_cutoff=NOW,
        )
    )
    assert first.status == RUN_SUCCEEDED
    assert runs.run is not None
    # The pipeline contract says success is already durable.
    runs.run = runs.run.succeeded(
        coverage_state=RUN_COVERAGE_COMPLETE,
        signal_count=3,
        match_count=2,
        finished_at=NOW,
    )

    second = _run(
        runner.run_radar(
            workspace_id="ws-1",
            radar_id="radar-1",
            evaluation_cutoff=NOW,
        )
    )
    assert second.run_id == first.run_id
    assert second.status == RUN_SUCCEEDED
    assert len(pipeline.calls) == 1


def test_failed_run_retries_same_run_identity() -> None:
    runs = FakeRuns()
    pipeline = FakePipeline([RuntimeError("transient"), "success"])
    runner = AsyncCloudApplicationRunner(runs, pipeline)

    first = _run(
        runner.run_radar(
            workspace_id="ws-1",
            radar_id="radar-1",
            evaluation_cutoff=NOW,
        )
    )
    assert first.status == RUN_FAILED
    assert runs.run is not None
    first_id = runs.run.run_id
    assert runs.run.attempt == 1

    second = _run(
        runner.run_radar(
            workspace_id="ws-1",
            radar_id="radar-1",
            evaluation_cutoff=NOW,
        )
    )
    assert second.status == RUN_SUCCEEDED
    assert second.run_id == first_id
    assert runs.run is not None
    assert runs.run.attempt == 2
    assert pipeline.calls == [first_id, first_id]


def test_pipeline_failure_is_converted_to_safe_failed_run() -> None:
    runs = FakeRuns()
    pipeline = FakePipeline([RuntimeError("secret-value-should-not-be-structural")])
    runner = AsyncCloudApplicationRunner(runs, pipeline)

    result = _run(
        runner.run_radar(
            workspace_id="ws-1",
            radar_id="radar-1",
            evaluation_cutoff=NOW,
        )
    )

    assert result.status == RUN_FAILED
    assert result.error_code
    assert runs.run is not None
    assert runs.run.status == RUN_FAILED


def test_pipeline_cannot_swap_logical_run_identity() -> None:
    runs = FakeRuns()

    class BadPipeline:
        async def execute_and_persist(self, run: RadarRun) -> RadarRun:
            return RadarRun.create(
                workspace_id=run.workspace_id,
                radar_id=run.radar_id,
                radar_version_id="another-version",
                evaluation_cutoff=run.evaluation_cutoff,
                started_at=NOW,
            ).succeeded(
                coverage_state=RUN_COVERAGE_COMPLETE,
                signal_count=0,
                match_count=0,
                finished_at=NOW,
            )

    runner = AsyncCloudApplicationRunner(runs, BadPipeline())

    try:
        _run(
            runner.run_radar(
                workspace_id="ws-1",
                radar_id="radar-1",
                evaluation_cutoff=NOW,
            )
        )
    except RuntimeError as exc:
        assert "different logical run" in str(exc)
    else:
        raise AssertionError("identity swap must be rejected")
