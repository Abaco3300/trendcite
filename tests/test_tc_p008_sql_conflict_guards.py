"""Repository-source regression checks for the real PostgreSQL conflict fix."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_primary_key_and_idempotency_conflicts_are_both_handled() -> None:
    for name in ("postgres.py", "postgres_execution.py"):
        text = (ROOT / "src/trendcite/cloud/db" / name).read_text(encoding="utf-8")
        assert "INSERT INTO trendcite.cloud_radar_run" in text
        assert "ON CONFLICT DO NOTHING" in text
        assert "WHERE workspace_id=$1 AND idempotency_key=$2" in text
        assert "radar run insert was not observable" in text


def test_queue_conflict_must_not_discard_unrelated_work() -> None:
    text = (ROOT / "src/trendcite/cloud/db/postgres.py").read_text(encoding="utf-8")
    assert "INSERT INTO trendcite.cloud_queue_delivery" in text
    assert "ON CONFLICT DO NOTHING" in text
    assert "WHERE workspace_id=$1 AND logical_id=$2" in text
    assert 'raise RuntimeError("queue delivery identity collision")' in text
