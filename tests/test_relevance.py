from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from trendcite.cloud.db.sqlite import SQLiteUnitOfWorkFactory
from trendcite.cloud.domain.relevance import (
    BAND_STRONG,
    BAND_VERY_STRONG,
    DECISION_EXCLUDED,
    DECISION_MATCHED,
    DECISION_NO_MATCH,
    RelevanceEvaluation,
    RelevanceService,
    RelevanceTarget,
    aggregate_radar,
)
from trendcite.cloud.domain.watchlist import WatchlistVersion

NOW = datetime(2026, 9, 22, 16, 0, tzinfo=UTC)


def watchlist(
    *,
    watchlist_id: str = "w1",
    version_number: int = 1,
    include: tuple[str, ...] = ("mcp server",),
    exclude: tuple[str, ...] = (),
    entities: tuple[str, ...] = (),
    domains: tuple[str, ...] = (),
) -> WatchlistVersion:
    return WatchlistVersion.create(
        watchlist_id=watchlist_id,
        workspace_id="workspace",
        version_number=version_number,
        include_terms=include,
        exclude_terms=exclude,
        entities=entities,
        domains=domains,
        created_at=NOW,
    )


def target(
    *,
    signal_id: str = "s1",
    snapshot_id: str = "snap1",
    label: str = "MCP server adoption accelerating",
    key: str = "mcp server",
    related: tuple[str, ...] = ("agent tooling",),
    context: tuple[str, ...] = ("Teams deploy MCP server infrastructure",),
) -> RelevanceTarget:
    return RelevanceTarget(signal_id, snapshot_id, label, key, related, context)


def test_golden_relevance_scenarios() -> None:
    data = json.loads((Path(__file__).parent / "golden" / "relevance_scenarios.json").read_text())
    service = RelevanceService()
    for scenario in data["scenarios"]:
        wl = watchlist(
            include=tuple(scenario["include"]),
            exclude=tuple(scenario["exclude"]),
        )
        item = target(
            label=scenario["label"],
            key=scenario["key"],
            related=tuple(scenario["related"]),
            context=tuple(scenario["context"]),
        )
        outcome = service.evaluate_one(wl, item)
        assert outcome.decision == scenario["decision"], scenario["name"]


def test_exact_phrase_is_strong_and_explainable() -> None:
    outcome = RelevanceService().evaluate_one(watchlist(), target())
    assert outcome.decision == DECISION_MATCHED
    assert outcome.band in {BAND_STRONG, BAND_VERY_STRONG}
    assert any(reason.reason_type == "exact_term" for reason in outcome.reasons)


def test_generic_term_is_capped_below_positive_threshold() -> None:
    wl = watchlist(include=("agents",))
    item = target(
        label="Travel agents face new commission rules",
        key="travel agents",
        related=(),
        context=(),
    )
    outcome = RelevanceService().evaluate_one(wl, item)
    assert outcome.decision == DECISION_NO_MATCH
    assert outcome.score <= 39


def test_hard_exclusion_wins() -> None:
    wl = watchlist(include=("agents",), exclude=("gaming",))
    item = target(label="Gaming NPC agents", key="gaming agents", related=(), context=())
    outcome = RelevanceService().evaluate_one(wl, item)
    assert outcome.decision == DECISION_EXCLUDED
    assert outcome.score == 0
    assert any(reason.reason_type == "exclusion" for reason in outcome.reasons)


def test_related_term_can_match_without_llm() -> None:
    wl = watchlist(include=("autonomous software engineering",))
    item = target(
        label="Developer agent tooling",
        key="developer agents",
        related=("autonomous software engineering",),
        context=(),
    )
    outcome = RelevanceService().evaluate_one(wl, item)
    assert outcome.score > 0
    assert any(reason.reason_type == "related_term" for reason in outcome.reasons)


def test_signal_score_is_not_a_relevance_input() -> None:
    item = target()
    assert not hasattr(item, "score")
    assert not hasattr(item, "signal_score")
    outcome = RelevanceService().evaluate_one(watchlist(), item)
    assert outcome.decision == DECISION_MATCHED


def test_evaluation_identity_changes_with_watchlist_version_and_snapshot() -> None:
    service = RelevanceService()
    wl1 = watchlist(version_number=1)
    wl2 = watchlist(version_number=2)
    item1 = target(snapshot_id="snap1")
    item2 = target(snapshot_id="snap2")
    out1 = service.evaluate_one(wl1, item1)
    out2 = service.evaluate_one(wl2, item1)
    out3 = service.evaluate_one(wl1, item2)
    ev1 = RelevanceEvaluation.create(
        workspace_id="workspace",
        watchlist=wl1,
        target=item1,
        outcome=out1,
        evaluated_at=NOW,
    )
    ev2 = RelevanceEvaluation.create(
        workspace_id="workspace",
        watchlist=wl2,
        target=item1,
        outcome=out2,
        evaluated_at=NOW,
    )
    ev3 = RelevanceEvaluation.create(
        workspace_id="workspace",
        watchlist=wl1,
        target=item2,
        outcome=out3,
        evaluated_at=NOW,
    )
    assert len({ev1.evaluation_id, ev2.evaluation_id, ev3.evaluation_id}) == 3


def test_same_logical_evaluation_is_idempotent_in_database(tmp_path: Path) -> None:
    from trendcite.cloud.application import CloudApplication

    class EmptyExecutor:
        def execute(self, radar: object, *, evaluation_cutoff: datetime) -> object:
            raise AssertionError("executor must not be called")

    factory = SQLiteUnitOfWorkFactory(tmp_path / "cloud.db")
    factory.bootstrap()
    app = CloudApplication(factory, executor=EmptyExecutor())
    workspace = app.create_workspace(slug="rel", name="Rel", owner_principal_id="owner")
    wl, version = app.create_watchlist(
        workspace_id=workspace.workspace_id,
        name="MCP",
        include_terms=["mcp server"],
    )
    del wl

    with factory() as uow:
        from trendcite.cloud.domain.signals import StoredSignal, StoredSignalEvaluation

        # Minimal global rows required by relevance foreign keys.
        signal = StoredSignal("s1", "mcp server", "MCP server", (), NOW, NOW, "signal-id-v1")
        snapshot = StoredSignalEvaluation(
            "snap1", "s1", NOW, "eval-v1", "evidence-v1", 95.0, "high", "accelerating", 1, 1, 1, {}
        )
        uow.signals.upsert(signal)
        uow.signals.record_evaluation(snapshot)
        outcome = RelevanceService().evaluate_one(version, target())
        evaluation = RelevanceEvaluation.create(
            workspace_id=workspace.workspace_id,
            watchlist=version,
            target=target(),
            outcome=outcome,
            evaluated_at=NOW,
        )
        assert uow.relevance.record_evaluation(evaluation) is True
        assert uow.relevance.record_evaluation(evaluation) is False
        uow.commit()


def test_radar_aggregation_uses_max_relevance() -> None:
    service = RelevanceService()
    item = target()
    high_wl = watchlist(watchlist_id="high", include=("mcp server",))
    low_wl = watchlist(watchlist_id="low", include=("server",))
    high_out = service.evaluate_one(high_wl, item)
    low_out = service.evaluate_one(low_wl, item)
    high = RelevanceEvaluation.create(
        workspace_id="workspace", watchlist=high_wl, target=item, outcome=high_out, evaluated_at=NOW
    )
    low = RelevanceEvaluation.create(
        workspace_id="workspace", watchlist=low_wl, target=item, outcome=low_out, evaluated_at=NOW
    )
    aggregated = aggregate_radar("s1", [low, high])
    assert aggregated is not None
    assert aggregated.score == max(high.score, low.score)


def test_migration_upgrade_from_0001_to_0002(tmp_path: Path) -> None:
    import sqlite3

    from trendcite.cloud.db.sqlite import apply_migrations

    db_path = tmp_path / "upgrade.db"
    conn = sqlite3.connect(db_path)
    try:
        migration1 = (
            Path(__file__).parents[1]
            / "src"
            / "trendcite"
            / "cloud"
            / "db"
            / "sql"
            / "0001_cloud_foundation.sql"
        ).read_text(encoding="utf-8")
        conn.executescript(migration1)
        conn.execute(
            "CREATE TABLE schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO schema_migrations(name) VALUES (?)",
            ("0001_cloud_foundation.sql",),
        )
        conn.commit()
        applied = apply_migrations(conn)
        assert applied == [
            "0001_cloud_foundation.sql",
            "0002_signal_matching_relevance.sql",
        ]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(cloud_watchlist_version)")}
        assert {"entities", "domains"} <= columns
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "cloud_relevance_evaluation" in tables
        assert "cloud_watchlist_signal_match" in tables
    finally:
        conn.close()
