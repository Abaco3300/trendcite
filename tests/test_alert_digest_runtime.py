from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trendcite.cloud.alert_runtime import AlertDigestRuntime
from trendcite.cloud.db.sqlite import SQLiteUnitOfWorkFactory, connect
from trendcite.cloud.delivery import LocalDeliveryAdapter
from trendcite.cloud.domain.alerts import (
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    MATERIALITY_MATERIAL,
    MATERIALITY_NONE,
    REASON_BELOW_MATERIALITY,
    REASON_BELOW_RELEVANCE,
    REASON_COOLDOWN,
    REASON_DISMISSED,
    REASON_DUPLICATE,
    REASON_MUTED,
    REASON_QUALIFIED,
    TARGET_ALERT,
    TARGET_DIGEST,
    AlertBaseline,
    AlertPolicy,
    MaterialityService,
    SignalState,
)
from trendcite.cloud.domain.radar import (
    RUN_COVERAGE_COMPLETE,
    RUN_COVERAGE_DEGRADED,
)
from trendcite.cloud.domain.usage import (
    USAGE_ALERT_CANDIDATE,
    USAGE_ALERT_CREATED,
    USAGE_DELIVERY_ATTEMPT,
    USAGE_DELIVERY_FAILURE,
    USAGE_DELIVERY_SUCCESS,
    USAGE_DIGEST_CREATED,
)

NOW = datetime(2026, 9, 22, 20, 0, tzinfo=UTC)


class Clock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def seed_scope(db: Path, suffix: str = "a") -> dict[str, str]:
    SQLiteUnitOfWorkFactory(db).bootstrap()
    ids = {
        "workspace": f"workspace-{suffix}",
        "watchlist": f"watchlist-{suffix}",
        "radar": f"radar-{suffix}",
        "radar_version": f"radar-version-{suffix}",
    }
    conn = connect(db)
    try:
        conn.execute(
            "INSERT INTO cloud_workspace(workspace_id,slug,name,created_at) VALUES (?,?,?,?)",
            (ids["workspace"], f"ws-{suffix}", f"Workspace {suffix}", NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO cloud_watchlist(watchlist_id,workspace_id,name,created_at) "
            "VALUES (?,?,?,?)",
            (ids["watchlist"], ids["workspace"], "AI Signals", NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO cloud_radar(radar_id,workspace_id,name,created_at) VALUES (?,?,?,?)",
            (ids["radar"], ids["workspace"], "AI Radar", NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO cloud_radar_version("
            "version_id,radar_id,workspace_id,version_number,watchlist_version_ids,sources,"
            "niche,top,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ids["radar_version"],
                ids["radar"],
                ids["workspace"],
                1,
                "[]",
                "[]",
                "[]",
                5,
                NOW.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return ids


def seed_signal(
    db: Path,
    *,
    signal_id: str,
    snapshot_id: str,
    score: float = 70.0,
) -> None:
    conn = connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO cloud_signal("
            "signal_id,signal_key,label,related_terms,first_seen_at,last_seen_at,signal_id_version"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                signal_id,
                signal_id,
                f"Signal {signal_id}",
                "[]",
                NOW.isoformat(),
                NOW.isoformat(),
                "signal-id-v1",
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO cloud_signal_evaluation("
            "snapshot_id,signal_id,captured_at,evaluation_version,evidence_set_version,score,"
            "confidence,state,observation_count,story_count,source_count,component_values"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot_id,
                signal_id,
                NOW.isoformat(),
                "evaluation-v1",
                "evidence-v1",
                score,
                "high",
                "emerging",
                5,
                2,
                2,
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def state(
    signal_id: str,
    snapshot_id: str,
    *,
    signal_score: float = 70.0,
    relevance: float = 82.0,
    lifecycle: str = "emerging",
    velocity: float | None = 0.4,
    source_count: int = 2,
    counterevidence: tuple[str, ...] = (),
    observed_at: datetime = NOW,
) -> SignalState:
    return SignalState.create(
        signal_id=signal_id,
        snapshot_id=snapshot_id,
        signal_score=signal_score,
        relevance_score=relevance,
        lifecycle_state=lifecycle,
        velocity=velocity,
        source_count=source_count,
        counterevidence=counterevidence,
        observed_at=observed_at,
    )


def test_materiality_uses_delivered_baseline_and_withholds_degraded_declines() -> None:
    service = MaterialityService()
    previous = state(
        "s1",
        "snap1",
        signal_score=90,
        relevance=90,
        velocity=0.8,
        source_count=4,
    )
    baseline = AlertBaseline.of(
        workspace_id="w",
        watchlist_id="wl",
        signal_id="s1",
        alert_id="a1",
        state=previous,
        delivered_at=NOW,
    )
    current = state(
        "s1",
        "snap2",
        signal_score=60,
        relevance=65,
        velocity=0.2,
        source_count=1,
        observed_at=NOW + timedelta(hours=1),
    )
    degraded = service.evaluate(
        current,
        baseline,
        coverage_state=RUN_COVERAGE_DEGRADED,
    )
    assert degraded.level == MATERIALITY_NONE
    assert degraded.withheld_declines

    complete = service.evaluate(
        current,
        baseline,
        coverage_state=RUN_COVERAGE_COMPLETE,
    )
    assert complete.at_least(MATERIALITY_MATERIAL)


def test_new_material_signal_creates_alert_and_successful_delivery_moves_baseline(
    tmp_path: Path,
) -> None:
    db = tmp_path / "cloud.db"
    ids = seed_scope(db)
    seed_signal(db, signal_id="s1", snapshot_id="snap1")
    factory = SQLiteUnitOfWorkFactory(db)
    clock = Clock()
    runtime = AlertDigestRuntime(factory, LocalDeliveryAdapter(), clock=clock)

    candidate = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="run-1",
        label="MCP adoption accelerates",
        state=state("s1", "snap1"),
    )
    assert candidate.reason == REASON_QUALIFIED
    alert = runtime.alert_for_candidate(ids["workspace"], candidate.candidate_id)
    assert alert is not None
    assert alert.delivery_state == DELIVERY_PENDING

    delivered = runtime.deliver_alert(ids["workspace"], alert.alert_id)
    assert delivered.delivery_state == DELIVERY_DELIVERED

    with factory() as uow:
        baseline = uow.alerts.get_baseline(ids["workspace"], ids["watchlist"], "s1")
        assert baseline is not None
        assert baseline.snapshot_id == "snap1"
        assert len(uow.alerts.attempts_for(ids["workspace"], TARGET_ALERT, alert.alert_id)) == 1
        assert uow.usage.total(ids["workspace"], USAGE_ALERT_CANDIDATE) == 1
        assert uow.usage.total(ids["workspace"], USAGE_ALERT_CREATED) == 1
        assert uow.usage.total(ids["workspace"], USAGE_DELIVERY_ATTEMPT) == 1
        assert uow.usage.total(ids["workspace"], USAGE_DELIVERY_SUCCESS) == 1


def test_candidate_suppression_reasons_and_duplicate(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed_scope(db)
    factory = SQLiteUnitOfWorkFactory(db)
    for signal_id in ("muted", "dismissed", "weak", "minor", "dup"):
        seed_signal(db, signal_id=signal_id, snapshot_id=f"{signal_id}-snap")

    runtime = AlertDigestRuntime(factory, LocalDeliveryAdapter(), clock=Clock())
    muted = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r1",
        label="Muted",
        state=state("muted", "muted-snap"),
        match_status="muted",
    )
    assert muted.reason == REASON_MUTED

    dismissed = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r2",
        label="Dismissed",
        state=state("dismissed", "dismissed-snap"),
        match_status="dismissed",
    )
    assert dismissed.reason == REASON_DISMISSED

    weak = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r3",
        label="Weak",
        state=state("weak", "weak-snap", relevance=47),
    )
    assert weak.reason == REASON_BELOW_RELEVANCE

    # A delivered baseline with no meaningful change creates a below-materiality candidate.
    seed_signal(db, signal_id="minor", snapshot_id="minor-prev")
    old = state("minor", "minor-prev", signal_score=70, relevance=82)
    with factory() as uow:
        uow.alerts.upsert_baseline(
            AlertBaseline.of(
                workspace_id=ids["workspace"],
                watchlist_id=ids["watchlist"],
                signal_id="minor",
                alert_id="old-alert",
                state=old,
                delivered_at=NOW - timedelta(days=2),
            )
        )
        uow.commit()
    minor = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r4",
        label="Minor",
        state=state("minor", "minor-snap", signal_score=71, relevance=83),
    )
    assert minor.reason == REASON_BELOW_MATERIALITY

    duplicate1 = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r5",
        label="Dup",
        state=state("dup", "dup-snap"),
    )
    duplicate2 = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r5",
        label="Dup",
        state=state("dup", "dup-snap"),
    )
    assert duplicate1.reason == REASON_QUALIFIED
    assert duplicate2.reason == REASON_DUPLICATE
    with factory() as uow:
        assert len(uow.alerts.candidates_for_run(ids["workspace"], "r5")) == 1
        assert len(uow.alerts.list_alerts(ids["workspace"], ids["radar"])) == 1


def test_cooldown_after_success_but_failed_delivery_does_not_move_baseline(
    tmp_path: Path,
) -> None:
    db = tmp_path / "cloud.db"
    ids = seed_scope(db)
    factory = SQLiteUnitOfWorkFactory(db)
    seed_signal(db, signal_id="s1", snapshot_id="snap1")
    seed_signal(db, signal_id="s1", snapshot_id="snap2", score=90)
    clock = Clock()
    runtime = AlertDigestRuntime(factory, LocalDeliveryAdapter(), clock=clock)

    first = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r1",
        label="S1",
        state=state("s1", "snap1"),
    )
    alert = runtime.alert_for_candidate(ids["workspace"], first.candidate_id)
    assert alert is not None
    runtime.deliver_alert(ids["workspace"], alert.alert_id)

    second = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r2",
        label="S1",
        state=state(
            "s1",
            "snap2",
            signal_score=90,
            relevance=90,
            lifecycle="sustained",
        ),
    )
    assert second.reason == REASON_COOLDOWN

    db2 = tmp_path / "failed.db"
    ids2 = seed_scope(db2, "b")
    factory2 = SQLiteUnitOfWorkFactory(db2)
    seed_signal(db2, signal_id="f1", snapshot_id="f-snap1")
    seed_signal(db2, signal_id="f1", snapshot_id="f-snap2", score=90)
    failing = LocalDeliveryAdapter(fail_attempts_below=99)
    runtime2 = AlertDigestRuntime(factory2, failing, clock=Clock())
    c1 = runtime2.evaluate(
        workspace_id=ids2["workspace"],
        radar_id=ids2["radar"],
        watchlist_id=ids2["watchlist"],
        run_id="fr1",
        label="F1",
        state=state("f1", "f-snap1"),
    )
    a1 = runtime2.alert_for_candidate(ids2["workspace"], c1.candidate_id)
    assert a1 is not None
    failed = runtime2.deliver_alert(ids2["workspace"], a1.alert_id)
    assert failed.delivery_state == DELIVERY_PENDING
    with factory2() as uow:
        assert uow.alerts.get_baseline(ids2["workspace"], ids2["watchlist"], "f1") is None
        assert uow.usage.total(ids2["workspace"], USAGE_DELIVERY_FAILURE) == 1

    c2 = runtime2.evaluate(
        workspace_id=ids2["workspace"],
        radar_id=ids2["radar"],
        watchlist_id=ids2["watchlist"],
        run_id="fr2",
        label="F1",
        state=state(
            "f1",
            "f-snap2",
            signal_score=90,
            relevance=90,
            lifecycle="sustained",
        ),
    )
    assert c2.reason == REASON_QUALIFIED


def test_delivery_retry_then_success_and_exhaustion(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed_scope(db)
    factory = SQLiteUnitOfWorkFactory(db)
    seed_signal(db, signal_id="s1", snapshot_id="snap1")
    adapter = LocalDeliveryAdapter(fail_attempts_below=2)
    runtime = AlertDigestRuntime(factory, adapter, clock=Clock())
    candidate = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r1",
        label="S1",
        state=state("s1", "snap1"),
    )
    alert = runtime.alert_for_candidate(ids["workspace"], candidate.candidate_id)
    assert alert is not None
    first = runtime.deliver_alert(ids["workspace"], alert.alert_id)
    assert first.delivery_state == DELIVERY_PENDING
    second = runtime.deliver_alert(ids["workspace"], alert.alert_id)
    assert second.delivery_state == DELIVERY_DELIVERED
    with factory() as uow:
        assert len(uow.alerts.attempts_for(ids["workspace"], TARGET_ALERT, alert.alert_id)) == 2

    db2 = tmp_path / "exhaust.db"
    ids2 = seed_scope(db2, "c")
    factory2 = SQLiteUnitOfWorkFactory(db2)
    seed_signal(db2, signal_id="x1", snapshot_id="x-snap")
    runtime2 = AlertDigestRuntime(
        factory2,
        LocalDeliveryAdapter(fail_attempts_below=99),
        clock=Clock(),
    )
    c2 = runtime2.evaluate(
        workspace_id=ids2["workspace"],
        radar_id=ids2["radar"],
        watchlist_id=ids2["watchlist"],
        run_id="xr1",
        label="X1",
        state=state("x1", "x-snap"),
    )
    a2 = runtime2.alert_for_candidate(ids2["workspace"], c2.candidate_id)
    assert a2 is not None
    result = a2
    for _ in range(3):
        result = runtime2.deliver_alert(ids2["workspace"], a2.alert_id)
    assert result.delivery_state == DELIVERY_FAILED
    with factory2() as uow:
        assert len(uow.alerts.attempts_for(ids2["workspace"], TARGET_ALERT, a2.alert_id)) == 3


def test_daily_digest_max_five_dedupes_signal_and_delivers_with_retry(
    tmp_path: Path,
) -> None:
    db = tmp_path / "cloud.db"
    ids = seed_scope(db)
    factory = SQLiteUnitOfWorkFactory(db)
    clock = Clock()
    runtime = AlertDigestRuntime(
        factory,
        LocalDeliveryAdapter(fail_attempts_below=2),
        clock=clock,
    )

    for index in range(8):
        signal_id = f"s{index}"
        snapshot_id = f"snap{index}"
        seed_signal(db, signal_id=signal_id, snapshot_id=snapshot_id)
        runtime.evaluate(
            workspace_id=ids["workspace"],
            radar_id=ids["radar"],
            watchlist_id=ids["watchlist"],
            run_id=f"run-{index}",
            label=f"Signal {index}",
            state=state(
                signal_id,
                snapshot_id,
                signal_score=90 - index,
                relevance=95 - index,
                observed_at=NOW + timedelta(minutes=index),
            ),
        )

    # Same signal, new snapshot: two candidates, one digest item.
    seed_signal(db, signal_id="s0", snapshot_id="snap0b", score=95)
    runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="run-0b",
        label="Signal 0 newer",
        state=state(
            "s0",
            "snap0b",
            signal_score=95,
            relevance=96,
            lifecycle="sustained",
            observed_at=NOW + timedelta(minutes=20),
        ),
    )

    digest = runtime.build_digest(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        radar_name="AI Radar",
        day=NOW,
    )
    assert digest is not None
    assert digest.item_count == 5
    with factory() as uow:
        items = uow.digests.items(ids["workspace"], digest.digest_id)
        assert len(items) == 5
        assert len({item.signal_id for item in items}) == 5
        assert uow.usage.total(ids["workspace"], USAGE_DIGEST_CREATED) == 1

    first = runtime.deliver_digest(ids["workspace"], digest.digest_id)
    assert first.delivery_state == DELIVERY_PENDING
    second = runtime.deliver_digest(ids["workspace"], digest.digest_id)
    assert second.delivery_state == DELIVERY_DELIVERED
    with factory() as uow:
        attempts = uow.alerts.attempts_for(ids["workspace"], TARGET_DIGEST, digest.digest_id)
        assert len(attempts) == 2


def test_empty_digest_and_tenant_isolation(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    a = seed_scope(db, "a")
    b = seed_scope(db, "b")
    factory = SQLiteUnitOfWorkFactory(db)
    runtime = AlertDigestRuntime(factory, LocalDeliveryAdapter(), clock=Clock())

    assert (
        runtime.build_digest(
            workspace_id=a["workspace"],
            radar_id=a["radar"],
            radar_name="A",
            day=NOW,
        )
        is None
    )

    seed_signal(db, signal_id="b-signal", snapshot_id="b-snap")
    candidate = runtime.evaluate(
        workspace_id=b["workspace"],
        radar_id=b["radar"],
        watchlist_id=b["watchlist"],
        run_id="b-run",
        label="B only",
        state=state("b-signal", "b-snap"),
    )
    alert = runtime.alert_for_candidate(b["workspace"], candidate.candidate_id)
    assert alert is not None
    assert runtime.alert_for_candidate(a["workspace"], candidate.candidate_id) is None


def test_migration_0003_bootstrap_repeat_and_schema(tmp_path: Path) -> None:
    db = tmp_path / "migration.db"
    factory = SQLiteUnitOfWorkFactory(db)
    first = factory.bootstrap()
    second = factory.bootstrap()
    assert first == [
        "0001_cloud_foundation.sql",
        "0002_signal_matching_relevance.sql",
        "0003_alert_digest_delivery.sql",
        "0004_scheduled_radar_orchestration.sql",
    ]
    assert second == first
    conn = connect(db)
    try:
        tables = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "cloud_alert_policy",
            "cloud_alert_baseline",
            "cloud_alert_candidate",
            "cloud_alert",
            "cloud_digest",
            "cloud_digest_item",
            "cloud_delivery_attempt",
        } <= tables
    finally:
        conn.close()


def test_policy_can_disable_delivery_and_persists(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed_scope(db)
    factory = SQLiteUnitOfWorkFactory(db)
    seed_signal(db, signal_id="s1", snapshot_id="snap1")
    runtime = AlertDigestRuntime(factory, LocalDeliveryAdapter(), clock=Clock())
    policy = AlertPolicy.create(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        enabled=False,
        updated_at=NOW,
    )
    runtime.set_policy(policy)
    candidate = runtime.evaluate(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="r1",
        label="S1",
        state=state("s1", "snap1"),
    )
    assert candidate.reason != REASON_QUALIFIED
    assert runtime.alert_for_candidate(ids["workspace"], candidate.candidate_id) is None
