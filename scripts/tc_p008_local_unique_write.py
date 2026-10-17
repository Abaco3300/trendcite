"""Disposable LOCAL PostgreSQL proof; never run against a hosted database."""

import argparse
import json
import threading
import time
import uuid
from urllib.parse import urlsplit

from trendcite.cloud.tc_p008_unique_write_contention import validate_unique_write_contention


def run_local(dsn: str) -> dict[str, object]:
    info = urlsplit(dsn)
    if (
        info.scheme not in ("postgresql", "postgres")
        or info.hostname not in ("127.0.0.1", "localhost")
        or info.path != "/tc_p008_local"
        or info.query
        or info.fragment
    ):
        raise RuntimeError("local loopback DSN required")
    import psycopg

    run_id, key = uuid.uuid4(), uuid.uuid4()
    a_inserted = threading.Event()
    b_attempting = threading.Event()
    release_a = threading.Event()
    failures: list[str] = []
    result: dict[str, object] = {}
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute("CREATE SCHEMA tc_p008_disposable")
        admin.execute(
            "CREATE TABLE tc_p008_disposable.probe "
            "(probe_key uuid PRIMARY KEY, run_id uuid NOT NULL, contender text NOT NULL)"
        )
    try:

        def holder() -> None:
            try:
                with psycopg.connect(dsn) as conn:
                    conn.execute("SET statement_timeout = '8s'")
                    result["holder_pid"] = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                    conn.execute(
                        "INSERT INTO tc_p008_disposable.probe VALUES (%s,%s,'holder')",
                        (key, run_id),
                    )
                    a_inserted.set()
                    if not release_a.wait(6):
                        raise RuntimeError("holder deadline")
                    conn.commit()
                    result["holder_commit"] = True
            except Exception as exc:
                failures.append("holder: " + type(exc).__name__)
                a_inserted.set()

        def contender() -> None:
            try:
                if not a_inserted.wait(6):
                    raise RuntimeError("insert barrier deadline")
                with psycopg.connect(dsn) as conn:
                    conn.execute("SET statement_timeout = '8s'")
                    result["contender_pid"] = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                    b_attempting.set()
                    row = conn.execute(
                        "INSERT INTO tc_p008_disposable.probe VALUES (%s,%s,'contender') "
                        "ON CONFLICT DO NOTHING RETURNING probe_key",
                        (key, run_id),
                    ).fetchall()
                    result["contender_insert_count"] = len(row)
                    conn.commit()
            except Exception as exc:
                failures.append("contender: " + type(exc).__name__)
                b_attempting.set()

        t_a = threading.Thread(target=holder)
        t_b = threading.Thread(target=contender)
        t_a.start()
        t_b.start()
        try:
            if not b_attempting.wait(6):
                raise RuntimeError("contender start deadline")
            deadline = time.monotonic() + 5
            with psycopg.connect(dsn, autocommit=True) as observer:
                while time.monotonic() < deadline:
                    pid = result.get("contender_pid")
                    a_pid = result.get("holder_pid")
                    if pid and a_pid:
                        blocked_by = observer.execute(
                            "SELECT pg_blocking_pids(%s)", (pid,)
                        ).fetchone()[0]
                        if a_pid in blocked_by:
                            result["blocking_pid"] = a_pid
                            result["blocked_pid"] = pid
                            break
                    time.sleep(0.05)
        finally:
            release_a.set()
            t_a.join(timeout=10)
            t_b.join(timeout=10)
        if t_a.is_alive() or t_b.is_alive() or failures:
            raise RuntimeError("transaction failed or deadline exceeded: " + str(failures))
        with psycopg.connect(dsn, autocommit=True) as observer:
            rows = observer.execute(
                "SELECT contender FROM tc_p008_disposable.probe WHERE probe_key=%s AND run_id=%s",
                (key, run_id),
            ).fetchall()
            result["durable_count"] = len(rows)
            result["winner"] = rows[0][0] if len(rows) == 1 else None
            observer.execute(
                "DELETE FROM tc_p008_disposable.probe WHERE probe_key=%s AND run_id=%s",
                (key, run_id),
            )
            result["cleanup_count"] = observer.execute(
                "SELECT count(*) FROM tc_p008_disposable.probe WHERE probe_key=%s AND run_id=%s",
                (key, run_id),
            ).fetchone()[0]
        result["isolated_nonprod"] = True
        verdict = validate_unique_write_contention(result)
        return {"observations": result, "verdict": verdict}
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute("DROP TABLE tc_p008_disposable.probe")
            admin.execute("DROP SCHEMA tc_p008_disposable")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()
    print(json.dumps(run_local(args.dsn), sort_keys=True))
