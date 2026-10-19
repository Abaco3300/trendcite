"""Offline-testable hosted proof executor. Never invoked by CI or import."""

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from trendcite.cloud.tc_p008_hosted_evidence_gate import assess_hosted_probe
from trendcite.cloud.tc_p008_session_abort import abort_session
from trendcite.cloud.tc_p008_shutdown_classification import classify_shutdown


def execute_probe(connect: Callable[[], Any], *, approved: bool = False) -> dict[str, str]:
    """Single bounded run on a separately authenticated and verified sandbox."""
    if approved is not True:
        raise RuntimeError("explicit hosted probe approval required")
    raise RuntimeError("hosted runner blocked: independent cleanup audit not implemented")
    run_id, key = str(uuid.uuid4()), str(uuid.uuid4())
    state: dict[str, object] = {"probe_run": run_id, "probe_key": key}
    ready, begun, release = threading.Event(), threading.Event(), threading.Event()
    faults: list[str] = []
    threads: list[threading.Thread] = []

    def participant(name: str) -> None:
        db = None
        try:
            if name == "contender" and not ready.wait(6):
                raise RuntimeError("holder deadline")
            with connect() as db:
                db.execute("SET LOCAL statement_timeout = '8s'")
                db.execute("SET LOCAL lock_timeout = '5s'")
                db.execute("SET LOCAL idle_in_transaction_session_timeout = '10s'")
                pid = db.execute("SELECT pg_backend_pid()").fetchone()[0]
                state[name + "_pid"] = pid
                if name == "contender":
                    begun.set()
                returned = db.execute(
                    "INSERT INTO tc_p008_isolated.unique_write_probe "
                    "(probe_key,probe_run,contender) VALUES (%s,%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING probe_key",
                    (key, run_id, name),
                ).fetchall()
                if name == "holder":
                    if len(returned) != 1:
                        raise RuntimeError("holder insert not established")
                    ready.set()
                    if not release.wait(6):
                        raise RuntimeError("release deadline")
                    db.commit()
                    state["holder_commit"] = True
                else:
                    state["contender_insert_count"] = len(returned)
                    db.commit()
        except Exception as exc:
            faults.append(name + ":" + type(exc).__name__)
            if db is not None:
                try:
                    abort_session(db)
                except RuntimeError:
                    faults.append(name + ":abort_incomplete")
            ready.set()
            begun.set()

    try:
        for name in ("holder", "contender"):
            thread = threading.Thread(target=participant, args=(name,), daemon=True)
            threads.append(thread)
            thread.start()
        if not begun.wait(7):
            raise RuntimeError("contender start deadline")
        with connect() as observer:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                a, b = state.get("holder_pid"), state.get("contender_pid")
                if type(a) is int and type(b) is int:
                    blockers = observer.execute("SELECT pg_blocking_pids(%s)", (b,)).fetchone()[0]
                    if a in blockers:
                        state["blocking_pid"], state["blocked_pid"] = a, b
                        break
                time.sleep(0.05)
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=11)
        if any(thread.is_alive() for thread in threads):
            faults.append("sessions_not_closed")
        # A failed observer connection must not silently bypass cleanup.
        with connect() as cleanup:
            try:
                if not faults:
                    rows = cleanup.execute(
                        "SELECT contender FROM tc_p008_isolated.unique_write_probe "
                        "WHERE probe_key=%s AND probe_run=%s",
                        (key, run_id),
                    ).fetchall()
                    state["durable_count"] = len(rows)
                    state["winner"] = rows[0][0] if len(rows) == 1 else None
            finally:
                cleanup.execute(
                    "DELETE FROM tc_p008_isolated.unique_write_probe "
                    "WHERE probe_key=%s AND probe_run=%s",
                    (key, run_id),
                )
                cleanup.commit()
                remaining = cleanup.execute(
                    "SELECT count(*) FROM tc_p008_isolated.unique_write_probe "
                    "WHERE probe_key=%s AND probe_run=%s",
                    (key, run_id),
                ).fetchone()[0]
                state["cleanup_count"] = remaining
    if faults:
        raise RuntimeError("hosted probe failed closed: " + ",".join(faults))
    audited_remaining = independently_audit_cleanup(connect, run_id, key)
    state["isolated_nonprod"] = True
    cleanup_evidence = {
        "target_isolated": True,
        "cleanup_targeted": True,
        "independent_readback": True,
        "sessions_closed": True,
        "probe_run": run_id,
        "probe_key": key,
        "remaining_rows": audited_remaining,
    }
    classification = classify_shutdown(
        observer_ok=state.get("blocking_pid") == state.get("holder_pid"),
        cleanup_ok=state.get("cleanup_count") == 0,
        sessions_closed=not any(thread.is_alive() for thread in threads),
        audited_zero=audited_remaining == 0,
    )
    if classification != "REQUIRES_INDEPENDENT_HOSTED_REVIEW":
        raise RuntimeError("TC-P008 shutdown: " + classification)
    return assess_hosted_probe(state, cleanup_evidence, hosted_run_attested=False)


def independently_audit_cleanup(connect: Callable[[], Any], run_id: str, key: str) -> int:
    """Read exact probe scope via a new connection; reject any residue."""
    if not run_id or not key:
        raise RuntimeError("cleanup audit identifiers missing")
    with connect() as observer:
        record = observer.execute(
            "SELECT count(*) FROM tc_p008_isolated.unique_write_probe "
            "WHERE probe_run=%s AND probe_key=%s",
            (run_id, key),
        ).fetchone()
    if record is None or len(record) != 1 or type(record[0]) is not int or record[0] != 0:
        raise RuntimeError("independent cleanup audit failed closed")
    return record[0]
