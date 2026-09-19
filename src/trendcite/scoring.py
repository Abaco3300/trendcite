"""Deterministic, documented cluster scoring.

The score is computed over the cluster's *evidence set*: the (at most MAX_EVIDENCE)
items shown in the brief, chosen by :func:`select_evidence`. Every number a brief
claims can therefore be checked against the evidence it displays.

Every component is in [0, 1]; the total is a weighted sum scaled to 0-100.

    score = 100 * (0.25*R + 0.25*E + 0.25*C + 0.15*V + 0.10*D)

R  recency        mean over items of 0.5 ** (age_hours / 48)  (48 h half-life;
                  future-dated items count as age 0)
E  engagement     mean of the top-3 item engagement percentiles, where each item's
                  percentile is computed *within its own source* over everything
                  collected in the run (so 400 HN points and 1,800 GitHub stars are
                  never compared directly). Percentile = (below + 0.5*equal) / n.
                  Sources without metrics (RSS, Reddit feeds) are excluded; a
                  cluster with no measurable items gets UNKNOWN_ENGAGEMENT (0.25).
C  corroboration  *independent* sources: the largest number of source adapters that
                  can each be paired with a different underlying URL (story_key).
                  1 -> 0.0, 2 -> 0.5, >=3 -> 1.0. One link mirrored via Hacker News
                  and an HN RSS feed is one independent source, not two.
V  relevance      distinct niche phrases matched in the evidence feature text:
                  min(1, matches/2); 0.5 (neutral) when no niche is configured
D  diversity      distinct publishers (feed / subreddit / repo owner / HN):
                  min(1, (publishers - 1) / 3)

Confidence:
  high    independent sources >= 3 (C = 1.0) and unique URLs >= 4 and publishers >= 3,
          and at least one niche phrase matched when a niche is configured, and the
          evidence is cohesive (see :func:`evidence_is_cohesive`)
  medium  independent sources >= 2 or unique URLs >= 3
  low     otherwise
A single-source cluster can never be high confidence.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .models import EvidenceItem, ScoreBreakdown, TopicCluster
from .text import agreement_terms, extract_terms, item_text, phrase_in, tokenize

MAX_EVIDENCE = 6


@dataclass(frozen=True)
class Weights:
    recency: float = 0.25
    engagement: float = 0.25
    corroboration: float = 0.25
    relevance: float = 0.15
    diversity: float = 0.10

    def as_dict(self) -> dict[str, float]:
        return {
            "recency": self.recency,
            "engagement": self.engagement,
            "corroboration": self.corroboration,
            "relevance": self.relevance,
            "diversity": self.diversity,
        }


WEIGHTS = Weights()
HALF_LIFE_HOURS = 48.0
UNKNOWN_ENGAGEMENT = 0.25
NEUTRAL_RELEVANCE = 0.5


def age_hours(item: EvidenceItem, now: datetime) -> float:
    return max(0.0, (now - item.published_at).total_seconds() / 3600.0)


def recency_score(items: list[EvidenceItem], now: datetime) -> float:
    if not items:
        return 0.0
    return sum(float(0.5 ** (age_hours(i, now) / HALF_LIFE_HOURS)) for i in items) / len(items)


def engagement_percentiles(corpus: list[EvidenceItem]) -> dict[str, float]:
    """Map item_id -> percentile of its engagement within its own source."""
    by_source: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for item in corpus:
        value = item.engagement()
        if value is not None:
            by_source[item.source].append((item.item_id, value))
    out: dict[str, float] = {}
    for values in by_source.values():
        n = len(values)
        numbers = [v for _, v in values]
        for item_id, v in values:
            below = sum(1 for x in numbers if x < v)
            equal = sum(1 for x in numbers if x == v)
            out[item_id] = (below + 0.5 * equal) / n
    return out


def engagement_score(items: list[EvidenceItem], percentiles: dict[str, float]) -> float:
    values = sorted(
        (percentiles[i.item_id] for i in items if i.item_id in percentiles), reverse=True
    )
    if not values:
        return UNKNOWN_ENGAGEMENT
    top = values[:3]
    return sum(top) / len(top)


def _source_url_matching(items: list[EvidenceItem]) -> dict[str, str]:
    """Maximum matching of sources to distinct story keys (deterministic augmenting paths)."""
    keys_by_source: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if item.story_key not in keys_by_source[item.source]:
            keys_by_source[item.source].append(item.story_key)
    owner: dict[str, str] = {}  # story_key -> source

    def augment(source: str, seen: set[str]) -> bool:
        for key in keys_by_source[source]:
            if key in seen:
                continue
            seen.add(key)
            if key not in owner or augment(owner[key], seen):
                owner[key] = source
                return True
        return False

    for source in sorted(keys_by_source):
        augment(source, set())
    return {source: key for key, source in owner.items()}


def independent_sources(items: list[EvidenceItem]) -> int:
    """Sources that each contribute a different underlying URL (see module docstring)."""
    return len(_source_url_matching(items))


def unique_urls(items: list[EvidenceItem]) -> int:
    return len({i.story_key for i in items})


def corroboration_score(items: list[EvidenceItem]) -> float:
    n = independent_sources(items)
    return 0.0 if n <= 1 else 0.5 if n == 2 else 1.0


def select_evidence(
    items: list[EvidenceItem],
    percentiles: dict[str, float],
    now: datetime,
    limit: int = MAX_EVIDENCE,
) -> list[EvidenceItem]:
    """Choose the displayed (and scored) evidence, stratified by source.

    1. For every source in the independent-source matching, its best item for the
       matched URL, so every source that earns corroboration is shown.
    2. Then the best remaining items that add a new URL *and* a new publisher,
    3. then items that add a new URL, 4. then anything else, in rank order
       (engagement percentile, then recency, then id).
    """
    ranked = sorted(
        items, key=lambda i: (-percentiles.get(i.item_id, -1.0), age_hours(i, now), i.item_id)
    )
    matching = _source_url_matching(ranked)
    chosen: list[EvidenceItem] = []
    for source, key in sorted(matching.items()):
        chosen.append(next(i for i in ranked if i.source == source and i.story_key == key))
    chosen = sorted(chosen, key=ranked.index)[:limit]

    def fill(*, new_publisher: bool) -> None:
        for item in ranked:
            if len(chosen) >= limit:
                return
            if item in chosen or item.story_key in {c.story_key for c in chosen}:
                continue
            if new_publisher and item.publisher in {c.publisher for c in chosen}:
                continue
            chosen.append(item)

    fill(new_publisher=True)
    fill(new_publisher=False)
    for item in ranked:
        if len(chosen) >= limit:
            break
        if item not in chosen:
            chosen.append(item)
    return sorted(chosen, key=ranked.index)


def evidence_is_cohesive(
    seed: str, items: list[EvidenceItem], term_sets: list[set[str]] | None = None
) -> bool:
    """True if the items agree on more than the single seed word.

    A multi-word seed phrase is agreement in itself. For a single-word seed, items are
    grouped by underlying URL, and every URL must share an agreement term (a specific
    word or phrase beyond the seed, see ``text.agreement_terms``) with *more than half*
    of the other URLs. Chains (A~B via one term, B~C via another) do not pass.
    """
    if " " in seed:
        return True
    if term_sets is None:
        term_sets = [extract_terms(item_text(i)) for i in items]
    groups: dict[str, set[str]] = defaultdict(set)
    for item, terms in zip(items, term_sets, strict=True):
        groups[item.story_key] |= agreement_terms(terms, seed)
    keys = sorted(groups)
    for key in keys:
        agreeing = sum(1 for other in keys if other != key and groups[key] & groups[other])
        if 2 * agreeing <= len(keys) - 1:
            return False
    return True


def niche_matches(items: list[EvidenceItem], niche: list[str]) -> list[str]:
    tokens: list[str] = []
    for item in items:
        tokens.extend(tokenize(item_text(item)))
        tokens.append("\x00")  # prevent phrases spanning two items
    return sorted({n for n in niche if n.strip() and phrase_in(n, tokens)})


def relevance_score(matches: list[str], niche: list[str]) -> float:
    if not [n for n in niche if n.strip()]:
        return NEUTRAL_RELEVANCE
    return min(1.0, len(matches) / 2)


def diversity_score(items: list[EvidenceItem]) -> float:
    publishers = len({i.publisher for i in items})
    return min(1.0, max(0, publishers - 1) / 3)


def confidence_label(
    corroboration: float,
    n_unique_urls: int,
    n_publishers: int,
    *,
    niche_matched: bool = True,
    cohesive: bool = True,
) -> str:
    """``corroboration`` is the C component: 0.5 = 2 and 1.0 = 3+ independent sources."""
    if (
        corroboration >= 1.0
        and n_unique_urls >= 4
        and n_publishers >= 3
        and niche_matched
        and cohesive
    ):
        return "high"
    if corroboration >= 0.5 or n_unique_urls >= 3:
        return "medium"
    return "low"


def score_cluster(
    cluster: TopicCluster,
    *,
    now: datetime,
    niche: list[str],
    percentiles: dict[str, float],
    weights: Weights = WEIGHTS,
) -> ScoreBreakdown:
    items = select_evidence(cluster.items, percentiles, now)
    cluster.evidence = items
    matches = niche_matches(items, niche)
    cluster.niche_matches = matches
    r = recency_score(items, now)
    e = engagement_score(items, percentiles)
    c = corroboration_score(items)
    v = relevance_score(matches, niche)
    d = diversity_score(items)
    total = 100 * (
        weights.recency * r
        + weights.engagement * e
        + weights.corroboration * c
        + weights.relevance * v
        + weights.diversity * d
    )
    n_urls = unique_urls(items)
    n_publishers = len({i.publisher for i in items})
    cohesive = evidence_is_cohesive(cluster.key, items)
    has_niche = any(n.strip() for n in niche)
    return ScoreBreakdown(
        recency=round(r, 3),
        engagement=round(e, 3),
        corroboration=round(c, 3),
        relevance=round(v, 3),
        diversity=round(d, 3),
        total=round(total, 1),
        confidence=confidence_label(
            c,
            n_urls,
            n_publishers,
            niche_matched=bool(matches) or not has_niche,
            cohesive=cohesive,
        ),
        evidence_items=len(items),
        unique_urls=n_urls,
        sources=tuple(sorted({i.source for i in items})),
        independent_sources=independent_sources(items),
        publishers=n_publishers,
        cohesive=cohesive,
    )


def rank_clusters(
    clusters: list[TopicCluster], *, now: datetime, niche: list[str], corpus: list[EvidenceItem]
) -> list[TopicCluster]:
    percentiles = engagement_percentiles(corpus)
    for cluster in clusters:
        cluster.score = score_cluster(cluster, now=now, niche=niche, percentiles=percentiles)
    return sorted(clusters, key=lambda c: (-(c.score.total if c.score else 0.0), c.key))
