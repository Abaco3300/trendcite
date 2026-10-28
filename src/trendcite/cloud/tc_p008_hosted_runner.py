"""Gated hosted proof executor for the dedicated TC-P008 sandbox.

Never invoked by CI or import. A successful run returns raw, secret-free
evidence for independent review; it never certifies the hosted criterion.
"""

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast

from trendcite.cloud.tc_p008_backend_cancel import cancel_and_verify_backends
from trendcite.cloud.tc_p008_cleanup_evidence import verify_probe_cleanup
from trendcite.cloud.tc_p008_session_abort import abort_session
from trendcite.cloud.tc_p008_shutdown_classification import classify_shutdown
from trendcite.cloud.tc_p008_unique_write_contention import validate_unique_write_contention

HOSTED_RESULT_PENDING = "NOT_VERIFIED_PENDING_INDEPENDENT_REVIEW"
# A closed client socket is not instantly removed from pg_stat_activity.
# Re-read on the same independent session for a bounded period before
# declaring a backend still alive (and escalating to cancellation).
BACKEND_EXIT_POLL_ATTEMPTS = 10
BACKEND_EXIT_POLL_INTERVAL_S = 0.2


@contextmanager
def _closing_connection(connect: Callable[[], Any]) -> Iterator[Any]:
    """Close the driver session, including after transaction-context exit."""
    connection = connect()
    try:
        with connection as db:
            yield db
    finally:
        connection.close()


def _recover_stalled_participants(
    connect: Callable[[], Any],
    threads: list[threading.Thread],
    pids: tuple[object, object],
) -> None:
    """Try query cancellation before allowing any subsequent cleanup."""
    if any(type(pid) is not int or pid <= 0 for pid in pids) or pids[0] == pids[1]:
        raise RuntimeError("TC-P008 stalled backends unverified: cleanup prohibited")
    cancellation_errors: list[str] = []
    for pid in pids:
        try:
            with _closing_connection(connect) as canceller:
                row = canceller.execute("SELECT pg_cancel_backend(%s)", (pid,)).fetchone()
                if row is None or len(row) != 1 or row[0] is not True:
                    cancellation_errors.append("cancel_not_confirmed")
        except Exception as exc:
            # Continue attempting cancellation of the other backend.
            cancellation_errors.append(type(exc).__name__)
    for thread in threads:
        thread.join(timeout=2)
    if any(thread.is_alive() for thread in threads):
        raise RuntimeError("TC-P008 stalled threads remain active: cleanup prohibited")
    # Cancellation failures cannot be reclassified as success by a later
    # point-in-time backend readback. Preserve the failure before new SQL.
    if cancellation_errors:
        raise RuntimeError("TC-P008 stalled cancellation unverified: cleanup prohibited")
    if not independently_verify_backends_terminated(
        connect, (cast(int, pids[0]), cast(int, pids[1]))
    ):
        raise RuntimeError("TC-P008 stalled backends remain active: cleanup prohibited")


def execute_probe(connect: Callable[[], Any], *, approved: bool = False) -> dict[str, object]:
    """Single bounded run on a separately authenticated and verified sandbox.

    ``connect`` must come from ``prepare_sandbox_connection`` (allowlisted
    target, verify-full TLS, restricted role). The result is evidence for
    independent review only; hosted certification stays NOT_VERIFIED.
    """
    if approved is not True:
        raise RuntimeError("explicit hosted probe approval required")
    if not callable(connect):
        raise RuntimeError("TC-P008 sandbox connection factory unavailable")
    return _run_probe_with_injected_connections(connect)


def _run_probe_with_injected_connections(connect: Callable[[], Any]) -> dict[str, object]:
    """Probe orchestration; offline tests inject synthetic connections."""
    run_id, key = str(uuid.uuid4()), str(uuid.uuid4())
    state: dict[str, object] = {"probe_run": run_id, "probe_key": key}
    ready, begun, release = threading.Event(), threading.Event(), threading.Event()
    faults: list[str] = []
    threads: list[threading.Thread] = []
    observer_failure: Exception | None = None
    cleanup_failure: Exception | None = None

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
        finally:
            # DB-API transaction context managers may commit/rollback without
            # closing the underlying PostgreSQL connection.
            if db is not None:
                try:
                    db.close()
                except Exception:
                    faults.append(name + ":close_failed")
                    ready.set()
                    begun.set()

    try:
        for name in ("holder", "contender"):
            thread = threading.Thread(target=participant, args=(name,), daemon=True)
            threads.append(thread)
            thread.start()
        if not begun.wait(7):
            raise RuntimeError("contender start deadline")
        with _closing_connection(connect) as observer:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                a, b = state.get("holder_pid"), state.get("contender_pid")
                if type(a) is int and type(b) is int:
                    blockers = observer.execute("SELECT pg_blocking_pids(%s)", (b,)).fetchone()[0]
                    if a in blockers:
                        state["blocking_pid"], state["blocked_pid"] = a, b
                        break
                time.sleep(0.05)
    except Exception as exc:
        observer_failure = exc
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=11)
        if any(thread.is_alive() for thread in threads):
            # Attempt bounded cancellation on independent connections; no
            # cleanup until both threads and both backends are gone.
            _recover_stalled_participants(
                connect,
                threads,
                (state.get("holder_pid"), state.get("contender_pid")),
            )
        # Thread termination alone never proves the PostgreSQL backend exited.
        # Unknown backend identity or unverified sessions must block mutation.
        holder_pid, contender_pid = state.get("holder_pid"), state.get("contender_pid")
        if not (
            type(holder_pid) is int
            and type(contender_pid) is int
            and holder_pid > 0
            and contender_pid > 0
            and holder_pid != contender_pid
        ):
            raise RuntimeError("TC-P008 backend identities unverified: cleanup prohibited")
        if not independently_verify_backends_terminated(connect, (holder_pid, contender_pid)):
            # Do not assume that a finished Python thread means a finished
            # PostgreSQL backend. Cancellation itself is not proof.
            def cancel_backend(pid: int) -> bool:
                with _closing_connection(connect) as canceller:
                    row = canceller.execute("SELECT pg_cancel_backend(%s)", (pid,)).fetchone()
                return row is not None and len(row) == 1 and row[0] is True

            try:
                cancel_and_verify_backends(
                    (holder_pid, contender_pid),
                    cancel=cancel_backend,
                    verify_absent=lambda pids: independently_verify_backends_terminated(
                        connect, pids
                    ),
                )
            except Exception as exc:
                raise RuntimeError(
                    "TC-P008 backend cancellation NOT_VERIFIED: cleanup prohibited"
                ) from exc
        # Failed observation cannot suppress the attempt to clean up.
        try:
            with _closing_connection(connect) as cleanup:
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
        except Exception as exc:
            cleanup_failure = exc
    if observer_failure is not None or cleanup_failure is not None or faults:
        failures = list(faults)
        if observer_failure is not None:
            failures.append("observer:" + type(observer_failure).__name__)
        if cleanup_failure is not None:
            failures.append("cleanup:" + type(cleanup_failure).__name__)
        raise RuntimeError("hosted probe failed closed: " + ",".join(failures))
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
    contract = validate_unique_write_contention(state)
    cleanup_contract = verify_probe_cleanup(cleanup_evidence)
    evidence: dict[str, object] = {
        key_name: state.get(key_name)
        for key_name in (
            "probe_run",
            "probe_key",
            "holder_pid",
            "contender_pid",
            "blocking_pid",
            "blocked_pid",
            "holder_commit",
            "contender_insert_count",
            "durable_count",
            "winner",
            "cleanup_count",
        )
    }
    evidence["independent_audit_remaining_rows"] = audited_remaining
    evidence["shutdown_classification"] = classification
    evidence["contention_contract"] = contract["local_contract"]
    evidence["cleanup_contract"] = cleanup_contract["cleanup_contract"]
    # Certification needs independent review of provider-side evidence via
    # tc_p008_hosted_evidence_gate.assess_hosted_probe(hosted_run_attested=True).
    evidence["hosted_certification"] = HOSTED_RESULT_PENDING
    return evidence


def independently_audit_cleanup(connect: Callable[[], Any], run_id: str, key: str) -> int:
    """Read exact probe scope via a new connection; reject any residue."""
    if not run_id or not key:
        raise RuntimeError("cleanup audit identifiers missing")
    with _closing_connection(connect) as observer:
        record = observer.execute(
            "SELECT count(*) FROM tc_p008_isolated.unique_write_probe "
            "WHERE probe_run=%s AND probe_key=%s",
            (run_id, key),
        ).fetchone()
    if record is None or len(record) != 1 or type(record[0]) is not int or record[0] != 0:
        raise RuntimeError("independent cleanup audit failed closed")
    return record[0]


def independently_verify_backends_terminated(
    connect: Callable[[], Any], pids: tuple[int, int]
) -> bool:
    """Fail closed unless an independent session confirms both backends gone."""
    if (
        len(pids) != 2
        or any(type(pid) is not int or pid <= 0 for pid in pids)
        or pids[0] == pids[1]
    ):
        raise RuntimeError("invalid PostgreSQL backend identities")
    with _closing_connection(connect) as observer:
        for attempt in range(BACKEND_EXIT_POLL_ATTEMPTS):
            # Backend status is cached per transaction; without discarding the
            # snapshot every re-read inside one transaction is stale.
            observer.execute("SELECT pg_catalog.pg_stat_clear_snapshot()", ())
            row = observer.execute(
                "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE pid = ANY(%s)",
                (list(pids),),
            ).fetchone()
            if row is None or len(row) != 1 or type(row[0]) is not int:
                raise RuntimeError("backend termination evidence malformed")
            if row[0] == 0:
                return True
            if attempt + 1 < BACKEND_EXIT_POLL_ATTEMPTS:
                time.sleep(BACKEND_EXIT_POLL_INTERVAL_S)
    return False
