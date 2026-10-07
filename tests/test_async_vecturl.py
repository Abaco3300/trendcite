from __future__ import annotations

from typing import Any

from trendcite.cloud.async_vecturl import AsyncVectURLClient


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, body))
        if method == "POST":
            return {
                "schema": "vecturl.ingestion_accept.v1",
                "jobId": "job_async_1",
                "status": "queued",
            }
        if path.endswith("/job_async_1"):
            return {
                "schema": "vecturl.ingestion_status.v1",
                "jobId": "job_async_1",
                "status": "ready",
                "bundleId": "veb_async_1",
            }
        return {
            "schema": "vecturl.evidence_bundle.v1",
            "bundleId": "veb_async_1",
            "source": {"canonicalUrl": "https://example.com/article"},
            "evidence": [{"text": "bounded linked content"}],
            "provenance": [],
            "quality": {"overall": 1, "completeness": 1, "provenanceCoverage": 1},
            "processing": {
                "fulfilledCapabilities": ["metadata", "text"],
                "missingCapabilities": [],
            },
            "cost": {"actualMicroUsd": 0},
        }


def test_async_client_uses_zero_cost_best_effort_contract() -> None:
    transport = FakeTransport()
    linked = _run(
        AsyncVectURLClient(
            transport,
            poll_attempts=2,
            poll_interval_seconds=0,
        ).acquire_linked_content("https://example.com/article")
    )

    assert linked.bundle_id == "veb_async_1"
    assert linked.actual_cost_micro_usd == 0
    assert len(transport.calls) == 3
    request = transport.calls[0][2]
    assert request is not None
    assert request["request"]["maxCostMicroUsd"] == 0
    assert request["request"]["policyProfile"] == "best_effort"
    assert request["request"]["required"] == ["metadata", "text"]
