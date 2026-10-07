from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trendcite.cloud.async_http import fetch_bytes_async
from trendcite.cloud.async_sources import (
    AsyncCollectorSet,
    AsyncGitHubCollector,
    AsyncHackerNewsCollector,
    AsyncRedditCollector,
    AsyncRSSCollector,
    AsyncSourceExecutionServiceImpl,
    AsyncXCollector,
    collect_async,
)
from trendcite.cloud.domain.radar import RadarVersion
from trendcite.config import Config
from trendcite.vecturl import linked_content_from_bundle

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
FIXTURES = Path("src/trendcite/fixtures")


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


class FixtureTransport:
    def __init__(self) -> None:
        self.hn_records = json.loads((FIXTURES / "demo_hackernews.json").read_text())
        self.github = (FIXTURES / "demo_github.json").read_bytes()
        self.rss = (FIXTURES / "demo_rss.xml").read_bytes()
        self.reddit_saas = (FIXTURES / "demo_reddit_saas.xml").read_bytes()
        self.reddit_devs = (FIXTURES / "demo_reddit_devs.xml").read_bytes()
        self.calls: list[str] = []

    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
    ) -> tuple[int, bytes]:
        self.calls.append(url)
        assert timeout > 0
        assert "User-Agent" in headers
        if url.endswith("/topstories.json"):
            ids = [record["id"] for record in self.hn_records]
            return 200, json.dumps(ids).encode()
        if "/item/" in url:
            item_id = int(url.rsplit("/", 1)[-1].split(".", 1)[0])
            record = next(row for row in self.hn_records if row["id"] == item_id)
            return 200, json.dumps(record).encode()
        if "api.github.com/search/repositories" in url:
            return 200, self.github
        if url == "https://example.com/feed.xml":
            return 200, self.rss
        if "/r/SaaS/" in url:
            return 200, self.reddit_saas
        if "/r/ExperiencedDevs/" in url:
            return 200, self.reddit_devs
        return 404, b""


def _radar(sources: list[str]) -> RadarVersion:
    return RadarVersion.create(
        radar_id="radar-1",
        workspace_id="ws-1",
        version_number=1,
        watchlist_version_ids=["watchlist-version-1"],
        sources=sources,
        niche=["ai agents", "developer tools", "startups", "saas"],
        top=5,
        created_at=NOW,
    )


def test_async_http_retries_without_blocking_sleep() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def transport(url: str, timeout: float, headers: dict[str, str]) -> tuple[int, bytes]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return 503, b""
        return 200, b"ok"

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    body = _run(
        fetch_bytes_async(
            "https://example.com/data",
            transport=transport,
            retries=1,
            backoff=0.25,
            sleep=sleep,
        )
    )

    assert body == b"ok"
    assert attempts == 2
    assert sleeps == [0.25]


def test_each_async_collector_reuses_canonical_normalizers() -> None:
    transport = FixtureTransport()

    hn = _run(AsyncHackerNewsCollector(transport, limit=30).collect(NOW))
    gh = _run(AsyncGitHubCollector(transport, ["ai agent"]).collect(NOW))
    rss = _run(AsyncRSSCollector(transport, ["https://example.com/feed.xml"]).collect(NOW))
    reddit = _run(AsyncRedditCollector(transport, ["SaaS", "ExperiencedDevs"]).collect(NOW))

    assert hn and all(item.source == "hackernews" for item in hn)
    assert gh and all(item.source == "github" for item in gh)
    assert rss and all(item.source == "rss" for item in rss)
    assert reddit and all(item.source == "reddit" for item in reddit)


def test_collect_async_degrades_one_source_without_failing_run() -> None:
    transport = FixtureTransport()
    collectors = (
        AsyncRSSCollector(transport, ["https://example.com/feed.xml"]),
        AsyncXCollector(),
    )

    items, statuses = _run(collect_async(collectors, NOW))

    assert items
    assert statuses[0].source == "rss"
    assert statuses[0].ok is True
    assert statuses[1].source == "x"
    assert statuses[1].ok is False


def test_async_source_execution_service_builds_execution_batch_from_fixtures() -> None:
    transport = FixtureTransport()
    config = Config(
        feeds=["https://example.com/feed.xml"],
        subreddits=["SaaS", "ExperiencedDevs"],
        github_queries=["ai agent", "developer tools"],
        hn_limit=30,
        sources=["hackernews", "github", "rss", "reddit"],
        top=5,
    )
    service = AsyncSourceExecutionServiceImpl(transport, config=config)

    batch = _run(
        service.execute(
            _radar(["hackernews", "github", "rss", "reddit"]),
            evaluation_cutoff=NOW,
        )
    )

    assert batch.signals
    assert 3 <= len(batch.signals) <= 5
    assert {status.source for status in batch.source_status} == {
        "hackernews",
        "github",
        "rss",
        "reddit",
    }
    assert all(status.ok for status in batch.source_status)


def test_collector_set_rejects_unknown_source() -> None:
    transport = FixtureTransport()
    collectors = AsyncCollectorSet(transport, Config())

    with pytest.raises(ValueError, match="unknown source"):
        collectors.for_radar(_radar(["unknown"]))


class FakeLinkedContentProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    async def acquire_linked_content(self, url: str):
        self.calls.append(url)
        if self.fail:
            raise RuntimeError("synthetic linked-content failure")
        return linked_content_from_bundle(
            {
                "schema": "vecturl.evidence_bundle.v1",
                "bundleId": "veb_" + str(len(self.calls)),
                "source": {"canonicalUrl": url},
                "evidence": [{"text": "supplemental linked context"}],
                "provenance": [],
                "quality": {
                    "overall": 1,
                    "completeness": 1,
                    "provenanceCoverage": 1,
                },
                "processing": {
                    "fulfilledCapabilities": ["metadata", "text"],
                    "missingCapabilities": [],
                },
                "cost": {"actualMicroUsd": 0},
            }
        )


def _fixture_config() -> Config:
    return Config(
        feeds=["https://example.com/feed.xml"],
        subreddits=["SaaS", "ExperiencedDevs"],
        github_queries=["ai agent", "developer tools"],
        hn_limit=30,
        sources=["hackernews", "github", "rss", "reddit"],
        top=5,
    )


def test_vecturl_enrichment_happens_after_scoring_and_does_not_mutate_signals() -> None:
    radar = _radar(["hackernews", "github", "rss", "reddit"])
    baseline = _run(
        AsyncSourceExecutionServiceImpl(
            FixtureTransport(),
            config=_fixture_config(),
        ).execute(radar, evaluation_cutoff=NOW)
    )
    provider = FakeLinkedContentProvider()
    enriched = _run(
        AsyncSourceExecutionServiceImpl(
            FixtureTransport(),
            config=_fixture_config(),
            linked_content_provider=provider,
            linked_content_limit=2,
        ).execute(radar, evaluation_cutoff=NOW)
    )

    assert [signal.to_dict() for signal in enriched.signals] == [
        signal.to_dict() for signal in baseline.signals
    ]
    assert len(enriched.linked_content) == 2
    assert len(provider.calls) == 2
    assert all(row.evidence.actual_cost_micro_usd == 0 for row in enriched.linked_content)


def test_vecturl_enrichment_failure_is_fail_open_for_normal_run() -> None:
    radar = _radar(["hackernews", "github", "rss", "reddit"])
    baseline = _run(
        AsyncSourceExecutionServiceImpl(
            FixtureTransport(),
            config=_fixture_config(),
        ).execute(radar, evaluation_cutoff=NOW)
    )
    provider = FakeLinkedContentProvider(fail=True)
    enriched = _run(
        AsyncSourceExecutionServiceImpl(
            FixtureTransport(),
            config=_fixture_config(),
            linked_content_provider=provider,
            linked_content_limit=2,
        ).execute(radar, evaluation_cutoff=NOW)
    )

    assert [signal.to_dict() for signal in enriched.signals] == [
        signal.to_dict() for signal in baseline.signals
    ]
    assert enriched.linked_content == ()
    assert provider.calls
