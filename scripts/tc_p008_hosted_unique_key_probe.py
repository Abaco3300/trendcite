"""Operator-run, single-shot TC-P008 Test A on the dedicated PostgreSQL sandbox.

Run ONLY on the operator machine, after the operator has set a temporary
password for ``tc_p008_probe_login`` through psql ``\\password`` (client-side
SCRAM hashing; plaintext never reaches SQL text or server logs) and a short
``VALID UNTIL``. See
``.irmya/capability-packs/TC-P008/HOSTED-TEST-A-OPERATOR-PROCEDURE-2026-10-21.md``.

Secret handling:
- the password is read with ``getpass`` (no echo); never from argv or env;
- it is never printed, logged, serialized or written to disk;
- at the end the role revokes its own password (``PASSWORD NULL``).

The output is secret-free evidence for independent review. It never claims
hosted certification.
"""

from __future__ import annotations

import argparse
import getpass
import importlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trendcite.cloud.tc_p008_connection_factory import prepare_sandbox_connection
from trendcite.cloud.tc_p008_hosted_runner import execute_probe
from trendcite.cloud.tc_p008_sandbox_target import (
    EXPECTED_ROLE,
    SANDBOX_TARGETS,
    sandbox_dsn,
)

CONFIRMATION = "RUN-TC-P008-TEST-A-ONCE"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def load_driver() -> Callable[..., Any]:
    """psycopg 3 is optional for the package; require it only here."""
    try:
        psycopg = importlib.import_module("psycopg")
    except ImportError as exc:
        raise RuntimeError("psycopg 3 required: pip install 'psycopg[binary]>=3.2'") from exc
    connect = getattr(psycopg, "connect", None)
    if not callable(connect):
        raise RuntimeError("psycopg.connect unavailable")
    return connect  # type: ignore[no-any-return]


def verify_session_identity(connect: Callable[[], Any]) -> dict[str, object]:
    """One read-only session: restricted identity, TLS in use, expected schema."""
    connection = connect()
    try:
        row = connection.execute(
            "SELECT current_user, session_user, "
            "(SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls "
            " FROM pg_catalog.pg_roles WHERE rolname = current_user), "
            "s.ssl, s.version, current_setting('server_version'), "
            "has_table_privilege('tc_p008_isolated.unique_write_probe', 'INSERT'), "
            "has_table_privilege('tc_p008_isolated.unique_write_probe', 'UPDATE') "
            "FROM pg_catalog.pg_stat_ssl s WHERE s.pid = pg_backend_pid()"
        ).fetchone()
        connection.rollback()
    finally:
        connection.close()
    if row is None or len(row) != 8:
        raise RuntimeError("sandbox identity evidence malformed")
    current, session, elevated, ssl, tls_version, server, can_insert, can_update = row
    if current != EXPECTED_ROLE or session != EXPECTED_ROLE:
        raise RuntimeError("restricted sandbox identity not established")
    if elevated is not False:
        raise RuntimeError("sandbox identity holds elevated attributes")
    if ssl is not True:
        raise RuntimeError("TLS not in use for sandbox session")
    if can_insert is not True or can_update is not False:
        raise RuntimeError("sandbox privileges differ from least-privilege contract")
    return {
        "current_user": current,
        "session_user": session,
        "elevated_attributes": elevated,
        "tls": ssl,
        "tls_version": tls_version,
        "server_version": server,
    }


def revoke_own_password(connect: Callable[[], Any]) -> str:
    """Remove the temporary password; contains no secret in SQL text."""
    connection = connect()
    try:
        connection.execute("ALTER ROLE CURRENT_USER PASSWORD NULL")
        connection.commit()
    finally:
        connection.close()
    return "PASSWORD_NULL_COMMITTED"


def run(transport: str, sslrootcert: str, password: str) -> dict[str, object]:
    connect = prepare_sandbox_connection(
        sandbox_dsn(transport),
        password,
        driver_connect=load_driver(),
        sslrootcert=sslrootcert,
    )
    report: dict[str, object] = {
        "test": "TC-P008 Test A - hosted PostgreSQL unique-key contention",
        "project": "btjgozzguhuzfdueensf",
        "transport": transport,
        "started_at": _now(),
        "hosted_certification": "NOT_VERIFIED_PENDING_INDEPENDENT_REVIEW",
    }
    try:
        report["identity"] = verify_session_identity(connect)
        report["probe"] = execute_probe(connect, approved=True)
        report["probe_status"] = "COMPLETED_EVIDENCE_PENDING_REVIEW"
    except Exception:
        # Driver exception messages are untrusted and can contain passwords or DSNs.
        report["probe_status"] = "FAILED_CLOSED"
        report["probe_error"] = "PROBE_EXCEPTION_REDACTED"
    finally:
        try:
            report["credential_revocation"] = revoke_own_password(connect)
        except Exception as exc:
            report["credential_revocation"] = (
                f"REVOCATION_FAILED_OPERATOR_MUST_REVOKE ({type(exc).__name__})"
            )
        report["finished_at"] = _now()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transport", choices=sorted(SANDBOX_TARGETS), required=True)
    parser.add_argument("--sslrootcert", required=True, help="Supabase root CA (PEM) path")
    parser.add_argument("--evidence-out", type=Path, help="write secret-free JSON here")
    parser.add_argument("--confirm", required=True, help=f"must equal {CONFIRMATION}")
    args = parser.parse_args(argv)
    if args.confirm != CONFIRMATION:
        print("CONFIRMATION_MISMATCH: nothing executed", file=sys.stderr)
        return 2
    password = getpass.getpass(f"Temporary password for {EXPECTED_ROLE} (not echoed): ")
    try:
        try:
            report = run(args.transport, args.sslrootcert, password)
        except Exception:
            # Preparation errors occur before run()'s internal redaction gate.
            # Never propagate arbitrary driver text or a traceback to the terminal.
            print("PROBE_PREPARATION_FAILED_REDACTED: no probe evidence", file=sys.stderr)
            return 1
    finally:
        password = ""  # drop the only reference
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    print(text)
    if args.evidence_out is not None:
        args.evidence_out.write_text(text + "\n", encoding="utf-8")
    ok = report.get("probe_status") == "COMPLETED_EVIDENCE_PENDING_REVIEW"
    revoked = report.get("credential_revocation") == "PASSWORD_NULL_COMMITTED"
    return 0 if ok and revoked else 1


if __name__ == "__main__":
    raise SystemExit(main())
