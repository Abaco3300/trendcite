from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trendcite.cloud.vecturl_enrichment import enrich_report_linked_content
from trendcite.models import Report
from trendcite.pipeline import run_demo
from trendcite.vecturl import LinkedContentEvidence, LinkedContentProvenance


class _FakeVectURL:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.urls: list[str] = []

    async def acquire(self, url: str) -> LinkedContentEvidence:
        self.urls.append(url)
        if self.fail:
            raise RuntimeError("synthetic-vecturl-failure")
        return LinkedContentEvidence(
            bundle_id="veb_test",
            source_url=url,
            text_fragments=("supplemental text",),
            provenance=(
                LinkedContentProvenance(
                    provenance_id="p1",
                    origin_type="source",
                    method="public_http",
                    provider="public-http",
                    provider_product=None,
                    model=None,
                    source_ref=url,
                    created_at="2026-10-07T00:00:00Z",
                ),
            ),
            quality_overall=1.0,
            quality_completeness=1.0,
            quality_provenance_coverage=1.0,
            fulfilled_capabilities=("metadata", "text"),
            missing_capabilities=(),
            actual_cost_micro_usd=0,
        )


@pytest.mark.asyncio
async def test_linked_content_runs_after_scoring_and_cannot_mutate_scores() -> None:
    report = run_demo(top=5)
    before = [
        (
            brief.signal.signal_id if brief.signal is not None else None,
            brief.score.total,
            brief.score.recency,
            brief.score.engagement,
            brief.score.corroboration,
            brief.score.relevance,
            brief.score.diversity,
            tuple(item.item_id for item in brief.evidence),
        )
        for brief in report.briefs
    ]

    client = _FakeVectURL()
    linked = await enrich_report_linked_content(report, client, limit=3)

    after = [
        (
            brief.signal.signal_id if brief.signal is not None else None,
            brief.score.total,
            brief.score.recency,
            brief.score.engagement,
            brief.score.corroboration,
            brief.score.relevance,
            brief.score.diversity,
            tuple(item.item_id for item in brief.evidence),
        )
        for brief in report.briefs
    ]

    assert after == before
    assert len(linked) <= 3
    assert len(client.urls) == len(linked)
    assert all(row.status == "ready" for row in linked)
    assert all(row.actual_cost_micro_usd == 0 for row in linked)


@pytest.mark.asyncio
async def test_linked_content_failure_is_fail_open_and_separate() -> None:
    report: Report = run_demo(top=3)
    before = [brief.score.total for brief in report.briefs]

    linked = await enrich_report_linked_content(report, _FakeVectURL(fail=True), limit=1)

    assert [brief.score.total for brief in report.briefs] == before
    assert len(linked) == 1
    assert linked[0].status == "failed"
    assert linked[0].bundle_id == ""
    assert linked[0].text_fragments == ()
    assert linked[0].actual_cost_micro_usd == 0


def test_nonprod_runtime_flag_is_scoped_and_zero_cost_contract_is_static() -> None:
    from pathlib import Path
    import json

    root = Path(__file__).resolve().parents[1]
    config = json.loads(
        (root / "deploy" / "cloudflare" / "wrangler.nonprod.jsonc").read_text()
    )
    assert config["name"] == "trendcite-nonprod-runtime"
    assert config["vars"]["TRENDCITE_VECTURL_ENRICHMENT"] == "nonprod-enabled"

    source = (root / "src" / "trendcite" / "cloud" / "vecturl_enrichment.py").read_text()
    assert '"maxCostMicroUsd": 0' in source
    assert '"policyProfile": "best_effort"' in source
    assert "MAX_ENRICHMENTS_PER_RUN = 3" in source
