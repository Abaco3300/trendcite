"""Async VectURL linked-content enrichment for TrendCite nonprod.

This module runs only after the Signal Engine has completed scoring. Its output is
supplemental context and is never converted into EvidenceItem or fed back into
recency, engagement, corroboration, relevance or diversity.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlparse

from ..models import Report
from ..vecturl import LinkedContentEvidence, VectURLClientError, linked_content_from_bundle
from .application import LinkedContentEnrichment

MAX_ENRICHMENTS_PER_RUN = 3
CANONICAL_VECTURL_BASE = "https://vecturl.getistriade.com"


class AsyncVectURLTransport(Protocol):
    async def __call__(
        self,
        method: str,
        url: str,
        timeout: float,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> tuple[int, bytes]: ...


class AsyncVectURLClient:
    def __init__(
        self,
        *,
        transport: AsyncVectURLTransport,
        consumer_id: str,
        token: str,
        base_url: str = CANONICAL_VECTURL_BASE,
        timeout_seconds: float = 10.0,
        poll_attempts: int = 20,
        poll_interval_seconds: float = 0.5,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        base = base_url.strip().rstrip("/")
        if base != CANONICAL_VECTURL_BASE:
            raise VectURLClientError("VECTURL_BASE_URL_NOT_ALLOWED")
        if consumer_id != "trendcite-nonprod":
            raise VectURLClientError("VECTURL_CONSUMER_ID_NOT_ALLOWED")
        if len(token.strip()) < 16:
            raise VectURLClientError("VECTURL_TOKEN_INVALID")
        self.transport = transport
        self.consumer_id = consumer_id
        self.token = token.strip()
        self.base_url = base
        self.timeout_seconds = timeout_seconds
        self.poll_attempts = poll_attempts
        self.poll_interval_seconds = poll_interval_seconds
        self.sleep = sleep

    async def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        status, raw = await self.transport(
            method,
            self.base_url + path,
            self.timeout_seconds,
            {
                "content-type": "application/json",
                "x-vecturl-consumer-id": self.consumer_id,
                "authorization": "Bearer " + self.token,
            },
            payload,
        )
        if not 200 <= status < 300:
            raise VectURLClientError(f"VECTURL_HTTP_{status}")
        if len(raw) > 2_000_000:
            raise VectURLClientError("VECTURL_RESPONSE_TOO_LARGE")
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise VectURLClientError("VECTURL_JSON_INVALID") from exc
        if not isinstance(parsed, dict):
            raise VectURLClientError("VECTURL_RESPONSE_INVALID")
        return parsed

    async def acquire(self, url: str) -> LinkedContentEvidence:
        started = await self._request(
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
            raise VectURLClientError("VECTURL_START_RESPONSE_INVALID")
        job_id = started.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise VectURLClientError("VECTURL_START_RESPONSE_INVALID")

        bundle_id: str | None = None
        for attempt in range(self.poll_attempts):
            status = await self._request("GET", f"/v1/ingestions/{job_id}")
            state = status.get("status")
            candidate = status.get("bundleId")
            if state == "failed":
                raise VectURLClientError("VECTURL_JOB_FAILED")
            if state in {"ready", "partial"} and isinstance(candidate, str) and candidate:
                bundle_id = candidate
                break
            if attempt + 1 < self.poll_attempts:
                await self.sleep(self.poll_interval_seconds)
        if bundle_id is None:
            raise VectURLClientError("VECTURL_POLL_TIMEOUT")

        bundle = await self._request("GET", f"/v1/content/{bundle_id}")
        return linked_content_from_bundle(bundle)


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def enrich_report_linked_content(
    report: Report,
    client: AsyncVectURLClient,
    *,
    limit: int = MAX_ENRICHMENTS_PER_RUN,
) -> tuple[LinkedContentEnrichment, ...]:
    """Enrich already-scored briefs without changing the report or its scores."""

    selected: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for brief in report.briefs:
        if brief.signal is None:
            continue
        for evidence in brief.evidence:
            url = evidence.url.strip()
            if not _is_public_http_url(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            selected.append((brief.signal.signal.signal_id, url))
            break
        if len(selected) >= max(0, min(limit, MAX_ENRICHMENTS_PER_RUN)):
            break

    rows: list[LinkedContentEnrichment] = []
    for signal_id, url in selected:
        try:
            linked = await client.acquire(url)
            provenance_json = json.dumps(
                [
                    {
                        "provenance_id": row.provenance_id,
                        "origin_type": row.origin_type,
                        "method": row.method,
                        "provider": row.provider,
                        "provider_product": row.provider_product,
                        "model": row.model,
                        "source_ref": row.source_ref,
                        "created_at": row.created_at,
                    }
                    for row in linked.provenance
                ],
                separators=(",", ":"),
                sort_keys=True,
            )
            rows.append(
                LinkedContentEnrichment(
                    signal_id=signal_id,
                    source_url=linked.source_url,
                    status="ready",
                    bundle_id=linked.bundle_id,
                    text_fragments=linked.text_fragments,
                    provenance_json=provenance_json,
                    quality_overall=linked.quality_overall,
                    actual_cost_micro_usd=linked.actual_cost_micro_usd or 0,
                )
            )
        except Exception as exc:
            code = str(exc)
            if not code.startswith("VECTURL_"):
                code = type(exc).__name__.upper()
            rows.append(
                LinkedContentEnrichment(
                    signal_id=signal_id,
                    source_url=url,
                    status="failed",
                    error_code=code[:120],
                )
            )
    return tuple(rows)
