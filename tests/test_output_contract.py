"""The public output contract: additive only.

TrendCite's published JSON and Markdown are what other tools and the Agent Skill read.
The signal engine may add to them; it may not remove, rename or reshape anything that
was already there, and it may not change a single byte of the Markdown report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trendcite.pipeline import run_demo
from trendcite.render import to_json, to_markdown
from trendcite.versions import (
    CONTENT_OPPORTUNITY_SCORE_VERSION,
    SIGNAL_EVALUATION_VERSION,
    engine_versions,
)

pytestmark = pytest.mark.usefixtures("no_network")

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REPORT = REPO_ROOT / "examples" / "demo-report.md"

# Exactly the keys v0.1.0 published. Nothing here may ever disappear.
REPORT_KEYS_V0_1_0 = {
    "tool",
    "generated_at",
    "mode",
    "niche",
    "total_items",
    "source_status",
    "notes",
    "briefs",
}
BRIEF_KEYS_V0_1_0 = {
    "rank",
    "topic",
    "angle",
    "why_now",
    "evidence",
    "score",
    "score_explanation",
    "counterpoints",
    "founder_questions",
    "draft_outline_not_evidence",
    "flags",
    "synthesis_note",
}
EVIDENCE_KEYS_V0_1_0 = {
    "source",
    "source_label",
    "title",
    "excerpt",
    "url",
    "published_at",
    "fetched_at",
    "author",
    "discussion_url",
    "metrics",
    "raw",
    "flags",
    "id",
}
SCORE_KEYS_V0_1_0 = {
    "recency",
    "engagement",
    "corroboration",
    "relevance",
    "diversity",
    "total",
    "confidence",
    "evidence_items",
    "unique_urls",
    "sources",
    "independent_sources",
    "publishers",
    "cohesive",
}


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    return json.loads(to_json(run_demo()))


# ----------------------------------------------------------------- nothing was removed


def test_report_keeps_every_published_key(report: dict[str, object]) -> None:
    assert set(report) >= REPORT_KEYS_V0_1_0


def test_briefs_keep_every_published_key(report: dict[str, object]) -> None:
    briefs = report["briefs"]
    assert isinstance(briefs, list) and briefs
    for brief in briefs:
        assert set(brief) >= BRIEF_KEYS_V0_1_0
        assert set(brief["score"]) >= SCORE_KEYS_V0_1_0
        for evidence in brief["evidence"]:
            assert set(evidence) >= EVIDENCE_KEYS_V0_1_0


def test_public_score_semantics_are_unchanged(report: dict[str, object]) -> None:
    """The Content Opportunity score is frozen; the signal score is a separate number."""
    briefs = report["briefs"]
    assert isinstance(briefs, list)
    assert [(b["topic"], b["score"]["total"], b["score"]["confidence"]) for b in briefs] == [
        ("Usage based pricing", 81.7, "high"),
        ("MCP server", 77.5, "high"),
        ("Local first sync", 57.9, "medium"),
        ("AI code review", 46.0, "medium"),
        ("Agent eval", 43.1, "medium"),
    ]


def test_markdown_is_byte_identical_to_the_committed_example() -> None:
    """``examples/demo-report.md`` is verbatim CLI output; the signal layer is JSON-only.

    If this fails, the Markdown contract moved and the example, the SVG and the
    README excerpt all have to be regenerated together.
    """
    rendered = to_markdown(run_demo())
    committed = EXAMPLE_REPORT.read_text(encoding="utf-8")
    assert rendered in committed, "the demo Markdown no longer matches examples/demo-report.md"


def test_markdown_does_not_leak_signal_internals() -> None:
    md = to_markdown(run_demo())
    for internal in ("signal_id", "evidence_set", "insufficient_data", "observation_id"):
        assert internal not in md


# --------------------------------------------------------------------- what was added


def test_report_declares_its_algorithm_versions(report: dict[str, object]) -> None:
    engine = report["engine"]
    assert isinstance(engine, dict)
    assert engine["score_formula"] == CONTENT_OPPORTUNITY_SCORE_VERSION
    assert engine["versions"] == engine_versions()


def test_every_brief_carries_its_signal(report: dict[str, object]) -> None:
    briefs = report["briefs"]
    assert isinstance(briefs, list)
    for brief in briefs:
        signal = brief["signal"]
        assert signal is not None
        assert set(signal) == {"signal", "evaluation", "evidence_set", "snapshot", "observations"}
        assert signal["evaluation"]["evaluation_version"] == SIGNAL_EVALUATION_VERSION
        assert signal["signal"]["label"] == brief["topic"]


def test_evidence_rows_join_to_the_signal_observations(report: dict[str, object]) -> None:
    """The additive join keys must actually line up, or the audit trail is decorative."""
    briefs = report["briefs"]
    assert isinstance(briefs, list)
    for brief in briefs:
        by_id = {o["observation_id"]: o for o in brief["signal"]["observations"]}
        assert [e["observation_id"] for e in brief["evidence"]] == list(by_id)
        for evidence in brief["evidence"]:
            observation = by_id[evidence["observation_id"]]
            assert observation["evidence_item_id"] == evidence["id"]
            assert observation["story_key"] == evidence["story_key"]
            assert observation["url"] == evidence["url"]


def test_signal_evidence_set_matches_the_displayed_evidence(report: dict[str, object]) -> None:
    """A signal is scored over exactly the links the brief shows. No hidden inputs."""
    briefs = report["briefs"]
    assert isinstance(briefs, list)
    for brief in briefs:
        evidence_set = brief["signal"]["evidence_set"]
        assert evidence_set["observation_ids"] == [e["observation_id"] for e in brief["evidence"]]
        assert evidence_set["story_count"] == len({e["story_key"] for e in brief["evidence"]})
        assert evidence_set["story_count"] == brief["score"]["unique_urls"]


def test_signal_score_is_reported_separately_from_the_public_score(
    report: dict[str, object],
) -> None:
    briefs = report["briefs"]
    assert isinstance(briefs, list)
    for brief in briefs:
        evaluation = brief["signal"]["evaluation"]
        assert 0 <= evaluation["score"] <= 100
        assert set(evaluation["components"][0]) == {"name", "weight", "value", "status", "basis"}
        names = [c["name"] for c in evaluation["components"]]
        assert names == [
            "recency",
            "velocity",
            "novelty",
            "corroboration",
            "source_diversity",
            "engagement_strength",
            "persistence",
        ]


def test_json_output_is_still_deterministic() -> None:
    assert to_json(run_demo()) == to_json(run_demo())


def test_json_output_is_still_redacted_and_serialisable() -> None:
    text = to_json(run_demo())
    assert json.loads(text)  # parses
    assert "BEGIN PRIVATE KEY" not in text
