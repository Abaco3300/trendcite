"""Dormant VectURL linked-content client for TrendCite Pro.

This module is intentionally outside the scoring pipeline. VectURL enrichment is
supplemental context only: it never creates an EvidenceItem and therefore cannot
change TrendCite recency, engagement, corroboration, relevance or diversity scores.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .security import clean_text

CANONICAL_VECTURL_BASE = "https://vecturl.getistriade.com"
MAX_FRAGMENT_CHARS = 4000
MAX_FRAGMENTS = 20
MAX_PROVENANCE = 20


class VectURLClientError(RuntimeError):
    """Stable, credential-free VectURL client error."""


@dataclass(frozen=True)
class VectURLConfig:
    base_url: str
    consumer_id: str
    token: str
    timeout_seconds: float = 10.0
    poll_attempts: int = 40
    poll_interval_seconds: float = 0.5


@dataclass(frozen=True)
class LinkedContentProvenance:
    provenance_id: str | None
    origin_type: str | None
    method: str | None
    provider: str | None
    provider_product: str | None
    model: str | None
    source_ref: str | None
    created_at: str | None


@dataclass(frozen=True)
class LinkedContentEvidence:
    bundle_id: str
    source_url: str
    text_fragments: tuple[str, ...]
    provenance: tuple[LinkedContentProvenance, ...]
    quality_overall: float | None
    quality_completeness: float | None
    quality_provenance_coverage: float | None
    fulfilled_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    actual_cost_micro_usd: int | None


RequestJSON = Callable[
    [str, str, Mapping[str, str], Mapping[str, Any] | None, float],
    Mapping[str, Any],
]


def config_from_env(env: Mapping[str, str] | None = None) -> VectURLConfig | None:
    values = os.environ if env is None else env
    base_url = values.get("VECTURL_BASE_URL", "").strip().rstrip("/")
    consumer_id = values.get("VECTURL_CONSUMER_ID", "").strip()
    token = values.get("VECTURL_CONSUMER_TOKEN", "").strip()
    if not base_url or not consumer_id or not token:
        return None
    if base_url != CANONICAL_VECTURL_BASE:
        raise VectURLClientError("VECTURL_BASE_URL_NOT_ALLOWED")
    if len(token) < 16:
        raise VectURLClientError("VECTURL_TOKEN_INVALID")
    return VectURLConfig(base_url=base_url, consumer_id=consumer_id, token=token)


def _urllib_request_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any] | None,
    timeout: float,
) -> Mapping[str, Any]:
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    request = urllib.request.Request(url, data=payload, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise VectURLClientError("VECTURL_RESPONSE_TOO_LARGE")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VectURLClientError("VECTURL_NETWORK_ERROR") from exc

    if not 200 <= status < 300:
        raise VectURLClientError(f"VECTURL_HTTP_{status}")
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise VectURLClientError("VECTURL_JSON_INVALID") from exc
    if not isinstance(parsed, dict):
        raise VectURLClientError("VECTURL_RESPONSE_INVALID")
    return parsed


class VectURLClient:
    def __init__(
        self,
        config: VectURLConfig,
        request_json: RequestJSON | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._request_json = request_json or _urllib_request_json
        self._sleep = sleep

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        headers = {
            "content-type": "application/json",
            "x-vecturl-consumer-id": self.config.consumer_id,
            "authorization": f"Bearer {self.config.token}",
        }
        return self._request_json(
            method,
            self.config.base_url + path,
            headers,
            body,
            self.config.timeout_seconds,
        )

    def acquire_linked_content(self, url: str) -> LinkedContentEvidence:
        started = self._request(
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
        for attempt in range(self.config.poll_attempts):
            status = self._request("GET", f"/v1/ingestions/{job_id}")
            state = status.get("status")
            if state == "failed":
                raise VectURLClientError("VECTURL_JOB_FAILED")
            candidate = status.get("bundleId")
            if state in {"ready", "partial"} and isinstance(candidate, str) and candidate:
                bundle_id = candidate
                break
            if attempt + 1 < self.config.poll_attempts:
                self._sleep(self.config.poll_interval_seconds)
        if bundle_id is None:
            raise VectURLClientError("VECTURL_POLL_TIMEOUT")

        bundle = self._request("GET", f"/v1/content/{bundle_id}")
        if bundle.get("schema") != "vecturl.evidence_bundle.v1":
            raise VectURLClientError("VECTURL_BUNDLE_INVALID")
        return linked_content_from_bundle(bundle)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def linked_content_from_bundle(bundle: Mapping[str, Any]) -> LinkedContentEvidence:
    if bundle.get("schema") != "vecturl.evidence_bundle.v1":
        raise VectURLClientError("VECTURL_BUNDLE_INVALID")
    bundle_id = bundle.get("bundleId")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise VectURLClientError("VECTURL_BUNDLE_INVALID")

    source = bundle.get("source")
    source_url = ""
    if isinstance(source, dict):
        for key in ("canonicalUrl", "resolvedUrl", "submittedUrl"):
            candidate = source.get(key)
            if isinstance(candidate, str) and candidate:
                source_url = candidate
                break
    if not source_url:
        raise VectURLClientError("VECTURL_SOURCE_URL_MISSING")

    fragments: list[str] = []
    evidence = bundle.get("evidence")
    if isinstance(evidence, list):
        for item in evidence[:MAX_FRAGMENTS]:
            if not isinstance(item, dict):
                continue
            raw = item.get("text")
            if isinstance(raw, str):
                cleaned = clean_text(raw, MAX_FRAGMENT_CHARS)
                if cleaned:
                    fragments.append(cleaned)

    provenance_rows: list[LinkedContentProvenance] = []
    provenance = bundle.get("provenance")
    if isinstance(provenance, list):
        for item in provenance[:MAX_PROVENANCE]:
            if not isinstance(item, dict):
                continue
            provenance_rows.append(
                LinkedContentProvenance(
                    provenance_id=item.get("provenanceId")
                    if isinstance(item.get("provenanceId"), str)
                    else None,
                    origin_type=item.get("originType")
                    if isinstance(item.get("originType"), str)
                    else None,
                    method=item.get("method") if isinstance(item.get("method"), str) else None,
                    provider=item.get("provider")
                    if isinstance(item.get("provider"), str)
                    else None,
                    provider_product=item.get("providerProduct")
                    if isinstance(item.get("providerProduct"), str)
                    else None,
                    model=item.get("model") if isinstance(item.get("model"), str) else None,
                    source_ref=item.get("sourceRef")
                    if isinstance(item.get("sourceRef"), str)
                    else None,
                    created_at=item.get("createdAt")
                    if isinstance(item.get("createdAt"), str)
                    else None,
                )
            )

    quality = bundle.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    processing = bundle.get("processing")
    processing = processing if isinstance(processing, dict) else {}
    cost = bundle.get("cost")
    cost = cost if isinstance(cost, dict) else {}

    fulfilled = processing.get("fulfilledCapabilities")
    missing = processing.get("missingCapabilities")
    actual = cost.get("actualMicroUsd")

    return LinkedContentEvidence(
        bundle_id=bundle_id,
        source_url=source_url,
        text_fragments=tuple(fragments),
        provenance=tuple(provenance_rows),
        quality_overall=_number(quality.get("overall")),
        quality_completeness=_number(quality.get("completeness")),
        quality_provenance_coverage=_number(quality.get("provenanceCoverage")),
        fulfilled_capabilities=tuple(x for x in fulfilled if isinstance(x, str))
        if isinstance(fulfilled, list)
        else (),
        missing_capabilities=tuple(x for x in missing if isinstance(x, str))
        if isinstance(missing, list)
        else (),
        actual_cost_micro_usd=int(actual)
        if isinstance(actual, int) and not isinstance(actual, bool)
        else None,
    )
