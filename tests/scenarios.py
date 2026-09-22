"""Deterministic signal scenarios, each isolating one thing the engine must get right.

These are hand-built evidence sets rather than clustering output, so a scenario tests
the *evaluation* and nothing else: if a golden number moves, the cause is in
``signal_scoring``, not in tokenisation or cluster selection.

Every scenario is pinned to ``conftest.NOW`` and derives its URLs from title hashes,
so observation ids, evidence-set versions and snapshot ids are all reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from trendcite.models import EvidenceItem
from trendcite.observation import observe
from trendcite.scoring import engagement_percentiles, niche_matches, relevance_score
from trendcite.signal import (
    STATE_DORMANT,
    STATE_EMERGING,
    CandidateSignal,
    SignalBrief,
    SignalSnapshot,
    signal_id_for,
)
from trendcite.signal_scoring import build_signal_brief

from .conftest import NOW, item


@dataclass(frozen=True)
class Scenario:
    """One named evidence set plus the run context it is evaluated in."""

    name: str
    key: str
    label: str
    evidence: list[EvidenceItem]
    #: Extra items collected in the same run that are not part of this signal. Novelty
    #: measures the signal's term against the whole corpus, so this matters.
    background: list[EvidenceItem] = field(default_factory=list)
    niche: list[str] = field(default_factory=list)
    history: list[SignalSnapshot] = field(default_factory=list)
    cohesive: bool = True

    @property
    def corpus(self) -> list[EvidenceItem]:
        return [*self.evidence, *self.background]


def prior_snapshot(
    key: str,
    *,
    hours_ago: float,
    story_count: int,
    score: float = 50.0,
    state: str = STATE_EMERGING,
) -> SignalSnapshot:
    """A snapshot as a previous run would have written it."""
    captured = NOW - timedelta(hours=hours_ago)
    return SignalSnapshot(
        snapshot_id=f"prior-{signal_id_for(key)}-{int(hours_ago)}",
        signal_id=signal_id_for(key),
        captured_at=captured,
        evaluation_version="signal-eval-v1",
        evidence_set_version="prior-evidence-set",
        score=score,
        confidence="medium",
        state=state,
        observation_count=story_count,
        story_count=story_count,
        source_count=2,
    )


def build(scenario: Scenario) -> SignalBrief:
    """Evaluate a scenario exactly the way the pipeline does."""
    corpus = scenario.corpus
    candidate = CandidateSignal(
        key=scenario.key,
        label=scenario.label,
        observations=tuple(observe(scenario.evidence, ingested_at=NOW)),
        cohesive=scenario.cohesive,
    )
    return build_signal_brief(
        candidate,
        now=NOW,
        corpus=observe(corpus, ingested_at=NOW),
        percentiles=engagement_percentiles(corpus),
        relevance=relevance_score(niche_matches(scenario.evidence, scenario.niche), scenario.niche),
        history=scenario.history,
    )


def _filler(prefix: str, count: int, *, term: str = "unrelated topic") -> list[EvidenceItem]:
    """Background corpus items that never mention the scenario's key term."""
    return [
        item(f"{prefix} {term} number {n}", source="rss", label=f"{prefix}-feed-{n}")
        for n in range(count)
    ]


# --------------------------------------------------------------------------- scenarios


def strong_multi_source() -> Scenario:
    """Four source types, six distinct stories, five publishers, four days of evidence.

    The case the product exists to find: independent communities converging, with
    measurable engagement on the sources that publish it.
    """
    evidence = [
        item(
            "Kubernetes operators are eating the platform team",
            source="hackernews",
            label="Hacker News",
            hours_ago=6,
            metrics={"points": 420, "comments": 190},
        ),
        item(
            "fixture-labs/operator-audit: policy checks for Kubernetes operators",
            source="github",
            label="GitHub/fixture-labs",
            hours_ago=30,
            metrics={"stars": 1800, "forks": 90},
        ),
        item(
            "We replaced three Kubernetes operators with one controller",
            source="reddit",
            label="r/devops",
            hours_ago=52,
        ),
        item(
            "The Kubernetes operator pattern, five years on",
            source="rss",
            label="platform-weekly",
            hours_ago=74,
        ),
        item(
            "Kubernetes operators and the cost of control loops",
            source="rss",
            label="sre-notes",
            hours_ago=96,
        ),
        item(
            "Ask HN: how do you test Kubernetes operators?",
            source="hackernews",
            label="Hacker News",
            hours_ago=20,
            metrics={"points": 150, "comments": 260},
        ),
    ]
    return Scenario(
        name="strong_multi_source",
        key="kubernetes operators",
        label="Kubernetes operators",
        evidence=evidence,
        background=_filler("bg", 30),
        niche=["kubernetes"],
    )


def single_source_viral_spike() -> Scenario:
    """One community, three stories, hours old, enormous engagement.

    Loud is not the same as corroborated. Corroboration and diversity must both be
    zero, and velocity must refuse to guess from a five-hour window.
    """
    evidence = [
        item(
            "Show HN: I rewrote the parser in a weekend",
            source="hackernews",
            label="Hacker News",
            hours_ago=1,
            metrics={"points": 980, "comments": 410},
        ),
        item(
            "The parser rewrite, one day later",
            source="hackernews",
            label="Hacker News",
            hours_ago=3,
            metrics={"points": 640, "comments": 300},
        ),
        item(
            "Parser rewrite benchmarks",
            source="hackernews",
            label="Hacker News",
            hours_ago=5,
            metrics={"points": 510, "comments": 120},
        ),
    ]
    # Ordinary Hacker News traffic from the same run. Engagement is a percentile
    # *within its own source*, so the spike only looks big against its own peers.
    quiet_hn = [
        item(
            f"An ordinary Hacker News story number {n}",
            source="hackernews",
            label="Hacker News",
            hours_ago=6 + n,
            metrics={"points": 8 + n, "comments": 2 + n},
        )
        for n in range(8)
    ]
    return Scenario(
        name="single_source_viral_spike",
        key="parser rewrite",
        label="Parser rewrite",
        evidence=evidence,
        background=[*quiet_hn, *_filler("spike", 25)],
    )


def syndicated_echo() -> Scenario:
    """One article, carried by three channels. Three sources, one story.

    The failure mode this guards: counting mirrors as corroboration. Independent
    sources must collapse to one, and the echo must be named as counterevidence.
    """
    url = "https://example.com/blog/the-one-article"
    evidence = [
        item(
            "The one article everyone syndicated",
            source="hackernews",
            label="Hacker News",
            url=url,
            hours_ago=8,
            metrics={"points": 300, "comments": 120},
        ),
        item(
            "The one article everyone syndicated",
            source="rss",
            label="Hacker News: Newest",
            url=url,
            hours_ago=8,
        ),
        item(
            "The one article everyone syndicated",
            source="reddit",
            label="r/programming",
            url=url,
            hours_ago=7,
        ),
    ]
    return Scenario(
        name="syndicated_echo",
        key="syndicated article",
        label="Syndicated article",
        evidence=evidence,
        background=_filler("echo", 20),
    )


def contradicted_signal() -> Scenario:
    """Real cross-source attention, but most of it is pushback.

    The score stays high because the attention is real; the counterevidence says
    plainly that the attention is criticism.
    """
    evidence = [
        item(
            "Vector databases are overhyped and we are moving back to Postgres",
            source="hackernews",
            label="Hacker News",
            hours_ago=10,
            metrics={"points": 700, "comments": 480},
        ),
        item(
            "The vector database backlash is here",
            source="rss",
            label="data-weekly",
            hours_ago=26,
        ),
        item(
            "Our vector database bill broke the budget",
            source="reddit",
            label="r/startups",
            hours_ago=40,
        ),
        item(
            "fixture-labs/pgvector-bench: vector database benchmarks",
            source="github",
            label="GitHub/fixture-labs",
            hours_ago=60,
            metrics={"stars": 640, "forks": 41},
        ),
    ]
    return Scenario(
        name="contradicted_signal",
        key="vector database",
        label="Vector database",
        evidence=evidence,
        background=_filler("contra", 24),
    )


def new_but_not_novel() -> Scenario:
    """A cluster that formed this run about a term the corpus is saturated with.

    New grouping, old subject. Novelty must be 0 even though the signal itself has
    never been reported before, and the score must fall accordingly.
    """
    evidence = [
        item(
            "Another AI agent framework ships today",
            source="hackernews",
            label="Hacker News",
            hours_ago=9,
            metrics={"points": 210, "comments": 88},
        ),
        item(
            "Choosing an AI agent framework in 2026",
            source="rss",
            label="builder-digest",
            hours_ago=33,
        ),
        item(
            "Our AI agent framework migration notes",
            source="reddit",
            label="r/SaaS",
            hours_ago=57,
        ),
    ]
    # Half the run is already about AI agents: the term is background, not news.
    background = [
        item(f"AI agent roundup number {n}", source="rss", label=f"noise-feed-{n}")
        for n in range(12)
    ] + _filler("nn", 8)
    return Scenario(
        name="new_but_not_novel",
        key="ai agent",
        label="AI agent",
        evidence=evidence,
        background=background,
    )


def novel_but_weak() -> Scenario:
    """A genuinely unseen term, on two feeds with no metrics and no corroboration.

    Novelty alone must not carry a score. Engagement is INSUFFICIENT_DATA (not zero),
    corroboration is zero, and confidence stays low.
    """
    evidence = [
        item(
            "Introducing quorumlattice, a new consensus shape",
            source="rss",
            label="obscure-lab-notes",
            hours_ago=4,
        ),
        item(
            "quorumlattice first impressions",
            source="rss",
            label="obscure-lab-notes",
            hours_ago=12,
        ),
    ]
    return Scenario(
        name="novel_but_weak",
        key="quorumlattice",
        label="Quorumlattice",
        evidence=evidence,
        background=_filler("nbw", 40),
    )


def dormant_signal() -> Scenario:
    """Evidence exists, but the newest of it is a month old. Nothing is happening now."""
    evidence = [
        item(
            "The great serverless migration retrospective",
            source="hackernews",
            label="Hacker News",
            hours_ago=30 * 24,
            metrics={"points": 260, "comments": 140},
        ),
        item(
            "Serverless migration, one year later",
            source="rss",
            label="cloud-weekly",
            hours_ago=34 * 24,
        ),
        item(
            "We finished our serverless migration",
            source="reddit",
            label="r/devops",
            hours_ago=38 * 24,
        ),
    ]
    return Scenario(
        name="dormant_signal",
        key="serverless migration",
        label="Serverless migration",
        evidence=evidence,
        background=_filler("dorm", 20),
    )


def reactivated_signal() -> Scenario:
    """The same topic as ``dormant_signal``, but fresh evidence after a long silence.

    History holds one dormant snapshot from a month ago; today's run finds new
    stories. That is reactivation, and it is the case a single-run tool cannot see.
    """
    evidence = [
        item(
            "Serverless migration is back on the roadmap",
            source="hackernews",
            label="Hacker News",
            hours_ago=5,
            metrics={"points": 380, "comments": 210},
        ),
        item(
            "Why we restarted our serverless migration",
            source="rss",
            label="cloud-weekly",
            hours_ago=14,
        ),
        item(
            "Serverless migration, take two",
            source="reddit",
            label="r/devops",
            hours_ago=30,
        ),
    ]
    return Scenario(
        name="reactivated_signal",
        key="serverless migration",
        label="Serverless migration",
        evidence=evidence,
        background=_filler("react", 20),
        history=[
            prior_snapshot(
                "serverless migration",
                hours_ago=32 * 24,
                story_count=3,
                score=41.0,
                state=STATE_DORMANT,
            )
        ],
    )


def sustained_with_history() -> Scenario:
    """A signal seen in two previous runs, still growing.

    Exercises the cross-run branches: velocity from the stored story count, novelty
    decayed by prior sightings, persistence raised by repeat appearances.
    """
    base = strong_multi_source()
    return Scenario(
        name="sustained_with_history",
        key=base.key,
        label=base.label,
        evidence=base.evidence,
        background=base.background,
        niche=base.niche,
        history=[
            prior_snapshot(base.key, hours_ago=96, story_count=2, score=44.0),
            prior_snapshot(base.key, hours_ago=48, story_count=4, score=55.0),
        ],
    )


ALL: tuple[Scenario, ...] = (
    strong_multi_source(),
    single_source_viral_spike(),
    syndicated_echo(),
    contradicted_signal(),
    new_but_not_novel(),
    novel_but_weak(),
    dormant_signal(),
    reactivated_signal(),
    sustained_with_history(),
)

BY_NAME = {s.name: s for s in ALL}
