from __future__ import annotations

import math

import pytest

from trendcite.models import TopicCluster
from trendcite.scoring import (
    UNKNOWN_ENGAGEMENT,
    WEIGHTS,
    confidence_label,
    corroboration_score,
    diversity_score,
    engagement_percentiles,
    engagement_score,
    niche_matches,
    rank_clusters,
    recency_score,
    relevance_score,
    score_cluster,
)

from .conftest import NOW, item


def test_weights_sum_to_one() -> None:
    assert math.isclose(sum(WEIGHTS.as_dict().values()), 1.0)


def test_recency_half_life() -> None:
    assert recency_score([item("a", hours_ago=0)], NOW) == pytest.approx(1.0)
    assert recency_score([item("a", hours_ago=48)], NOW) == pytest.approx(0.5)
    assert recency_score([item("a", hours_ago=96)], NOW) == pytest.approx(0.25)
    assert recency_score([item("a", hours_ago=-5)], NOW) == pytest.approx(1.0)  # future-dated
    assert recency_score([], NOW) == 0.0


def test_engagement_is_normalised_within_each_source() -> None:
    hn_small = item("h1", source="hackernews", metrics={"points": 5})
    hn_big = item("h2", source="hackernews", metrics={"points": 500})
    gh_small = item("g1", source="github", metrics={"stars": 50_000})
    gh_big = item("g2", source="github", metrics={"stars": 90_000})
    rss = item("r1", source="rss")
    pct = engagement_percentiles([hn_small, hn_big, gh_small, gh_big, rss])
    # 500 HN points ranks the same as 90k GitHub stars: each is top of its own source.
    assert pct[hn_big.item_id] == pct[gh_big.item_id] == 0.75
    assert pct[hn_small.item_id] == pct[gh_small.item_id] == 0.25
    assert rss.item_id not in pct


def test_engagement_score_unknown_and_top3() -> None:
    assert engagement_score([item("x")], {}) == UNKNOWN_ENGAGEMENT
    items = [item(f"t{i}", source="hackernews") for i in range(4)]
    pct = {
        items[0].item_id: 1.0,
        items[1].item_id: 0.8,
        items[2].item_id: 0.6,
        items[3].item_id: 0.0,
    }
    assert engagement_score(items, pct) == pytest.approx(0.8)


def test_corroboration_steps() -> None:
    assert corroboration_score([item("a"), item("b")]) == 0.0
    assert corroboration_score([item("a"), item("b", source="github")]) == 0.5
    three = [item("a"), item("b", source="github"), item("c", source="reddit")]
    assert corroboration_score(three) == 1.0


def test_relevance_and_niche_matching() -> None:
    items = [item("Pricing AI agents for SaaS teams"), item("Other")]
    matches = niche_matches(items, ["ai agents", "pricing", "developer tools"])
    assert matches == ["ai agents", "pricing"]
    assert relevance_score(matches, ["ai agents"]) == 1.0
    assert relevance_score(["pricing"], ["pricing", "x"]) == 0.5
    assert relevance_score([], []) == 0.5  # neutral when no niche configured


def test_niche_phrase_does_not_span_items() -> None:
    items = [item("We love AI"), item("Agents everywhere")]
    assert niche_matches(items, ["ai agents"]) == []


def test_diversity() -> None:
    assert diversity_score([item("a", label="one"), item("b", label="one")]) == 0.0
    four = [item(str(i), label=f"p{i}") for i in range(4)]
    assert diversity_score(four) == 1.0


def test_confidence_labels() -> None:
    assert confidence_label(1.0, 4, 3) == "high"
    assert confidence_label(0.5, 2, 2) == "medium"
    assert confidence_label(0.0, 3, 1) == "medium"
    assert confidence_label(0.0, 2, 2) == "low"


def test_score_cluster_matches_documented_formula() -> None:
    items = [
        item("MCP server risk", source="hackernews", hours_ago=0, metrics={"points": 10}),
        item("MCP server audit", source="github", hours_ago=0, metrics={"stars": 10}),
    ]
    cluster = TopicCluster(key="mcp server", label="MCP server", items=items)
    s = score_cluster(cluster, now=NOW, niche=["mcp"], percentiles=engagement_percentiles(items))
    expected = 100 * (0.25 * 1.0 + 0.25 * 0.5 + 0.25 * 0.5 + 0.15 * 0.5 + 0.10 * (1 / 3))
    assert s.total == pytest.approx(round(expected, 1))
    assert s.confidence == "medium"


def test_rank_is_deterministic_and_prefers_corroboration() -> None:
    solo = TopicCluster("solo", "Solo", [item("solo one"), item("solo two")])
    multi = TopicCluster(
        "multi",
        "Multi",
        [item("multi a"), item("multi b", source="github"), item("multi c", source="reddit")],
    )
    corpus = solo.items + multi.items
    ranked = rank_clusters([solo, multi], now=NOW, niche=[], corpus=corpus)
    assert [c.key for c in ranked] == ["multi", "solo"]
