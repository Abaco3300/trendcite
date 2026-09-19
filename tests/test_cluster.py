from __future__ import annotations

from trendcite.cluster import cluster_items, display_label
from trendcite.text import extract_terms, stem

from .conftest import item


def test_stemming_and_terms() -> None:
    assert stem("servers") == "server"
    assert stem("policies") == "policy"
    assert stem("saas") == "saas"
    assert stem("class") == "class"
    assert stem("kubernetes") == "kubernetes"
    terms = extract_terms("Show HN: MCP servers for the enterprise")
    assert "mcp server" in terms
    assert "show" not in terms and "the" not in terms


def test_cross_source_items_cluster_together() -> None:
    items = [
        item("MCP servers are a supply-chain risk", source="hackernews"),
        item("mcp-audit: scan MCP server permissions", source="github"),
        item("Running MCP servers in production", source="rss"),
        item("A post about gardening", source="rss"),
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 1
    top = clusters[0]
    assert top.label == "MCP server"
    assert top.sources == ["github", "hackernews", "rss"]
    assert len(top.items) == 3


def test_singletons_do_not_become_clusters() -> None:
    items = [item("Alpha topic"), item("Beta subject"), item("Gamma matter")]
    assert cluster_items(items) == []


def test_generic_words_do_not_seed_clusters() -> None:
    items = [item("New AI tool for cats"), item("New AI tool for dogs", source="github")]
    assert cluster_items(items) == []


def test_multi_source_seed_beats_bigger_single_source_seed() -> None:
    items = [
        item("Rust compiler tips", source="rss", label="a"),
        item("Rust borrow checker", source="rss", label="b"),
        item("Rust async runtime", source="rss", label="c"),
        item("Kubernetes cost cutting", source="hackernews"),
        item("Kubernetes cost dashboards", source="github"),
    ]
    clusters = cluster_items(items)
    assert clusters[0].key.startswith("kubernetes")
    assert {c.key for c in clusters} >= {"rust"}


def test_items_join_at_most_one_cluster_and_order_is_stable() -> None:
    items = [
        item("Local-first sync engines", source="hackernews"),
        item("A local-first sync library", source="github"),
        item("Sync engines compared", source="rss"),
    ]
    first = cluster_items(items)
    second = cluster_items(list(reversed(items)))
    assert [(c.key, [i.item_id for i in c.items]) for c in first] == [
        (c.key, [i.item_id for i in c.items]) for c in second
    ]
    seen = [i.item_id for c in first for i in c.items]
    assert len(seen) == len(set(seen))


def test_display_label() -> None:
    assert display_label("mcp server") == "MCP server"
    assert display_label("usage based pricing") == "Usage based pricing"
