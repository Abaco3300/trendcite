"""Pipeline: the one place the whole chain is assembled.

    Source -> Observation -> Cluster -> CandidateSignal -> Signal
           -> SignalEvaluation -> SignalSnapshot -> SignalBrief
           -> ContentOpportunityBrief -> Report

The public Content Opportunity behaviour is unchanged: the same clusters are ranked by
the same public score, the same 3-5 briefs are published, and the same Markdown comes
out. The signal layer runs alongside it and is attached to each brief, so the report
now carries both the projection people read and the canonical intelligence record it
was projected from.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from .briefs import build_brief
from .cluster import cluster_items
from .config import Config
from .history import HistoryStore, NullHistoryStore
from .http import Transport
from .models import EvidenceItem, Report, SourceStatus, TopicCluster
from .normalize import dedupe, parse_datetime
from .observation import Observation, observe
from .scoring import (
    engagement_percentiles,
    rank_clusters,
    relevance_score,
    select_evidence,
)
from .signal import CandidateSignal, SignalBrief
from .signal_scoring import build_signal_brief
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


def candidate_from_cluster(
    cluster: TopicCluster, *, now: datetime, evidence: list[EvidenceItem]
) -> CandidateSignal:
    """Promote a scored cluster to a candidate signal over its displayed evidence.

    The candidate is built from exactly the evidence the brief shows, so the signal
    evaluation is checkable against the same links the reader sees.
    """
    return CandidateSignal(
        key=cluster.key,
        label=cluster.label,
        observations=tuple(observe(evidence, ingested_at=now)),
        related_terms=tuple(cluster.related_terms),
        cohesive=cluster.score.cohesive if cluster.score is not None else True,
    )


def build_report(
    items: list[EvidenceItem],
    *,
    now: datetime,
    niche: list[str],
    top: int,
    mode: str,
    source_status: list[SourceStatus],
    history: HistoryStore | None = None,
) -> Report:
    store: HistoryStore = history or NullHistoryStore()
    items = dedupe(items)
    top = max(MIN_BRIEFS, min(MAX_BRIEFS, top))
    ranked = rank_clusters(cluster_items(items), now=now, niche=niche, corpus=items)
    # Quality gate: publish only topics whose displayed evidence agrees on more than a
    # single word (scoring.evidence_is_cohesive). Suppressed candidates are listed.
    clusters = [c for c in ranked if c.score is not None and c.score.cohesive]
    suppressed = [c for c in ranked if c.score is not None and not c.score.cohesive]
    percentiles = engagement_percentiles(items)
    corpus: list[Observation] = observe(items, ingested_at=now)
    published = list(enumerate(clusters[:top], 1))
    signals: list[SignalBrief] = []
    for _, cluster in published:
        evidence = cluster.evidence or select_evidence(cluster.items, percentiles, now)
        candidate = candidate_from_cluster(cluster, now=now, evidence=evidence)
        signals.append(
            build_signal_brief(
                candidate,
                now=now,
                corpus=corpus,
                percentiles=percentiles,
                relevance=relevance_score(cluster.niche_matches, niche),
                history=store.signal_history(candidate.signal_id),
            )
        )
    briefs = [
        build_brief(cluster, rank, now, percentiles, signal)
        for (rank, cluster), signal in zip(published, signals, strict=True)
    ]
    # Append-only: this run's evaluations become the previous run's history.
    store.append_signal_snapshots([s.snapshot for s in signals])
    store.append_observation_snapshots(
        [snap for s in signals for snap in s.observation_snapshots()]
    )
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
    cfg: Config,
    transport: Transport | None = None,
    now: datetime | None = None,
    history: HistoryStore | None = None,
) -> Report:
    now = now or datetime.now(UTC).replace(microsecond=0)
    items, status = collect(make_adapters(cfg, transport), now)
    return build_report(
        items,
        now=now,
        niche=cfg.niche,
        top=cfg.top,
        mode="live",
        source_status=status,
        history=history,
    )


def run_demo(
    top: int = 5, niche: list[str] | None = None, history: HistoryStore | None = None
) -> Report:
    """Offline demo. With no history store the run writes nothing and touches no disk."""
    items, now, demo_niche, status = load_demo_items()
    return build_report(
        items,
        now=now,
        niche=niche if niche is not None else demo_niche,
        top=top,
        mode="demo",
        source_status=status,
        history=history,
    )
