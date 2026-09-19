"""Live-like quality regressions (synthetic, offline).

Each case mirrors a defect seen in a real no-LLM live run: common words and feed
boilerplate seeding topics, one link mirrored through two channels counted as two
stories, and confidence claims that the displayed evidence could not support.
"""

from __future__ import annotations

import pytest

from trendcite.cluster import cluster_items
from trendcite.models import EvidenceItem, TopicCluster
from trendcite.pipeline import build_report, run_demo
from trendcite.scoring import (
    confidence_label,
    corroboration_score,
    engagement_percentiles,
    independent_sources,
    rank_clusters,
    score_cluster,
    select_evidence,
    unique_urls,
)
from trendcite.text import BOILERPLATE, COMMON, GENERIC, extract_terms, item_text

from .conftest import NOW, item

HNRSS = (
    "Article URL: {url} Comments URL: https://news.ycombinator.com/item?id={id} "
    "Points: {p} # Comments: {c}"
)
REDDIT_FOOTER = " submitted by /u/some_user [link] [comments]"


def hnrss(title: str, url: str, n: int) -> EvidenceItem:
    """An item shaped like an hnrss.org 'newest' entry."""
    return item(
        title,
        source="rss",
        label="Hacker News: Newest",
        url=url,
        excerpt=HNRSS.format(url=url, id=49760000 + n, p=n, c=n // 2),
    )


def keys_of(clusters: list[TopicCluster]) -> set[str]:
    return {c.key for c in clusters}


# --------------------------------------------------------------------------- senses


def test_unrelated_decision_items_do_not_cluster() -> None:
    laya = "https://laya.example.com/"
    items = [
        item(
            "fixture/jev-compaction: Claude Code plugin that replaces the compaction summary "
            "with scored decisions",
            source="github",
            label="GitHub/fixture",
            metrics={"stars": 4000},
        ),
        item(
            "I built non-autoregressive decision models with RL a year ago",
            source="hackernews",
            label="Hacker News",
            url=laya,
            metrics={"points": 777},
        ),
        hnrss("I built non-autoregressive decision models with RL a year ago", laya, 777),
        item(
            "DO NOT USE PADDLE AS YOUR PAYMENT PROCESSOR",
            source="reddit",
            label="r/SaaS",
            excerpt="I wanted to share my experience so other SaaS founders can make an "
            "informed decision before building on it." + REDDIT_FOOTER,
        ),
    ]
    clusters = cluster_items(items)
    assert "decision" not in keys_of(clusters)
    # The only lexical agreement left is the mirrored HN/RSS pair, which is one story.
    assert clusters == []


@pytest.mark.parametrize(
    "titles",
    [
        [
            "Markers to deter human intrusion into a waste isolation plant",
            "Human rights court rules on border detention",
            "Human-in-the-loop labelling for vision datasets",
        ],
        [
            "Fashion model walks the runway in Milan",
            "Model railway club opens a new layout",
            "Our pricing model for usage-heavy customers",
        ],
        # Not specific to the words seen in the live run: any common English word.
        [
            "Apple pie recipe for the autumn harvest",
            "Apple ships new laptop chips",
            "An apple orchard turned into a housing estate",
        ],
        [
            "The memory of my grandmother's kitchen",
            "Persistent memory for coding agents with vector search",
            "Memory prices spike as fabs cut output",
        ],
    ],
)
def test_common_word_senses_do_not_form_clusters(titles: list[str]) -> None:
    sources = ["hackernews", "rss", "reddit"]
    items = [item(t, source=s, label=f"{s}-{n}") for n, (t, s) in enumerate(zip(titles, sources))]
    assert cluster_items(items) == []


def test_related_items_cluster_on_specific_terms_not_on_the_common_word() -> None:
    items = [
        item("Why our decision to adopt Kubernetes and Helm backfired", source="hackernews"),
        item("A decision record template for Kubernetes Helm upgrades", source="rss"),
        item("Making a hard decision about my career", source="reddit"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 1
    assert clusters[0].key != "decision"
    titles = {i.title for i in clusters[0].items}
    assert "Making a hard decision about my career" not in titles
    assert len(titles) == 2


def test_common_word_plus_one_ordinary_word_is_not_enough() -> None:
    # Live regression: "Agent + testing" paired an MCP pentest toolbelt with a
    # drug-discovery article. Inflections ("testing" -> "test") count as common words,
    # and one common word plus one other shared word is below the agreement bar.
    items = [
        item(
            "fx/blitzstrike: MCP penetration-testing toolbelt for agent validation",
            source="github",
            label="GitHub/fx",
        ),
        item(
            "Testing Jev as a validation gate for drug-discovery agents",
            source="rss",
            label="Hacker News: Newest",
        ),
    ]
    assert cluster_items(items) == []


def test_specific_seed_plus_one_specific_term_still_clusters() -> None:
    items = [
        item("GPT-6 Astra solves a WWI radio cipher", source="hackernews"),
        item("Generating running routes with GPT-6 Astra", source="rss", label="Blog"),
        item("Plain-text file format for GPT memory", source="github", label="GitHub/fx"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 1
    assert {i.source for i in clusters[0].items} == {"hackernews", "rss"}
    assert "astra" in clusters[0].label.lower()


def test_specific_word_across_sources_needs_cohesion() -> None:
    # "gpt" is specific, but these items share nothing else across communities.
    items = [
        item("GPT solves a WWI radio cipher", source="hackernews"),
        item("Plain-text file format for GPT memory", source="github"),
        item("Remember n8n? Anyone still using it with GPT?", source="reddit"),
        item("Generating running routes with GPT", source="rss"),
    ]
    assert "gpt" not in keys_of(cluster_items(items))


def test_incohesive_single_word_candidates_are_suppressed_not_published() -> None:
    # Live regression: "California" grouped a tax-policy letter with two bird photos.
    items = [
        hnrss("Economists' letter supporting the California billionaire tax", "https://t/x", 1),
        item("California sea lion, Brandt's cormorant", source="rss", label="Photo Blog"),
        item("California brown pelican", source="rss", label="Photo Blog"),
        item("Vibe coding is making software worse", source="reddit", label="r/SaaS"),
        item("fx/qcode: learn vibe coding on an island", source="github", label="GitHub/fx"),
        item("The new AI vibe coding battleground", source="hackernews"),
    ]
    report = build_report(items, now=NOW, niche=[], top=5, mode="live", source_status=[])
    assert [b.topic for b in report.briefs] == ["Vibe coding"]
    assert any("Quality gate" in n and '"California"' in n for n in report.notes)
    assert all(b.score.cohesive for b in report.briefs)


# ------------------------------------------------------------------------ boilerplate


def test_feed_boilerplate_cannot_seed_or_label_a_cluster() -> None:
    items = [
        hnrss("The first new cat species discovered in 100 years", "https://a.example.org/cat", 1),
        hnrss("What Zig felt like, coming from Rust", "https://b.example.net/zig", 2),
        hnrss("A graphical desktop for the ZX Spectrum", "https://github.com/fx/zxdesk", 3),
        hnrss("Learning another language keeps your brain healthy", "https://c.example/x", 4),
        item(
            "Every SaaS owner can relate",
            source="reddit",
            label="r/SaaS",
            excerpt=REDDIT_FOOTER,
        ),
        item(
            "Tech companies treating developers",
            source="reddit",
            label="r/SaaS",
            excerpt=REDDIT_FOOTER,
        ),
    ]
    assert cluster_items(items) == []
    for it in items:
        terms = extract_terms(item_text(it))
        words = {w for t in terms for w in t.split()}
        assert not words & BOILERPLATE, terms
        assert not words & {"article", "comment", "point", "ycombinator", "submitted", "user"}


def test_content_format_phrases_cannot_seed_a_topic() -> None:
    # Live regression: "Curated list" grouped an MCP-for-SEO list with a hosting list.
    items = [
        item("fx/awesome-seo-mcp: A curated list of MCP tools for SEO", source="github"),
        item("Curated list of hosting providers", source="rss", label="Hacker News: Newest"),
        item("The complete guide to sourdough", source="reddit", label="r/Breadit"),
        item("A complete guide to tax filing", source="hackernews"),
    ]
    assert cluster_items(items) == []


def test_boilerplate_is_removed_only_from_the_feature_view() -> None:
    it = hnrss("MCP servers in production", "https://example.com/mcp", 9)
    assert "Article URL: https://example.com/mcp" in it.excerpt  # evidence text untouched
    assert "https" not in item_text(it) and "Article URL" not in item_text(it)
    assert "MCP servers in production" in item_text(it)


# -------------------------------------------------------------------- same-URL mirrors


def test_same_url_via_hn_and_rss_is_one_underlying_story() -> None:
    url = "https://www.example.com/post/"
    hn = item("Local-first sync is boring now", source="hackernews", url=url)
    rss = hnrss("Local-first sync is boring now", "https://example.com/post", 5)
    assert hn.story_key == rss.story_key
    assert unique_urls([hn, rss]) == 1
    assert independent_sources([hn, rss]) == 1
    assert corroboration_score([hn, rss]) == 0.0
    # Two channels, one story: not a cluster on its own.
    assert cluster_items([hn, rss]) == []


def test_mirror_counts_once_when_mixed_with_other_stories() -> None:
    url = "https://example.com/sync"
    items = [
        item("Local-first sync engines compared", source="hackernews", url=url),
        hnrss("Local-first sync engines compared", url, 5),
        item("tinysync: a local-first sync engine", source="github", label="GitHub/fx"),
    ]
    assert len({i.source for i in items}) == 3
    assert independent_sources(items) == 2  # rss only mirrors the HN link
    assert corroboration_score(items) == 0.5
    report = build_report(items, now=NOW, niche=[], top=5, mode="live", source_status=[])
    assert len(report.briefs) == 1
    brief = report.briefs[0]
    assert brief.score.independent_sources == 2
    assert brief.score.unique_urls == 2
    assert brief.score.confidence != "high"
    assert any("repeat a URL" in c for c in brief.counterpoints)


# ----------------------------------------------------------------------- confidence


def test_single_source_cluster_is_never_high_confidence() -> None:
    items = [
        item(
            f"owner{n}/mcp-tool-{n}: MCP server for Claude Code number {n}",
            source="github",
            label=f"GitHub/owner{n}",
            metrics={"stars": 1000 * n},
        )
        for n in range(1, 9)
    ]
    clusters = rank_clusters(
        cluster_items(items), now=NOW, niche=["mcp", "claude code"], corpus=items
    )
    assert clusters
    for c in clusters:
        assert c.score is not None
        assert c.score.confidence != "high"
    assert confidence_label(0.0, 50, 50) != "high"
    assert confidence_label(0.5, 50, 50) != "high"  # two sources are not enough either


def test_high_confidence_requires_niche_match_when_niche_configured() -> None:
    items = [
        item("Zig comptime tricks", source="hackernews", label="HN"),
        item("zigtools: Zig comptime helpers", source="github", label="GitHub/a"),
        item("Zig comptime explained", source="rss", label="Blog"),
        item("Zig comptime in production", source="reddit", label="r/Zig"),
    ]
    cluster = cluster_items(items)[0]
    pct = engagement_percentiles(items)
    with_niche = score_cluster(cluster, now=NOW, niche=["mcp"], percentiles=pct)
    without_niche = score_cluster(cluster, now=NOW, niche=[], percentiles=pct)
    assert with_niche.confidence == "medium"
    assert without_niche.confidence == "high"


def test_displayed_evidence_covers_every_scored_source() -> None:
    # Many high-engagement GitHub repos would crowd out the other sources if the
    # evidence were picked by engagement alone.
    github = [
        item(
            f"owner{n}/crdt-{n}: CRDT sync engine {n}",
            source="github",
            label=f"GitHub/owner{n}",
            metrics={"stars": 5000 + n},
        )
        for n in range(10)
    ]
    others = [
        item("CRDT sync engines compared", source="hackernews", metrics={"points": 3}),
        item("Why we moved to CRDT sync", source="reddit", label="r/programming"),
        item("CRDT sync in practice", source="rss", label="Some Blog"),
    ]
    items = github + others
    report = build_report(items, now=NOW, niche=["crdt"], top=5, mode="live", source_status=[])
    brief = report.briefs[0]
    shown = brief.evidence
    assert len(shown) == 6
    assert {e.source for e in shown} == {"github", "hackernews", "reddit", "rss"}
    assert set(brief.score.sources) == {e.source for e in shown}
    assert brief.score.independent_sources == independent_sources(shown) == 4
    assert brief.score.unique_urls == unique_urls(shown)
    assert brief.score.publishers == len({e.publisher for e in shown})
    assert brief.score.evidence_items == len(shown)
    assert any("13 items matched" in line for line in brief.why_now)


def test_select_evidence_is_deterministic_and_prefers_new_urls() -> None:
    url = "https://example.com/one"
    items = [
        item("Story one", source="hackernews", url=url, metrics={"points": 100}),
        hnrss("Story one", url, 100),
        item("Story two", source="rss", label="Other Blog"),
    ]
    pct = engagement_percentiles(items)
    first = select_evidence(items, pct, NOW, limit=2)
    assert first == select_evidence(list(reversed(items)), pct, NOW, limit=2)
    assert unique_urls(first) == 2


# ------------------------------------------------------------------ useful clusters


def test_multi_source_mcp_claude_code_evidence_forms_one_useful_cluster() -> None:
    mcp = [
        item(
            "Claude Code now supports remote MCP servers",
            source="hackernews",
            metrics={"points": 420},
        ),
        item(
            "fx/mcp-gateway: route Claude Code to many MCP servers",
            source="github",
            label="GitHub/fx",
            metrics={"stars": 900},
        ),
        item("My Claude Code + MCP server setup for Postgres", source="reddit", label="r/ClaudeAI"),
        item(
            "Securing the MCP servers your Claude Code agent uses",
            source="rss",
            label="Security Blog",
        ),
    ]
    noise = [
        item("Human rights court rules on border detention", source="rss", label="News"),
        item("Making a hard decision about my career", source="reddit", label="r/cscareers"),
        hnrss("The first new cat species discovered in 100 years", "https://a.example/cat", 3),
    ]
    items = mcp + noise
    report = build_report(
        items, now=NOW, niche=["mcp", "claude code"], top=5, mode="live", source_status=[]
    )
    assert len(report.briefs) == 1
    brief = report.briefs[0]
    assert {e.title for e in brief.evidence} == {i.title for i in mcp}
    assert "MCP" in brief.topic or "Claude code" in brief.topic
    assert brief.score.independent_sources == 4
    assert brief.score.confidence == "high"


def test_specific_domain_unigram_still_clusters_when_cohesive() -> None:
    # No shared "mcp server" phrase: the unigram "mcp" must still work across sources
    # when the items agree on something else (here: Claude).
    items = [
        item("OAuth for MCP in Claude Desktop", source="hackernews"),
        item(
            "fx/linear-mcp: Claude connector over MCP for Linear",
            source="github",
            label="GitHub/fx",
        ),
        item("MCP inspector tips for Claude users", source="reddit", label="r/ClaudeAI"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 1
    assert len(clusters[0].items) == 3


# ---------------------------------------------------------------------------- demo


def test_demo_briefs_are_deterministic_useful_and_explainable() -> None:
    first, second = run_demo(), run_demo()
    assert [b.to_dict() for b in first.briefs] == [b.to_dict() for b in second.briefs]
    assert 3 <= len(first.briefs) <= 5
    for brief in first.briefs:
        words = brief.topic.lower().split()
        assert not set(words) & BOILERPLATE
        assert not (len(words) == 1 and (words[0] in GENERIC or words[0] in COMMON))
        assert brief.score.cohesive
        assert brief.score.independent_sources >= 2
        assert set(brief.score.sources) == {e.source for e in brief.evidence}
        assert brief.score.unique_urls == len({e.story_key for e in brief.evidence})
