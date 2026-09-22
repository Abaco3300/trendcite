"""Golden tests for the signal engine.

Two layers, on purpose:

* a **golden file** (``tests/golden/signal_scenarios.json``) pinning every number the
  evaluator produces for every scenario, so any unintended change to a weight, a
  constant or a rounding rule fails loudly and visibly in a diff;
* **semantic assertions** stating, in code, *why* each scenario is what it is, so a
  deliberate change to the golden file still has to keep the meaning intact.

Regenerate the golden file after an intentional change with::

    TRENDCITE_REGEN_GOLDEN=1 python -m pytest tests/test_signal_engine.py

and review the diff. Regenerating without reading the diff defeats the point.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from trendcite.signal import (
    INSUFFICIENT_DATA,
    MEASURED,
    STATE_DORMANT,
    STATE_EMERGING,
    STATE_REACTIVATED,
    STATE_SUSTAINED,
)
from trendcite.signal_scoring import (
    CE_CONTRADICTED,
    CE_NO_ENGAGEMENT_METRICS,
    CE_SINGLE_SOURCE,
    CE_SMALL_SAMPLE,
    CE_STALE_EVIDENCE,
    CE_SYNDICATED_ECHO,
    SIGNAL_WEIGHTS,
    check_weights,
)

from . import scenarios

GOLDEN = Path(__file__).resolve().parent / "golden" / "signal_scenarios.json"


def evaluate(name: str) -> dict[str, object]:
    return scenarios.build(scenarios.BY_NAME[name]).to_dict()


def component(brief: dict[str, object], name: str) -> dict[str, object]:
    evaluation = brief["evaluation"]
    assert isinstance(evaluation, dict)
    components = evaluation["components"]
    assert isinstance(components, list)
    return next(c for c in components if c["name"] == name)


def codes(brief: dict[str, object]) -> set[str]:
    evaluation = brief["evaluation"]
    assert isinstance(evaluation, dict)
    return {c["code"] for c in evaluation["counterevidence"]}


# ------------------------------------------------------------------------ golden file


def _current() -> dict[str, object]:
    return {s.name: scenarios.build(s).to_dict() for s in scenarios.ALL}


def test_scenarios_match_the_golden_file() -> None:
    current = _current()
    if os.environ.get("TRENDCITE_REGEN_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        pytest.skip("golden file regenerated; re-run without TRENDCITE_REGEN_GOLDEN")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(current) == set(expected), "a scenario was added or removed"
    for name in sorted(expected):
        assert current[name] == expected[name], f"scenario '{name}' drifted from the golden file"


def test_evaluation_is_reproducible() -> None:
    """Same inputs, same output: no ordering, hashing or clock dependence."""
    assert _current() == _current()


def test_weights_sum_to_one() -> None:
    check_weights()
    assert sum(SIGNAL_WEIGHTS.as_dict().values()) == pytest.approx(1.0)


# --------------------------------------------------------------------------- semantics


def test_strong_multi_source_is_corroborated_and_confident() -> None:
    brief = evaluate("strong_multi_source")
    assert component(brief, "corroboration")["value"] == 1.0
    assert component(brief, "source_diversity")["value"] == 1.0
    assert component(brief, "engagement_strength")["status"] == MEASURED
    assert component(brief, "persistence")["value"] == 1.0
    assert brief["evaluation"]["confidence"] == "high"  # type: ignore[index]
    assert brief["evaluation"]["measured_weight"] == 1.0  # type: ignore[index]
    assert CE_SINGLE_SOURCE not in codes(brief)


def test_single_source_viral_spike_is_loud_but_uncorroborated() -> None:
    """High engagement must never buy corroboration, diversity or persistence."""
    brief = evaluate("single_source_viral_spike")
    assert component(brief, "corroboration")["value"] == 0.0
    assert component(brief, "source_diversity")["value"] == 0.0
    assert component(brief, "persistence")["value"] == 0.0
    # Top-3 percentiles within Hacker News: the spike outranks every ordinary story
    # collected in the same run. It cannot reach exactly 1.0, because an item is part
    # of the population it is ranked against.
    engagement = component(brief, "engagement_strength")["value"]
    assert isinstance(engagement, float) and engagement >= 0.85
    # A five-hour window is too narrow to claim an arrival rate from.
    assert component(brief, "velocity")["status"] == INSUFFICIENT_DATA
    assert CE_SINGLE_SOURCE in codes(brief)
    assert brief["evaluation"]["confidence"] == "medium"  # type: ignore[index]
    assert brief["evaluation"]["state"] == STATE_EMERGING  # type: ignore[index]


def test_syndicated_echo_collapses_to_one_independent_source() -> None:
    """Three channels carrying one link is one source, and is said to be."""
    brief = evaluate("syndicated_echo")
    assert brief["evidence_set"]["observation_count"] == 3  # type: ignore[index]
    assert brief["evidence_set"]["story_count"] == 1  # type: ignore[index]
    assert component(brief, "corroboration")["value"] == 0.0
    assert {CE_SYNDICATED_ECHO, CE_SINGLE_SOURCE, CE_SMALL_SAMPLE} <= codes(brief)


def test_contradicted_signal_reports_the_pushback() -> None:
    brief = evaluate("contradicted_signal")
    assert component(brief, "corroboration")["value"] == 1.0
    assert CE_CONTRADICTED in codes(brief)
    evaluation = brief["evaluation"]
    assert isinstance(evaluation, dict)
    entry = next(c for c in evaluation["counterevidence"] if c["code"] == CE_CONTRADICTED)
    # Counterevidence points at the exact observations that caused it.
    assert entry["observation_ids"]
    assert set(entry["observation_ids"]) <= set(brief["evidence_set"]["observation_ids"])  # type: ignore[index]


def test_new_but_not_novel_scores_zero_novelty() -> None:
    """A brand-new cluster about a saturated term is not news."""
    brief = evaluate("new_but_not_novel")
    novelty = component(brief, "novelty")
    assert novelty["status"] == MEASURED
    assert novelty["value"] == 0.0
    assert "saturation" in str(novelty["basis"])
    # It is still a real, corroborated conversation; only novelty is denied.
    assert component(brief, "corroboration")["value"] == 1.0


def test_novel_but_weak_is_novel_and_still_weak() -> None:
    brief = evaluate("novel_but_weak")
    # Near-maximal novelty: the term appears nowhere in the run except in its own
    # evidence. It can never be exactly 1.0, because the signal is part of the corpus
    # it is measured against -- and pretending otherwise would be the fake metric.
    novelty = component(brief, "novelty")["value"]
    assert isinstance(novelty, float) and novelty >= 0.8
    assert novelty > component(evaluate("new_but_not_novel"), "novelty")["value"]  # type: ignore[operator]
    assert component(brief, "corroboration")["value"] == 0.0
    # Feeds without vote counts mean unknown reach, never zero reach.
    engagement = component(brief, "engagement_strength")
    assert engagement["status"] == INSUFFICIENT_DATA
    assert engagement["value"] is None
    assert {CE_NO_ENGAGEMENT_METRICS, CE_SINGLE_SOURCE, CE_SMALL_SAMPLE} <= codes(brief)
    assert brief["evaluation"]["confidence"] == "low"  # type: ignore[index]
    # Novelty alone must not out-score a corroborated signal.
    assert brief["evaluation"]["score"] < evaluate("strong_multi_source")["evaluation"]["score"]  # type: ignore[index,operator]


def test_insufficient_components_are_excluded_not_assumed() -> None:
    """The unmeasured weight leaves the denominator; it is not scored 0 or 0.5."""
    brief = evaluate("novel_but_weak")
    evaluation = brief["evaluation"]
    assert isinstance(evaluation, dict)
    # Two feed items with no vote counts and a two-hour spread: reach is unknown and
    # the arrival window is too narrow to read anything into.
    assert evaluation["insufficient_data"] == ["velocity", "engagement_strength"]
    measured_weight = 1.0 - SIGNAL_WEIGHTS.velocity - SIGNAL_WEIGHTS.engagement_strength
    assert evaluation["measured_weight"] == pytest.approx(measured_weight)
    measured = [c for c in evaluation["components"] if c["status"] == MEASURED]
    earned = sum(c["value"] * c["weight"] for c in measured)
    assert evaluation["score"] == pytest.approx(100 * earned / measured_weight, abs=0.05)
    assert any("excluded rather than assumed" in n for n in evaluation["notes"])


def test_dormant_signal_is_marked_dormant_and_stale() -> None:
    brief = evaluate("dormant_signal")
    assert brief["evaluation"]["state"] == STATE_DORMANT  # type: ignore[index]
    assert CE_STALE_EVIDENCE in codes(brief)


def test_reactivation_needs_history() -> None:
    """Fresh evidence after a dormant snapshot is reactivation, not a new signal."""
    brief = evaluate("reactivated_signal")
    assert brief["evaluation"]["state"] == STATE_REACTIVATED  # type: ignore[index]
    # Same topic key as the dormant scenario, so the stable id lines the two up.
    assert brief["signal"]["signal_id"] == evaluate("dormant_signal")["signal"]["signal_id"]  # type: ignore[index]


def test_history_changes_velocity_novelty_and_persistence() -> None:
    """The cross-run branches must actually differ from the single-run ones."""
    fresh = evaluate("strong_multi_source")
    seen_before = evaluate("sustained_with_history")
    assert (
        fresh["evidence_set"]["observation_ids"]
        == (  # type: ignore[index]
            seen_before["evidence_set"]["observation_ids"]  # type: ignore[index]
        )
    )
    assert "previous snapshot" in str(component(seen_before, "velocity")["basis"])
    assert component(seen_before, "novelty")["value"] < component(fresh, "novelty")["value"]  # type: ignore[operator]
    assert seen_before["evaluation"]["state"] == STATE_SUSTAINED  # type: ignore[index]
    assert seen_before["signal"]["first_seen_at"] < seen_before["signal"]["last_seen_at"]  # type: ignore[index,operator]


def test_score_is_separate_from_confidence_and_relevance() -> None:
    brief = evaluate("strong_multi_source")
    evaluation = brief["evaluation"]
    assert isinstance(evaluation, dict)
    assert 0 <= evaluation["score"] <= 100
    assert evaluation["confidence"] in {"high", "medium", "low"}
    assert 0.0 <= evaluation["relevance"] <= 1.0
    # Relevance is reported beside the score, never folded into it.
    assert "relevance" not in {c["name"] for c in evaluation["components"]}


@pytest.mark.parametrize("scenario", [s.name for s in scenarios.ALL])
def test_every_scenario_is_internally_consistent(scenario: str) -> None:
    brief = evaluate(scenario)
    evaluation = brief["evaluation"]
    assert isinstance(evaluation, dict)
    for c in evaluation["components"]:
        assert (c["value"] is None) == (c["status"] == INSUFFICIENT_DATA)
        assert c["value"] is None or 0.0 <= c["value"] <= 1.0
        assert c["basis"], "every component must say what it measured"
    assert 0 <= evaluation["score"] <= 100
    evidence_set = brief["evidence_set"]
    assert isinstance(evidence_set, dict)
    assert evidence_set["story_count"] <= evidence_set["observation_count"]
    snapshot = brief["snapshot"]
    assert isinstance(snapshot, dict)
    assert snapshot["evidence_set_version"] == evidence_set["version_id"]
    assert snapshot["score"] == evaluation["score"]
