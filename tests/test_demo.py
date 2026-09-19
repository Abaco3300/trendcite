from __future__ import annotations

import json

import pytest

from trendcite.pipeline import load_demo_items, run_demo
from trendcite.render import DEMO_BANNER, to_json, to_markdown


@pytest.mark.usefixtures("no_network")
def test_demo_runs_offline_and_produces_3_to_5_briefs() -> None:
    report = run_demo()
    assert report.mode == "demo"
    assert 3 <= len(report.briefs) <= 5
    for brief in report.briefs:
        assert brief.evidence, "every brief must carry evidence"
        assert all(e.url.startswith(("https://", "http://")) for e in brief.evidence)
        assert brief.why_now and brief.counterpoints and brief.founder_questions
        assert brief.outline
        assert len({e.source for e in brief.evidence}) >= 2  # corroborated across sources
        assert 0 <= brief.score.total <= 100


@pytest.mark.usefixtures("no_network")
def test_demo_output_is_deterministic() -> None:
    assert to_json(run_demo()) == to_json(run_demo())
    assert to_markdown(run_demo()) == to_markdown(run_demo())


def test_demo_expected_ranking_snapshot() -> None:
    report = run_demo()
    ranking = [(b.topic, b.score.total, b.score.confidence) for b in report.briefs]
    assert ranking == [
        ("Usage based pricing", 81.7, "high"),
        ("MCP server", 77.5, "high"),
        ("Local first sync", 57.9, "medium"),
        ("AI code review", 46.0, "medium"),
        ("Agent eval", 43.1, "medium"),
    ]


def test_demo_filters_invalid_fixture_records() -> None:
    items, _, _, _ = load_demo_items()
    titles = {i.title for i in items}
    assert "Fixture Co is hiring engineers" not in titles  # HN job post
    assert "Dead story that must be ignored" not in titles
    assert "Unsafe link that must be dropped" not in titles  # javascript: URL
    assert "Item without a link is dropped as untraceable" not in titles


def test_demo_top_is_clamped() -> None:
    assert len(run_demo(top=1).briefs) == 3
    assert len(run_demo(top=50).briefs) == 5


def test_hostile_fixture_text_stays_inert_data() -> None:
    report = run_demo()
    md = to_markdown(report)
    data = json.loads(to_json(report))
    hostile = [
        e
        for b in data["briefs"]
        for e in b["evidence"]
        if "IGNORE ALL PREVIOUS INSTRUCTIONS" in e["title"]
    ]
    assert hostile, "fixture should include a hostile item"
    assert hostile[0]["flags"] == ["possible_prompt_injection"]
    assert "<script>" not in hostile[0]["excerpt"]
    # The hostile item is evidence like any other: it did not alter structure or scoring,
    # and the brief carries an explicit warning.
    mcp = next(b for b in report.briefs if b.topic == "MCP server")
    assert any("prompt injection" in f for f in mcp.flags)
    assert "WARNING: flagged `possible_prompt_injection`" in md
    assert DEMO_BANNER in md


def test_markdown_contains_required_brief_sections() -> None:
    md = to_markdown(run_demo())
    for heading in (
        "**Proposed angle:**",
        "**Why now**",
        "**Evidence**",
        "**Score and confidence**",
        "**Counterpoints and uncertainty**",
        "**Founder POV prompts**",
        "Draft outline (a writing aid, NOT evidence",
    ):
        assert heading in md
