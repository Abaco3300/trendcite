"""Core data model: normalised evidence items, topic clusters and briefs."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class EvidenceItem:
    """One piece of retrieved evidence, normalised across sources.

    ``title`` and ``excerpt`` are untrusted text that has been cleaned and bounded
    by :mod:`trendcite.security`; they must be treated as data, never instructions.
    """

    source: str  # adapter id, e.g. "hackernews", "rss", "github", "reddit"
    source_label: str  # human label for the concrete feed/channel, e.g. "r/startups"
    title: str
    excerpt: str
    url: str  # canonical URL of the item (article, repo, discussion)
    published_at: datetime
    fetched_at: datetime
    author: str | None = None
    discussion_url: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)  # minimal audit metadata
    flags: tuple[str, ...] = ()

    @property
    def item_id(self) -> str:
        digest = hashlib.sha256(f"{self.source}|{self.url}|{self.title}".encode()).hexdigest()
        return digest[:12]

    @property
    def story_key(self) -> str:
        """Identity of the underlying content, independent of the channel it came through.

        The same article seen via Hacker News and via an HN RSS mirror shares one key,
        so it counts as one story, not two. Scheme, ``www.`` and a trailing slash are
        ignored; the stored ``url`` is unchanged.
        """
        parts = urlsplit(self.url)
        host = (parts.hostname or "").removeprefix("www.")
        path = parts.path.rstrip("/")
        return f"{host}{path}?{parts.query}" if parts.query else f"{host}{path}"

    @property
    def publisher(self) -> str:
        """Independent publisher key used for diversity (feed/subreddit/repo owner)."""
        return f"{self.source}:{self.source_label}"

    def engagement(self) -> float | None:
        """Source-specific raw engagement, or ``None`` if the source exposes none."""
        m = self.metrics
        if self.source in {"hackernews", "reddit"} and ("points" in m or "score" in m):
            return m.get("points", m.get("score", 0.0)) + 0.5 * m.get("comments", 0.0)
        if self.source == "github" and "stars" in m:
            return m["stars"] + 0.25 * m.get("forks", 0.0)
        return None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = self.item_id
        data["published_at"] = self.published_at.isoformat()
        data["fetched_at"] = self.fetched_at.isoformat()
        data["flags"] = list(self.flags)
        return data


@dataclass(frozen=True)
class ScoreBreakdown:
    recency: float
    engagement: float
    corroboration: float
    relevance: float
    diversity: float
    total: float  # 0..100
    confidence: str  # "high" | "medium" | "low"
    # Counts over the scored (= displayed) evidence set, so every claim is checkable.
    evidence_items: int = 0
    unique_urls: int = 0
    sources: tuple[str, ...] = ()
    independent_sources: int = 0
    publishers: int = 0
    cohesive: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sources"] = list(self.sources)
        return data


@dataclass
class TopicCluster:
    key: str  # normalised seed term, e.g. "mcp server"
    label: str  # display label
    items: list[EvidenceItem]
    related_terms: list[str] = field(default_factory=list)
    niche_matches: list[str] = field(default_factory=list)
    score: ScoreBreakdown | None = None
    # Displayed evidence; the score is computed over exactly these items.
    evidence: list[EvidenceItem] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return sorted({i.source for i in self.items})


@dataclass
class Brief:
    rank: int
    topic: str
    angle: str
    why_now: list[str]
    evidence: list[EvidenceItem]
    score: ScoreBreakdown
    score_explanation: list[str]
    counterpoints: list[str]
    founder_questions: list[str]
    outline: list[str]  # DRAFT, not evidence
    flags: list[str] = field(default_factory=list)
    synthesis_note: str | None = None  # set when an LLM refined angle/outline

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "topic": self.topic,
            "angle": self.angle,
            "why_now": self.why_now,
            "evidence": [e.to_dict() for e in self.evidence],
            "score": self.score.to_dict(),
            "score_explanation": self.score_explanation,
            "counterpoints": self.counterpoints,
            "founder_questions": self.founder_questions,
            "draft_outline_not_evidence": self.outline,
            "flags": self.flags,
            "synthesis_note": self.synthesis_note,
        }


@dataclass
class SourceStatus:
    source: str
    ok: bool
    items: int
    message: str = ""


@dataclass
class Report:
    generated_at: datetime
    mode: str  # "demo" | "live"
    niche: list[str]
    briefs: list[Brief]
    source_status: list[SourceStatus]
    total_items: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "trendcite",
            "generated_at": self.generated_at.isoformat(),
            "mode": self.mode,
            "niche": self.niche,
            "total_items": self.total_items,
            "source_status": [asdict(s) for s in self.source_status],
            "notes": self.notes,
            "briefs": [b.to_dict() for b in self.briefs],
        }
