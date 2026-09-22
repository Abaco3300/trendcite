"""Core data model: normalised evidence items, topic clusters and briefs.

Layering note. :class:`EvidenceItem` is the *presentation* record: the sanitised,
displayable form of one thing a source showed us. Its canonical intelligence
counterpart is :class:`trendcite.observation.Observation`, which carries the same
facts plus explicit identity and time semantics. Identity itself is decided in one
place only, :mod:`trendcite.identity`; the properties below delegate there rather
than re-deriving keys.

:class:`Brief` is the Content Opportunity projection of a
:class:`trendcite.signal.SignalBrief`. It is a view of a signal, not the root
intelligence entity, and it stays the frozen public contract.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .identity import ObservationIdentity, resolve_identity, story_key_for_url
from .versions import CONTENT_OPPORTUNITY_SCORE_VERSION, engine_versions

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from .signal import SignalBrief


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
        so it counts as one story, not two. See :mod:`trendcite.identity`.
        """
        return story_key_for_url(self.url)

    @property
    def observation_identity(self) -> ObservationIdentity:
        """Canonical identity of this record: native id -> canonical URL -> fingerprint."""
        return resolve_identity(
            source=self.source,
            url=self.url,
            title=self.title,
            excerpt=self.excerpt,
            raw=self.raw,
        )

    @property
    def observation_id(self) -> str:
        """Stable id for this observation, used for dedup and cross-run history."""
        return self.observation_identity.observation_id

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
        # Additive join keys: they let a consumer line this evidence row up with the
        # canonical observation records carried under a brief's "signal".
        data["observation_id"] = self.observation_id
        data["story_key"] = self.story_key
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
    """A Content Opportunity Brief: the public projection of one evaluated signal.

    Every field below is part of the published contract and may only be added to.
    ``signal`` is the canonical intelligence record this brief projects; it is
    optional so that a brief can still be constructed (and rendered) without the
    signal layer.
    """

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
    signal: SignalBrief | None = None  # canonical signal this brief projects

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
            # Additive: the canonical signal behind this projection, or null when the
            # brief was built without the signal layer.
            "signal": self.signal.to_dict() if self.signal is not None else None,
        }


#: The domain name for what :class:`Brief` is. ``Brief`` stays the exported symbol so
#: existing imports keep working; this alias documents the projection relationship.
ContentOpportunityBrief = Brief


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
            # Additive: which deterministic algorithm versions produced this report.
            "engine": {
                "score_formula": CONTENT_OPPORTUNITY_SCORE_VERSION,
                "versions": engine_versions(),
            },
        }
