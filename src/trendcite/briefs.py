"""Turn scored clusters into Content Opportunity Briefs (deterministic templates).

Everything in a brief except the draft outline is derived from captured evidence
and computed scores. The outline is a writing aid and is labelled as such.
"""

from __future__ import annotations

from datetime import datetime

from .models import Brief, EvidenceItem, TopicCluster
from .scoring import HALF_LIFE_HOURS, WEIGHTS, age_hours, select_evidence
from .signal import SignalBrief
from .text import CRITICAL_RE

SOURCE_NAMES = {
    "hackernews": "Hacker News",
    "github": "GitHub",
    "rss": "RSS/Atom",
    "reddit": "Reddit",
    "x": "X",
}


def metric_summary(item: EvidenceItem) -> str:
    m = item.metrics
    if item.source == "hackernews":
        return f"{int(m.get('points', 0))} points, {int(m.get('comments', 0))} comments"
    if item.source == "github":
        return f"{int(m.get('stars', 0))} stars, {int(m.get('forks', 0))} forks"
    return "no engagement metrics available from this source"


def _source_list(sources: list[str]) -> str:
    return ", ".join(SOURCE_NAMES.get(s, s) for s in sources)


def _angle(cluster: TopicCluster) -> str:
    topic = cluster.label
    assert cluster.score is not None
    s = cluster.score
    sources = set(s.sources)
    if "github" in sources and sources & {"hackernews", "reddit"}:
        return (
            f"Builders are already shipping around {topic} while the discussion is still "
            f"unsettled: share what actually works (and what doesn't) from first-hand use."
        )
    if "reddit" in sources and s.engagement < 0.6:
        return (
            f"Practitioners are asking open questions about {topic}; answer them with your "
            f"own operating numbers and decisions rather than a summary of the debate."
        )
    if s.engagement >= 0.6 and s.corroboration >= 0.5:
        return (
            f"{topic} is drawing strong attention across communities; the useful angle is "
            f"what it changes for a small team this quarter."
        )
    return (
        f"{topic} is being covered by publishers; add a first-hand or contrarian take "
        f"that the existing coverage lacks."
    )


def _why_now(
    cluster: TopicCluster,
    evidence: list[EvidenceItem],
    now: datetime,
    percentiles: dict[str, float],
) -> list[str]:
    assert cluster.score is not None
    s = cluster.score
    items = evidence
    ages = [age_hours(i, now) for i in items]
    lines = [
        f"{len(items)} evidence item(s) shown and scored: {s.unique_urls} unique URL(s) from "
        f"{len(s.sources)} source(s) ({_source_list(list(s.sources))}); newest "
        f"{min(ages):.0f} h old, oldest {max(ages):.0f} h old."
    ]
    if len(cluster.items) > len(items):
        lines.append(
            f"{len(cluster.items)} items matched this topic in total; the rest are not "
            f"shown and do not affect the score."
        )
    measured = [i for i in items if i.item_id in percentiles]
    if measured:
        top = max(measured, key=lambda i: (percentiles[i.item_id], i.item_id))
        lines.append(
            f'Strongest engagement signal: "{top.title}" '
            f"({SOURCE_NAMES.get(top.source, top.source)}: "
            f"{metric_summary(top)}; engagement percentile {percentiles[top.item_id] * 100:.0f} "
            f"within that source this run)."
        )
    if cluster.niche_matches:
        lines.append("Matches your niche terms: " + ", ".join(cluster.niche_matches) + ".")
    if cluster.related_terms:
        lines.append("Co-occurring terms: " + ", ".join(cluster.related_terms) + ".")
    return lines


def _score_explanation(cluster: TopicCluster) -> list[str]:
    assert cluster.score is not None
    s = cluster.score
    w = WEIGHTS
    rows = [
        (
            "recency",
            w.recency,
            s.recency,
            f"{HALF_LIFE_HOURS:.0f} h half-life, averaged over items",
        ),
        ("engagement", w.engagement, s.engagement, "top-3 within-source percentiles"),
        (
            "corroboration",
            w.corroboration,
            s.corroboration,
            f"{s.independent_sources} independent source(s): sources that each link a "
            f"different URL",
        ),
        (
            "relevance",
            w.relevance,
            s.relevance,
            f"{len(cluster.niche_matches)} niche term(s) matched in the evidence",
        ),
        ("diversity", w.diversity, s.diversity, f"{s.publishers} distinct publisher(s)"),
    ]
    lines = [
        f"{name}: {value:.2f} x {weight:.2f} = {100 * value * weight:.1f} pts ({why})"
        for name, weight, value, why in rows
    ]
    lines.append(f"total: {s.total:.1f}/100, confidence {s.confidence}")
    lines.append(
        "all components are computed from the evidence items listed in this brief; high "
        "confidence requires >= 3 independent sources, >= 4 unique URLs, >= 3 publishers, "
        "a niche match (when a niche is set) and evidence that agrees on more than one word"
    )
    return lines


def _counterpoints(cluster: TopicCluster, evidence: list[EvidenceItem], now: datetime) -> list[str]:
    assert cluster.score is not None
    s = cluster.score
    notes: list[str] = []
    if s.independent_sources <= 1:
        where = _source_list(list(s.sources))
        if len(s.sources) > 1:
            notes.append(
                f"Seen via {where}, but they link the same underlying URL; that is one "
                f"story mirrored across channels, not independent corroboration."
            )
        else:
            notes.append(
                f"Only seen on {where}; this may be one community's echo chamber rather "
                f"than a broad trend."
            )
    mirrored = len(evidence) - s.unique_urls
    if mirrored > 0 and s.independent_sources > 1:
        notes.append(
            f"{mirrored} evidence item(s) repeat a URL already shown via another channel; "
            f"repeats are counted once for corroboration."
        )
    if s.unique_urls <= 2:
        notes.append(
            f"Small sample ({s.unique_urls} unique URL(s)). Treat as an early signal, not a trend."
        )
    if not any(i.engagement() is not None for i in evidence):
        notes.append("No engagement metrics are available for these sources; reach is unknown.")
    stale = [i for i in evidence if age_hours(i, now) > 7 * 24]
    if stale:
        notes.append(f"{len(stale)} item(s) are over a week old; part of this signal is not new.")
    critical = [i for i in evidence if CRITICAL_RE.search(i.title)]
    if critical:
        notes.append(
            f'Part of the evidence is critical or cautionary (e.g. "{critical[0].title}"); '
            f"address the downside explicitly instead of only the upside."
        )
    notes.append(
        "Clustering is keyword-based: confirm the linked items really discuss the same thing "
        "before relying on the corroboration count."
    )
    return notes


def _questions(topic: str) -> list[str]:
    return [
        f"What have you personally shipped, broken or decided about {topic} in the last 90 days?",
        "Where does this evidence disagree with what you hear from your own customers?",
        f"For a 3-person team, is {topic} a 'do now', 'watch' or 'ignore' this quarter, and why?",
        "Which number from your own business could you share to make the point concrete?",
    ]


def _outline(cluster: TopicCluster, evidence: list[EvidenceItem]) -> list[str]:
    first = evidence[0]
    return [
        f'Hook: open with the concrete signal from evidence [1] ("{first.title}").',
        "Context: summarise what the linked evidence shows, citing items by number.",
        "Your POV: answer the first founder question with a specific story or decision.",
        "Counterpoint: name the strongest objection listed above and respond to it honestly.",
        f"Takeaway: one practical recommendation about {cluster.label} for small teams.",
    ]


def build_brief(
    cluster: TopicCluster,
    rank: int,
    now: datetime,
    percentiles: dict[str, float],
    signal: SignalBrief | None = None,
) -> Brief:
    """Project one scored cluster (and, when available, its signal) into a public brief."""
    assert cluster.score is not None
    evidence = cluster.evidence or select_evidence(cluster.items, percentiles, now)
    flags: list[str] = []
    flagged = [i for i in evidence if i.flags]
    if flagged:
        flags.append(
            f"{len(flagged)} evidence item(s) contain text that looks like instructions to an AI "
            f"system (possible prompt injection). Shown as inert data only; nothing was executed."
        )
    return Brief(
        rank=rank,
        topic=cluster.label,
        angle=_angle(cluster),
        why_now=_why_now(cluster, evidence, now, percentiles),
        evidence=evidence,
        score=cluster.score,
        score_explanation=_score_explanation(cluster),
        counterpoints=_counterpoints(cluster, evidence, now),
        founder_questions=_questions(cluster.label),
        outline=_outline(cluster, evidence),
        flags=flags,
        signal=signal,
    )
