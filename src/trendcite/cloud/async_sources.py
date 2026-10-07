"""Async source collectors for the Cloudflare execution plane."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

from ..config import Config
from ..models import EvidenceItem, SourceStatus
from ..pipeline import build_report
from ..sources.base import SourceUnavailable
from ..sources.github import SEARCH, normalize_github_search
from ..sources.hackernews import API, normalize_hn_item
from ..sources.reddit import _SUB_RE, parse_reddit_feed
from ..sources.reddit import FEED as REDDIT_FEED
from ..sources.rss import parse_feed
from .application import ExecutionBatch
from .async_execution import AsyncSignalExecutionService
from .vecturl_enrichment import AsyncVectURLClient, enrich_report_linked_content
from .async_http import AsyncHTTPTransport, fetch_bytes_async, fetch_json_async
from .domain.radar import RadarVersion

log = logging.getLogger("trendcite.cloud.async_sources")


class AsyncSourceCollector:
    name = "base"

    async def collect(self, now: datetime) -> list[EvidenceItem]:
        raise NotImplementedError


class AsyncHackerNewsCollector(AsyncSourceCollector):
    name = "hackernews"

    def __init__(
        self,
        transport: AsyncHTTPTransport,
        *,
        limit: int = 30,
        lists: tuple[str, ...] = ("topstories",),
    ) -> None:
        self.transport = transport
        self.limit = max(1, min(limit, 100))
        self.lists = tuple(
            name for name in lists if name in {"topstories", "newstories", "beststories"}
        )

    async def collect(self, now: datetime) -> list[EvidenceItem]:
        ids: list[int] = []
        for list_name in self.lists or ("topstories",):
            try:
                data = await fetch_json_async(
                    f"{API}/{list_name}.json",
                    transport=self.transport,
                )
            except Exception as exc:
                raise SourceUnavailable(f"Hacker News unavailable: {exc}") from exc
            if isinstance(data, list):
                ids.extend(value for value in data[: self.limit] if isinstance(value, int))

        items: list[EvidenceItem] = []
        for item_id in dict.fromkeys(ids):
            try:
                record = await fetch_json_async(
                    f"{API}/item/{item_id}.json",
                    transport=self.transport,
                    retries=1,
                )
            except Exception as exc:
                log.debug("Hacker News item %s unavailable: %s", item_id, exc)
                continue
            item = normalize_hn_item(record, now)
            if item is not None:
                items.append(item)
        return items


class AsyncGitHubCollector(AsyncSourceCollector):
    name = "github"

    def __init__(
        self,
        transport: AsyncHTTPTransport,
        queries: list[str],
        *,
        days: int = 14,
        per_query: int = 15,
    ) -> None:
        self.transport = transport
        self.queries = list(queries)
        self.days = days
        self.per_query = max(1, min(per_query, 50))

    async def collect(self, now: datetime) -> list[EvidenceItem]:
        if not self.queries:
            raise SourceUnavailable("no GitHub queries configured")
        since = (now - timedelta(days=self.days)).date().isoformat()
        items: list[EvidenceItem] = []
        errors: list[str] = []
        for query in self.queries[:5]:
            encoded = quote(f"{query} created:>={since}", safe="")
            try:
                payload = await fetch_json_async(
                    SEARCH.format(q=encoded, n=self.per_query),
                    transport=self.transport,
                )
            except Exception as exc:
                errors.append(str(exc))
                continue
            items.extend(normalize_github_search(payload, now))
        if not items and errors:
            raise SourceUnavailable("GitHub search unavailable: " + "; ".join(errors))
        return items


class AsyncRSSCollector(AsyncSourceCollector):
    name = "rss"

    def __init__(self, transport: AsyncHTTPTransport, feeds: list[str]) -> None:
        self.transport = transport
        self.feeds = list(feeds)

    async def collect(self, now: datetime) -> list[EvidenceItem]:
        if not self.feeds:
            raise SourceUnavailable("no feeds configured")
        items: list[EvidenceItem] = []
        errors: list[str] = []
        for feed in self.feeds:
            try:
                body = await fetch_bytes_async(feed, transport=self.transport)
                items.extend(parse_feed(body, feed_url=feed, fetched_at=now))
            except Exception as exc:
                errors.append(f"{feed}: {exc}")
        if not items and errors:
            raise SourceUnavailable("; ".join(errors))
        return items


class AsyncRedditCollector(AsyncSourceCollector):
    name = "reddit"

    def __init__(self, transport: AsyncHTTPTransport, subreddits: list[str]) -> None:
        self.transport = transport
        self.subreddits = [name for name in subreddits if _SUB_RE.match(name)]

    async def collect(self, now: datetime) -> list[EvidenceItem]:
        if not self.subreddits:
            raise SourceUnavailable("no valid subreddits configured")
        items: list[EvidenceItem] = []
        errors: list[str] = []
        for sub in self.subreddits[:10]:
            try:
                body = await fetch_bytes_async(
                    REDDIT_FEED.format(sub=sub),
                    transport=self.transport,
                    retries=1,
                )
                items.extend(parse_reddit_feed(body, sub, now))
            except Exception as exc:
                errors.append(f"r/{sub}: {exc}")
        if not items:
            raise SourceUnavailable("Reddit unavailable: " + ("; ".join(errors) or "no items"))
        return items


class AsyncXCollector(AsyncSourceCollector):
    name = "x"

    async def collect(self, now: datetime) -> list[EvidenceItem]:
        raise SourceUnavailable(
            "X adapter remains interface-only; official authenticated API not configured"
        )


@dataclass(frozen=True)
class AsyncCollectorSet:
    transport: AsyncHTTPTransport
    config: Config

    def for_radar(self, radar: RadarVersion) -> tuple[AsyncSourceCollector, ...]:
        available: dict[str, AsyncSourceCollector] = {
            "hackernews": AsyncHackerNewsCollector(
                self.transport,
                limit=self.config.hn_limit,
            ),
            "github": AsyncGitHubCollector(
                self.transport,
                self.config.github_queries,
            ),
            "rss": AsyncRSSCollector(self.transport, self.config.feeds),
            "reddit": AsyncRedditCollector(self.transport, self.config.subreddits),
            "x": AsyncXCollector(),
        }
        unknown = [name for name in radar.sources if name not in available]
        if unknown:
            raise ValueError(f"unknown source(s): {', '.join(unknown)}")
        return tuple(available[name] for name in radar.sources)


async def collect_async(
    collectors: tuple[AsyncSourceCollector, ...],
    now: datetime,
) -> tuple[list[EvidenceItem], list[SourceStatus]]:
    """Collect all sources; one unavailable source never sinks the run."""

    items: list[EvidenceItem] = []
    statuses: list[SourceStatus] = []
    for collector in collectors:
        try:
            got = await collector.collect(now)
        except Exception as exc:
            log.warning("source %s unavailable: %s", collector.name, exc)
            statuses.append(SourceStatus(collector.name, False, 0, str(exc)[:200]))
            continue
        items.extend(got)
        statuses.append(SourceStatus(collector.name, True, len(got), ""))
    return items, statuses


class AsyncSourceExecutionServiceImpl(AsyncSignalExecutionService):
    """Produce the same Signal Engine output as the live pipeline, without sync I/O."""

    def __init__(
        self,
        transport: AsyncHTTPTransport,
        *,
        config: Config | None = None,
        vecturl_client: AsyncVectURLClient | None = None,
    ) -> None:
        self.collectors = AsyncCollectorSet(transport, config or Config())
        self.vecturl_client = vecturl_client

    async def execute(
        self,
        radar: RadarVersion,
        *,
        evaluation_cutoff: datetime,
    ) -> ExecutionBatch:
        items, statuses = await collect_async(
            self.collectors.for_radar(radar),
            evaluation_cutoff,
        )
        report = build_report(
            items,
            now=evaluation_cutoff,
            niche=list(radar.niche),
            top=radar.top,
            mode="cloud",
            source_status=statuses,
        )
        signals = tuple(brief.signal for brief in report.briefs if brief.signal is not None)
        linked_content = (
            await enrich_report_linked_content(report, self.vecturl_client)
            if self.vecturl_client is not None
            else ()
        )
        return ExecutionBatch(
            signals=signals,
            source_status=tuple(statuses),
            linked_content=linked_content,
        )
