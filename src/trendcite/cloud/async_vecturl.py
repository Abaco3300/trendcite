"""Async VectURL client used by the Cloudflare runtime.

Networking is injected by the Worker. The request contract is zero-cost and
best-effort; failures are handled by the caller as supplemental-context failures.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Protocol

from ..vecturl import LinkedContentEvidence, linked_content_from_bundle


class AsyncVectURLTransport(Protocol):
    async def request_json(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


class AsyncVectURLClient:
    def __init__(
        self,
        transport: AsyncVectURLTransport,
        *,
        poll_attempts: int = 12,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        if poll_attempts < 1:
            raise ValueError("poll_attempts must be positive")
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must not be negative")
        self.transport = transport
        self.poll_attempts = poll_attempts
        self.poll_interval_seconds = poll_interval_seconds

    async def acquire_linked_content(self, url: str) -> LinkedContentEvidence:
        started = await self.transport.request_json(
            "POST",
            "/v1/ingestions",
            {
                "url": url,
                "request": {
                    "required": ["metadata", "text"],
                    "profile": "balanced",
                    "maxCostMicroUsd": 0,
                    "policyProfile": "best_effort",
                },
            },
        )
        if started.get("schema") != "vecturl.ingestion_accept.v1":
            raise RuntimeError("vecturl_start_invalid")
        job_id = started.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise RuntimeError("vecturl_start_invalid")

        bundle_id: str | None = None
        for attempt in range(self.poll_attempts):
            status = await self.transport.request_json(
                "GET",
                "/v1/ingestions/" + job_id,
            )
            state = status.get("status")
            candidate = status.get("bundleId")
            if state == "failed":
                raise RuntimeError("vecturl_job_failed")
            if state in {"ready", "partial"} and isinstance(candidate, str) and candidate:
                bundle_id = candidate
                break
            if attempt + 1 < self.poll_attempts:
                await asyncio.sleep(self.poll_interval_seconds)

        if bundle_id is None:
            raise RuntimeError("vecturl_poll_timeout")

        bundle = await self.transport.request_json(
            "GET",
            "/v1/content/" + bundle_id,
        )
        if bundle.get("schema") != "vecturl.evidence_bundle.v1":
            raise RuntimeError("vecturl_bundle_invalid")
        return linked_content_from_bundle(bundle)
