from __future__ import annotations

from typing import Any

import pytest

from trendcite.vecturl import (
    CANONICAL_VECTURL_BASE,
    VectURLClient,
    VectURLClientError,
    VectURLConfig,
    config_from_env,
    linked_content_from_bundle,
)


def test_config_is_fail_closed_and_pinned() -> None:
    assert config_from_env({}) is None
    with pytest.raises(VectURLClientError, match="VECTURL_BASE_URL_NOT_ALLOWED"):
        config_from_env(
            {
                "VECTURL_BASE_URL": "https://example.com",
                "VECTURL_CONSUMER_ID": "trendcite-nonprod",
                "VECTURL_CONSUMER_TOKEN": "x" * 32,
            }
        )
    cfg = config_from_env(
        {
            "VECTURL_BASE_URL": CANONICAL_VECTURL_BASE,
            "VECTURL_CONSUMER_ID": "trendcite-nonprod",
            "VECTURL_CONSUMER_TOKEN": "x" * 32,
        }
    )
    assert cfg is not None
    assert cfg.consumer_id == "trendcite-nonprod"


def test_bundle_mapping_is_bounded_and_separate_from_scoring() -> None:
    bundle: dict[str, Any] = {
        "schema": "vecturl.evidence_bundle.v1",
        "bundleId": "veb_test",
        "source": {"canonicalUrl": "https://example.com/article"},
        "evidence": [
            {
                "evidenceId": "ev1",
                "type": "source_quote",
                "originType": "source",
                "text": "x" * 5000,
            }
        ],
        "provenance": [
            {
                "provenanceId": "p1",
                "originType": "source",
                "method": "public_http",
                "provider": "public-http",
                "sourceRef": "https://example.com/article",
                "createdAt": "2026-10-07T00:00:00Z",
            }
        ],
        "quality": {"overall": 1, "completeness": 0.9, "provenanceCoverage": 1},
        "processing": {
            "fulfilledCapabilities": ["metadata", "text"],
            "missingCapabilities": [],
        },
        "cost": {"actualMicroUsd": 0},
    }
    linked = linked_content_from_bundle(bundle)
    assert linked.bundle_id == "veb_test"
    assert linked.source_url == "https://example.com/article"
    assert len(linked.text_fragments) == 1
    assert len(linked.text_fragments[0]) <= 4000
    assert linked.provenance[0].provider == "public-http"
    assert linked.actual_cost_micro_usd == 0
    assert not hasattr(linked, "metrics")
    assert not hasattr(linked, "engagement")


def test_client_uses_server_side_auth_and_zero_cost_contract() -> None:
    calls: list[tuple[str, str, dict[str, str], dict[str, Any] | None]] = []

    def fake_request(
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        del timeout
        calls.append((method, url, headers, body))
        if method == "POST":
            return {
                "schema": "vecturl.ingestion_accept.v1",
                "jobId": "job_1",
                "status": "queued",
            }
        if url.endswith("/v1/ingestions/job_1"):
            return {
                "schema": "vecturl.ingestion_status.v1",
                "jobId": "job_1",
                "status": "ready",
                "bundleId": "veb_1",
            }
        return {
            "schema": "vecturl.evidence_bundle.v1",
            "bundleId": "veb_1",
            "source": {"canonicalUrl": "https://example.com/article"},
            "evidence": [],
            "provenance": [],
            "quality": {"overall": 1, "completeness": 1, "provenanceCoverage": 1},
            "processing": {
                "fulfilledCapabilities": ["metadata", "text"],
                "missingCapabilities": [],
            },
            "cost": {"actualMicroUsd": 0},
        }

    client = VectURLClient(
        VectURLConfig(
            base_url=CANONICAL_VECTURL_BASE,
            consumer_id="trendcite-nonprod",
            token="server-secret-" + "x" * 24,
            poll_interval_seconds=0,
        ),
        request_json=fake_request,
        sleep=lambda _: None,
    )
    linked = client.acquire_linked_content("https://example.com/article")
    assert linked.bundle_id == "veb_1"
    assert len(calls) == 3
    assert calls[0][2]["x-vecturl-consumer-id"] == "trendcite-nonprod"
    assert calls[0][2]["authorization"].startswith("Bearer ")
    assert calls[0][3] is not None
    request = calls[0][3]["request"]
    assert request["maxCostMicroUsd"] == 0
    assert request["policyProfile"] == "best_effort"
    assert "server-secret" not in repr(linked)


def test_errors_never_echo_token_or_provider_body() -> None:
    secret = "server-secret-" + "x" * 24

    def denied(
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        del method, url, headers, body, timeout
        raise VectURLClientError("VECTURL_HTTP_403")

    client = VectURLClient(
        VectURLConfig(
            base_url=CANONICAL_VECTURL_BASE,
            consumer_id="trendcite-nonprod",
            token=secret,
        ),
        request_json=denied,
    )
    with pytest.raises(VectURLClientError) as caught:
        client.acquire_linked_content("https://example.com/article")
    assert secret not in str(caught.value)
