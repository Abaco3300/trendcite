from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trendcite.cloud.alert_services import AlertService, DeliveryService, DigestService
from trendcite.cloud.db.sqlite import SQLiteUnitOfWorkFactory, connect
from trendcite.cloud.delivery import LocalDeliveryAdapter
from trendcite.cloud.domain.alerts import (
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    MATERIALITY_MATERIAL,
    REASON_BELOW_RELEVANCE,
    REASON_COOLDOWN,
    REASON_DISMISSED,
    REASON_DUPLICATE,
    REASON_MUTED,
    REASON_QUALIFIED,
    AlertPolicy,
    MaterialityService,
    SignalState,
)
from trendcite.cloud.domain.radar import RUN_COVERAGE_COMPLETE, RUN_COVERAGE_DEGRADED

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


def seed(db: Path, *, suffix: str = "a", signals: int = 1, snapshots: int = 2) -> dict[str, str]:
    SQLiteUnitOfWorkFactory(db).bootstrap()
    workspace = f"workspace-{suffix}"
    watchlist = f"watchlist-{suffix}"
    radar = f"radar-{suffix}"
    radar_version = f"radar-version-{suffix}"
    conn = connect(db)
    try:
        conn.execute(
            "INSERT INTO cloud_workspace(workspace_id,slug,name,created_at) VALUES (?,?,?,?)",
            (workspace, f"ws-{suffix}", f"Workspace {suffix}", NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO cloud_watchlist(watchlist_id,workspace_id,name,created_at) "
            "VALUES (?,?,?,?)",
            (watchlist, workspace, "AI Signals", NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO cloud_watchlist_version("
            "version_id,watchlist_id,workspace_id,version_number,include_terms,exclude_terms,"
            "match_mode,matcher_version,created_at,entities,domains"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"watchlist-version-{suffix}",
                watchlist,
                workspace,
                1,
                '["mcp"]',
                "[]",
                "any",
                "watchlist-match-v2",
                NOW.isoformat(),
                "[]",
                "[]",
            ),
        )
        conn.execute(
            "INSERT INTO cloud_radar(radar_id,workspace_id,name,created_at) VALUES (?,?,?,?)",
            (radar, workspace, "Radar", NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO cloud_radar_version("
            "version_id,radar_id,workspace_id,version_number,watchlist_version_ids,sources,niche,"
            "top,created_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                radar_version,
                radar,
                workspace,
                1,
                f'["watchlist-version-{suffix}"]',
                '["hackernews"]',
                "[]",
                5,
                NOW.isoformat(),
            ),
        )
        for index in range(signals):
            signal_id = f"signal-{suffix}-{index}"
            conn.execute(
                "INSERT INTO cloud_signal("
                "signal_id,signal_key,label,related_terms,first_seen_at,last_seen_at,signal_id_version"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    signal_id,
                    f"signal-key-{suffix}-{index}",
                    f"Signal {index}",
                    "[]",
                    NOW.isoformat(),
                    NOW.isoformat(),
                    "signal-id-v1",
                ),
            )
            for snap in range(snapshots):
                snapshot_id = f"snapshot-{suffix}-{index}-{snap}"
                conn.execute(
                    "INSERT INTO cloud_signal_evaluation("
                    "snapshot_id,signal_id,captured_at,evaluation_version,evidence_set_version,score,"
                    "confidence,state,observation_count,story_count,source_count,component_values"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        snapshot_id,
                        signal_id,
                        (NOW + timedelta(minutes=snap)).isoformat(),
                        "signal-eval-v1",
                        "evidence-v1",
                        70 + snap * 25,
                        "high",
                        "emerging" if snap == 0 else "accelerating",
                        5,
                        2,
                        2,
                        "{}",
                    ),
                )
        conn.commit()
    finally:
        conn.close()
    return {
        "workspace": workspace,
        "watchlist": watchlist,
        "radar": radar,
        "radar_version": radar_version,
    }


def state(
    suffix: str,
    signal_index: int = 0,
    snapshot_index: int = 0,
    *,
    relevance: float = 82.0,
    signal_score: float | None = None,
    lifecycle: str | None = None,
    velocity: float = 0.5,
    source_count: int = 2,
    counterevidence: tuple[str, ...] = (),
) -> SignalState:
    return SignalState.create(
        signal_id=f"signal-{suffix}-{signal_index}",
        snapshot_id=f"snapshot-{suffix}-{signal_index}-{snapshot_index}",
        signal_score=signal_score if signal_score is not None else 70 + snapshot_index * 25,
        relevance_score=relevance,
        lifecycle_state=lifecycle or ("emerging" if snapshot_index == 0 else "accelerating"),
        velocity=velocity,
        source_count=source_count,
        counterevidence=counterevidence,
        observed_at=NOW + timedelta(minutes=signal_index + snapshot_index),
    )


def qualify(
    service: AlertService,
    ids: dict[str, str],
    current: SignalState,
    *,
    match_status: str = "active",
    coverage: str = RUN_COVERAGE_COMPLETE,
):
    return service.qualify(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        watchlist_id=ids["watchlist"],
        run_id="run-1",
        label=current.signal_id,
        state=current,
        match_status=match_status,
        coverage_state=coverage,
    )


def test_materiality_uses_delivered_baseline_and_withholds_degraded_decline(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed(db)
    clock = Clock()
    alerts = AlertService(SQLiteUnitOfWorkFactory(db), clock=clock)
    first = qualify(alerts, ids, state("a"))
    alert = alerts.materialize(first)
    assert alert is not None
    delivered = DeliveryService(
        SQLiteUnitOfWorkFactory(db), LocalDeliveryAdapter(), clock=clock
    ).deliver_alert(ids["workspace"], alert.alert_id)
    assert delivered.delivery_state == DELIVERY_DELIVERED

    with SQLiteUnitOfWorkFactory(db)() as uow:
        baseline = uow.alerts.get_baseline(ids["workspace"], ids["watchlist"], "signal-a-0")
        uow.commit()
    assert baseline is not None
    declined = state(
        "a",
        snapshot_index=1,
        relevance=60,
        signal_score=40,
        lifecycle="dormant",
        velocity=0.1,
        source_count=0,
    )
    evaluation = MaterialityService().evaluate(
        declined,
        baseline,
        coverage_state=RUN_COVERAGE_DEGRADED,
    )
    assert evaluation.coverage_degraded
    assert evaluation.withheld_declines


def test_qualification_suppression_duplicate_and_cooldown(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed(db)
    factory = SQLiteUnitOfWorkFactory(db)
    clock = Clock()
    service = AlertService(factory, clock=clock)

    weak = qualify(service, ids, state("a", relevance=47))
    assert weak.reason == REASON_BELOW_RELEVANCE

    # A distinct database keeps deterministic candidate identity from the weak case.
    db2 = tmp_path / "states.db"
    ids2 = seed(db2, suffix="b")
    factory2 = SQLiteUnitOfWorkFactory(db2)
    service2 = AlertService(factory2, clock=Clock())
    muted = qualify(service2, ids2, state("b"), match_status="muted")
    assert muted.reason == REASON_MUTED

    db3 = tmp_path / "dismissed.db"
    ids3 = seed(db3, suffix="c")
    service3 = AlertService(SQLiteUnitOfWorkFactory(db3), clock=Clock())
    dismissed = qualify(service3, ids3, state("c"), match_status="dismissed")
    assert dismissed.reason == REASON_DISMISSED

    db4 = tmp_path / "duplicate.db"
    ids4 = seed(db4, suffix="d")
    factory4 = SQLiteUnitOfWorkFactory(db4)
    clock4 = Clock()
    service4 = AlertService(factory4, clock=clock4)
    first = qualify(service4, ids4, state("d"))
    assert first.reason == REASON_QUALIFIED
    duplicate = qualify(service4, ids4, state("d"))
    assert duplicate.reason == REASON_DUPLICATE

    alert = service4.materialize(first)
    assert alert is not None
    DeliveryService(factory4, LocalDeliveryAdapter(), clock=clock4).deliver_alert(
        ids4["workspace"], alert.alert_id
    )
    second = qualify(
        service4,
        ids4,
        state("d", snapshot_index=1, relevance=90, signal_score=95),
    )
    assert second.reason == REASON_COOLDOWN


def test_failed_delivery_does_not_move_baseline_and_retry_succeeds(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed(db)
    factory = SQLiteUnitOfWorkFactory(db)
    clock = Clock()
    service = AlertService(factory, clock=clock)
    candidate = qualify(service, ids, state("a"))
    alert = service.materialize(candidate)
    assert alert is not None

    delivery = DeliveryService(
        factory,
        LocalDeliveryAdapter(fail_attempts_below=2),
        clock=clock,
    )
    first = delivery.deliver_alert(ids["workspace"], alert.alert_id)
    assert first.delivery_state == DELIVERY_PENDING
    with factory() as uow:
        baseline = uow.alerts.get_baseline(ids["workspace"], ids["watchlist"], "signal-a-0")
        uow.commit()
    assert baseline is None

    second = delivery.deliver_alert(ids["workspace"], alert.alert_id)
    assert second.delivery_state == DELIVERY_DELIVERED
    with factory() as uow:
        attempts = uow.alerts.attempts_for(ids["workspace"], "alert", alert.alert_id)
        baseline = uow.alerts.get_baseline(ids["workspace"], ids["watchlist"], "signal-a-0")
        uow.commit()
    assert len(attempts) == 2
    assert baseline is not None


def test_delivery_exhaustion_marks_one_alert_failed(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed(db)
    factory = SQLiteUnitOfWorkFactory(db)
    service = AlertService(factory, clock=Clock())
    candidate = qualify(service, ids, state("a"))
    alert = service.materialize(candidate)
    assert alert is not None
    adapter = LocalDeliveryAdapter(fail_targets={alert.alert_id})
    delivery = DeliveryService(factory, adapter, clock=Clock())

    current = alert
    for _ in range(3):
        current = delivery.deliver_alert(ids["workspace"], alert.alert_id)
    assert current.delivery_state == DELIVERY_FAILED
    with factory() as uow:
        alerts = uow.alerts.list_alerts(ids["workspace"], ids["radar"])
        attempts = uow.alerts.attempts_for(ids["workspace"], "alert", alert.alert_id)
        uow.commit()
    assert len(alerts) == 1
    assert len(attempts) == 3


def test_digest_is_top_five_deduped_idempotent_and_deliverable(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed(db, signals=8, snapshots=2)
    factory = SQLiteUnitOfWorkFactory(db)
    service = AlertService(factory, clock=Clock())

    for index in range(8):
        candidate = qualify(
            service,
            ids,
            state("a", signal_index=index, relevance=90 - index),
        )
        assert candidate.reason == REASON_QUALIFIED

    # A second snapshot for signal 0 yields another candidate, but not another digest item.
    qualify(
        service,
        ids,
        state("a", signal_index=0, snapshot_index=1, relevance=95, signal_score=95),
    )

    digest_service = DigestService(factory, clock=Clock())
    digest = digest_service.build(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        radar_name="Radar",
        day=NOW,
    )
    assert digest is not None
    with factory() as uow:
        items = uow.digests.items(ids["workspace"], digest.digest_id)
        uow.commit()
    assert len(items) == 5
    assert len({item.signal_id for item in items}) == 5

    rebuilt = digest_service.build(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        radar_name="Radar",
        day=NOW,
    )
    assert rebuilt is not None
    assert rebuilt.digest_id == digest.digest_id

    adapter = LocalDeliveryAdapter(fail_attempts_below=2)
    delivery = DeliveryService(factory, adapter, clock=Clock())
    first = delivery.deliver_digest(ids["workspace"], digest.digest_id)
    assert first.delivery_state == DELIVERY_PENDING
    second = delivery.deliver_digest(ids["workspace"], digest.digest_id)
    assert second.delivery_state == DELIVERY_DELIVERED


def test_empty_digest_and_tenant_isolation(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    a = seed(db, suffix="a")
    b = seed(db, suffix="b")
    factory = SQLiteUnitOfWorkFactory(db)

    assert (
        DigestService(factory, clock=Clock()).build(
            workspace_id=a["workspace"],
            radar_id=a["radar"],
            radar_name="Radar",
            day=NOW,
        )
        is None
    )

    candidate_b = qualify(AlertService(factory, clock=Clock()), b, state("b"))
    with factory() as uow:
        wrong = uow.alerts.get_candidate(a["workspace"], candidate_b.candidate_id)
        right = uow.alerts.get_candidate(b["workspace"], candidate_b.candidate_id)
        uow.commit()
    assert wrong is None
    assert right is not None


def test_alert_policy_defaults_and_migration_0003(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    ids = seed(db)
    policy = AlertPolicy.default_for(
        workspace_id=ids["workspace"],
        radar_id=ids["radar"],
        updated_at=NOW,
    )
    assert policy.min_relevance == 60.0
    assert policy.min_materiality == MATERIALITY_MATERIAL
    assert policy.cooldown_hours == 24.0
    assert policy.digest_max_items == 5
    assert policy.max_delivery_attempts == 3

    names = SQLiteUnitOfWorkFactory(db).bootstrap()
    assert names[-1] == "0003_alert_digest_delivery.sql"
