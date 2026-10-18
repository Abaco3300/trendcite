"""Offline-testable hosted proof executor. Never invoked by CI or import."""

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from trendcite.cloud.tc_p008_hosted_evidence_gate import assess_hosted_probe


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
    state["isolated_nonprod"] = True
    cleanup_evidence = {
        "target_isolated": True,
        "cleanup_targeted": True,
        "independent_readback": False,
        "sessions_closed": True,
        "probe_run": run_id,
        "probe_key": key,
        "remaining_rows": state["cleanup_count"],
    }
    return assess_hosted_probe(state, cleanup_evidence, hosted_run_attested=False)
