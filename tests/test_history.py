"""The local history boundary: append-only, local, off by default."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from trendcite.history import (
    HistoryStore,
    InMemoryHistoryStore,
    JsonlHistoryStore,
    NullHistoryStore,
)
from trendcite.observation import ObservationSnapshot, observe
from trendcite.pipeline import run_demo
from trendcite.signal import STATE_EMERGING, STATE_SUSTAINED, SignalSnapshot

from .conftest import NOW, item

pytestmark = pytest.mark.usefixtures("no_network")


def snapshot(signal_id: str, *, hours_ago: float, score: float = 50.0) -> SignalSnapshot:
    return SignalSnapshot(
        snapshot_id=f"{signal_id}-{int(hours_ago)}",
        signal_id=signal_id,
        captured_at=NOW - timedelta(hours=hours_ago),
        evaluation_version="signal-eval-v1",
        evidence_set_version="evset",
        score=score,
        confidence="medium",
        state=STATE_EMERGING,
        observation_count=3,
        story_count=3,
        source_count=2,
    )


def test_all_stores_satisfy_the_protocol() -> None:
    for store in (NullHistoryStore(), InMemoryHistoryStore(), JsonlHistoryStore("x.jsonl")):
        assert isinstance(store, HistoryStore)


def test_null_store_is_the_default_and_remembers_nothing() -> None:
    store = NullHistoryStore()
    store.append_signal_snapshots([snapshot("abc", hours_ago=1)])
    assert store.signal_history("abc") == []


def test_demo_with_no_store_writes_nothing(tmp_path: Path) -> None:
    """The shipped default must not touch the filesystem."""
    before = set(tmp_path.iterdir())
    run_demo()
    assert set(tmp_path.iterdir()) == before


def test_in_memory_store_returns_history_oldest_first() -> None:
    store = InMemoryHistoryStore()
    store.append_signal_snapshots(
        [snapshot("abc", hours_ago=1), snapshot("abc", hours_ago=48), snapshot("zzz", hours_ago=2)]
    )
    history = store.signal_history("abc")
    assert [s.captured_at for s in history] == sorted(s.captured_at for s in history)
    assert len(history) == 2
    assert store.signal_history("missing") == []


def test_jsonl_store_round_trips(tmp_path: Path) -> None:
    store = JsonlHistoryStore(tmp_path / "nested" / "history.jsonl")
    original = snapshot("abc", hours_ago=24, score=61.5)
    store.append_signal_snapshots([original])
    restored = store.signal_history("abc")
    assert len(restored) == 1
    assert restored[0] == original


def test_jsonl_store_appends_rather_than_replacing(tmp_path: Path) -> None:
    store = JsonlHistoryStore(tmp_path / "history.jsonl")
    store.append_signal_snapshots([snapshot("abc", hours_ago=48)])
    store.append_signal_snapshots([snapshot("abc", hours_ago=24)])
    assert len(store.signal_history("abc")) == 2


def test_jsonl_store_stores_observation_readings(tmp_path: Path) -> None:
    store = JsonlHistoryStore(tmp_path / "history.jsonl")
    obs = observe([item("Measured", source="hackernews", metrics={"points": 12})], ingested_at=NOW)
    store.append_observation_snapshots([ObservationSnapshot.of(obs[0], captured_at=NOW)])
    readings = store.observation_history(obs[0].observation_id)
    assert len(readings) == 1
    assert readings[0].metrics == {"points": 12.0}


def test_corrupt_history_degrades_to_no_history(tmp_path: Path) -> None:
    """A broken file must cost the run its history, never the run itself."""
    path = tmp_path / "history.jsonl"
    good = snapshot("abc", hours_ago=24)
    store = JsonlHistoryStore(path)
    store.append_signal_snapshots([good])
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json at all\n")
        fh.write('{"v": "some-future-version", "kind": "signal_snapshot", "data": {}}\n')
        fh.write('{"v": "trendcite-history-v1", "kind": "signal_snapshot", "data": {}}\n')
    assert store.signal_history("abc") == [good]


def test_missing_history_file_is_simply_empty(tmp_path: Path) -> None:
    assert JsonlHistoryStore(tmp_path / "absent.jsonl").signal_history("abc") == []


# ---------------------------------------------------------------- end-to-end behaviour


def test_two_runs_make_a_signal_sustained() -> None:
    """The second run sees the first run's snapshots and says so."""
    store = InMemoryHistoryStore()
    first = run_demo(history=store)
    second = run_demo(history=store)

    first_states = {b.topic: b.signal.evaluation.state for b in first.briefs if b.signal}
    second_states = {b.topic: b.signal.evaluation.state for b in second.briefs if b.signal}
    assert set(first_states) == set(second_states)
    assert all(state == STATE_SUSTAINED for state in second_states.values())
    # A signal keeps its identity across runs; that is what makes history usable.
    first_ids = {b.topic: b.signal.signal_id for b in first.briefs if b.signal}
    second_ids = {b.topic: b.signal.signal_id for b in second.briefs if b.signal}
    assert first_ids == second_ids


def test_history_never_changes_the_public_contract() -> None:
    """Signal state may evolve across runs; the published briefs and scores may not."""
    store = InMemoryHistoryStore()
    first = run_demo(history=store)
    second = run_demo(history=store)
    assert [(b.topic, b.score.total, b.score.confidence) for b in first.briefs] == [
        (b.topic, b.score.total, b.score.confidence) for b in second.briefs
    ]


def test_a_run_appends_one_snapshot_per_published_brief(tmp_path: Path) -> None:
    store = JsonlHistoryStore(tmp_path / "history.jsonl")
    report = run_demo(history=store)
    for brief in report.briefs:
        assert brief.signal is not None
        assert len(store.signal_history(brief.signal.signal_id)) == 1
