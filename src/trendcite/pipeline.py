"""Pipeline: collect -> normalise -> cluster -> score -> brief -> (optional LLM) -> report."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from .briefs import build_brief
from .cluster import cluster_items
from .config import Config
from .http import Transport
from .models import EvidenceItem, Report, SourceStatus
from .normalize import dedupe, parse_datetime
from .scoring import engagement_percentiles, rank_clusters
from .sources import (
    GitHubAdapter,
    HackerNewsAdapter,
    RedditAdapter,
    RSSAdapter,
    SourceAdapter,
    XAdapter,
)
from .sources.github import normalize_github_search
from .sources.hackernews import normalize_hn_item
from .sources.reddit import parse_reddit_feed
from .sources.rss import parse_feed

log = logging.getLogger("trendcite.pipeline")

MIN_BRIEFS = 3
MAX_BRIEFS = 5


def build_report(
    items: list[EvidenceItem],
    *,
    now: datetime,
    niche: list[str],
    top: int,
    mode: str,
    source_status: list[SourceStatus],
) -> Report:
    items = dedupe(items)
    top = max(MIN_BRIEFS, min(MAX_BRIEFS, top))
    ranked = rank_clusters(cluster_items(items), now=now, niche=niche, corpus=items)
    # Quality gate: publish only topics whose displayed evidence agrees on more than a
    # single word (scoring.evidence_is_cohesive). Suppressed candidates are listed.
    clusters = [c for c in ranked if c.score is not None and c.score.cohesive]
    suppressed = [c for c in ranked if c.score is not None and not c.score.cohesive]
    percentiles = engagement_percentiles(items)
    briefs = [build_brief(c, rank, now, percentiles) for rank, c in enumerate(clusters[:top], 1)]
    notes: list[str] = []
    if suppressed:
        shown = ", ".join(
            f'"{c.label}" ({c.score.total:.1f})' for c in suppressed[:5] if c.score is not None
        )
        notes.append(
            f"Quality gate: {len(suppressed)} candidate topic(s) not published because their "
            f"evidence shares only a single word, not a common story: {shown}"
            + (" and more." if len(suppressed) > 5 else ".")
        )
    if len(briefs) < MIN_BRIEFS:
        notes.append(
            f"Only {len(briefs)} corroborated topic(s) found "
            f"(target is {MIN_BRIEFS}-{MAX_BRIEFS}). "
            "TrendCite does not pad results with uncorroborated single items."
        )
    return Report(
        generated_at=now,
        mode=mode,
        niche=niche,
        briefs=briefs,
        source_status=source_status,
        total_items=len(items),
        notes=notes,
    )


# ----------------------------------------------------------------------------- demo


def _fixture(name: str) -> bytes:
    return resources.files("trendcite").joinpath("fixtures", name).read_bytes()


def load_demo_items() -> tuple[list[EvidenceItem], datetime, list[str], list[SourceStatus]]:
    """Run the real parsers over bundled fixtures. No network access."""
    meta: dict[str, Any] = json.loads(_fixture("demo_meta.json"))
    now = parse_datetime(meta["reference_time"])
    assert now is not None
    files = meta["files"]
    status: list[SourceStatus] = []
    items: list[EvidenceItem] = []

    hn = [normalize_hn_item(r, now) for r in json.loads(_fixture(files["hackernews"]))]
    hn_items = [i for i in hn if i is not None]
    status.append(SourceStatus("hackernews", True, len(hn_items), "fixture"))
    gh_items = normalize_github_search(json.loads(_fixture(files["github"])), now)
    status.append(SourceStatus("github", True, len(gh_items), "fixture"))
    rss_items = parse_feed(
        _fixture(files["rss"]), feed_url="https://example.com/feed.xml", fetched_at=now
    )
    status.append(SourceStatus("rss", True, len(rss_items), "fixture"))
    reddit_items = parse_reddit_feed(_fixture(files["reddit_saas"]), "SaaS", now)
    reddit_items += parse_reddit_feed(_fixture(files["reddit_devs"]), "ExperiencedDevs", now)
    status.append(SourceStatus("reddit", True, len(reddit_items), "fixture"))
    status.append(SourceStatus("x", False, 0, "optional interface only; not used in demo"))
    items = hn_items + gh_items + rss_items + reddit_items
    return items, now, list(meta["niche"]), status


# ----------------------------------------------------------------------------- live


def make_adapters(cfg: Config, transport: Transport | None = None) -> list[SourceAdapter]:
    available: dict[str, SourceAdapter] = {
        "hackernews": HackerNewsAdapter(limit=cfg.hn_limit, transport=transport),
        "github": GitHubAdapter(cfg.github_queries, transport=transport),
        "rss": RSSAdapter(cfg.feeds, transport=transport),
        "reddit": RedditAdapter(cfg.subreddits, transport=transport),
        "x": XAdapter(transport=transport),
    }
    unknown = [s for s in cfg.sources if s not in available]
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(unknown)}")
    return [available[s] for s in cfg.sources]


def collect(
    adapters: list[SourceAdapter], now: datetime
) -> tuple[list[EvidenceItem], list[SourceStatus]]:
    """Collect from every adapter; failures are recorded, never fatal."""
    items: list[EvidenceItem] = []
    status: list[SourceStatus] = []
    for adapter in adapters:
        try:
            got = adapter.collect(now)
        except Exception as exc:
            log.warning("source %s unavailable: %s", adapter.name, exc)
            status.append(SourceStatus(adapter.name, False, 0, str(exc)[:200]))
            continue
        items.extend(got)
        status.append(SourceStatus(adapter.name, True, len(got), ""))
    return items, status


def run_live(
    cfg: Config, transport: Transport | None = None, now: datetime | None = None
) -> Report:
    now = now or datetime.now(UTC).replace(microsecond=0)
    items, status = collect(make_adapters(cfg, transport), now)
    return build_report(
        items, now=now, niche=cfg.niche, top=cfg.top, mode="live", source_status=status
    )


def run_demo(top: int = 5, niche: list[str] | None = None) -> Report:
    items, now, demo_niche, status = load_demo_items()
    return build_report(
        items,
        now=now,
        niche=niche if niche is not None else demo_niche,
        top=top,
        mode="demo",
        source_status=status,
    )
