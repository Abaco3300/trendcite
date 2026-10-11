"""Opt-in local PostgresExecutionStore integration probe; never use real credentials.

Requires local Docker postgres:17 image and psycopg. Creates/cleans an ephemeral DB
container with a port exposed ONLY on 127.0.0.1. Not a Cloudflare Queue E2E test.
"""

from __future__ import annotations

import asyncio
import json
import re
import selectors
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from trendcite.cloud.db.postgres import PostgresRuntimeStore  # noqa: E402
from trendcite.cloud.db.postgres_execution import PostgresExecutionStore  # noqa: E402


def command(*args: str, check: bool = True) -> str:
    p = subprocess.run(args, capture_output=True, text=True, check=check, timeout=45)
    return p.stdout.strip()


class AdapterConnection:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def transaction(self) -> Any:
        return self.inner.transaction()

    @staticmethod
    def params(sql: str, args: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
        ordering: list[int] = []

        def replace(match: re.Match[str]) -> str:
            ordering.append(int(match.group(1)) - 1)
            return "%s"

        converted = re.sub(r"\$(\d+)", replace, sql)
        return converted, tuple(args[i] for i in ordering)

    async def execute(self, query: str, *args: Any) -> str:
        query, values = self.params(query, args)
        async with self.inner.cursor() as cur:
            await cur.execute(query, values)
            return f"UPDATE {cur.rowcount}"

    async def fetchval(self, query: str, *args: Any) -> Any:
        row = await self.fetchrow(query, *args)
        return None if row is None else next(iter(row.values()))

    async def fetchrow(self, query: str, *args: Any) -> Any:
        query, values = self.params(query, args)
        async with self.inner.cursor() as cur:
            await cur.execute(query, values)
            return await cur.fetchone()

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        query, values = self.params(query, args)
        async with self.inner.cursor() as cur:
            await cur.execute(query, values)
            return list(await cur.fetchall())

    async def close(self) -> None:
        await self.inner.close()


async def exercise(port: int) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row

    # An independent connection for each invocation (the real application's contract).
    async def connector() -> AdapterConnection:
        db = await psycopg.AsyncConnection.connect(
            host="127.0.0.1",
            port=port,
            user="postgres",
            password="synthetic-local-only-no-production",  # noqa: S106
            dbname="postgres",
            row_factory=dict_row,
            connect_timeout=5,
        )
        return AdapterConnection(db)

    store = PostgresExecutionStore(connector, runtime_role="trendcite_runtime")
    now = datetime(2026, 10, 10, tzinfo=UTC)
    queue_store = PostgresRuntimeStore(connector, runtime_role="trendcite_runtime")

    async def create(tenant: str) -> Any:
        return await store.get_or_create_run(
            workspace_id=tenant,
            radar_id="radar-1" if tenant == "tenant-a" else "radar-2",
            evaluation_cutoff=now,
            started_at=now,
        )

    # Independent DB connections, real advisory serialization from unique index.
    attempts = await asyncio.gather(*(create("tenant-a") for _ in range(24)))
    assert len({run.run_id for run in attempts}) == 1
    replay = await create("tenant-a")  # downstream ACK might have been lost
    assert replay.run_id == attempts[0].run_id
    other = await create("tenant-b")
    assert other.workspace_id == "tenant-b"
    assert other.run_id != replay.run_id
    assert (await store.get_run("tenant-b", replay.run_id)) is None

    conn = await connector()
    try:
        a = await conn.fetchval(
            "SELECT count(*) FROM trendcite.cloud_radar_run WHERE workspace_id=$1", "tenant-a"
        )
        b = await conn.fetchval(
            "SELECT count(*) FROM trendcite.cloud_radar_run WHERE workspace_id=$1", "tenant-b"
        )
        assert (a, b) == (1, 1)
    finally:
        await conn.close()

    # Force a transaction rollback after writing a synthetic row.
    try:
        async with store._transaction() as transaction:
            await transaction.execute(
                "INSERT INTO trendcite.cloud_workspace VALUES ($1,$2,$3,$4)",
                "rolled-back",
                "rolled-back",
                "Synthetic",
                now.isoformat(),
            )
            raise RuntimeError("synthetic crash before commit")
    except RuntimeError as exc:
        assert str(exc) == "synthetic crash before commit"
    check = await connector()
    try:
        assert (
            await check.fetchval(
                "SELECT count(*) FROM trendcite.cloud_workspace WHERE workspace_id=$1",
                "rolled-back",
            )
            == 0
        )
    finally:
        await check.close()

    # The real Queue ledger uses the same database-level idempotency contract.
    async def claim(i: int) -> bool:
        return await queue_store.record_queue_once(
            delivery_id=f"delivery-{i}",
            workspace_id="tenant-a",
            logical_id="logical-one",
            kind="synthetic",
            first_seen_at=now,
        )

    claimed = await asyncio.gather(*(claim(i) for i in range(24)))
    assert sum(claimed) == 1, claimed
    assert await claim(0) is False  # same delivery ID replayed
    assert (
        await queue_store.record_queue_once(
            delivery_id="tenant-b-delivery",
            workspace_id="tenant-b",
            logical_id="logical-one",
            kind="synthetic",
            first_seen_at=now,
        )
        is True
    )
    # Reusing the actual winning delivery ID for a DIFFERENT logical job
    # must not be misclassified as harmless replay: fail closed instead.
    verifier = await connector()
    try:
        committed_delivery_id = await verifier.fetchval(
            "SELECT delivery_id FROM trendcite.cloud_queue_delivery "
            "WHERE workspace_id=$1 AND logical_id=$2",
            "tenant-a",
            "logical-one",
        )
    finally:
        await verifier.close()
    assert committed_delivery_id is not None
    try:
        await queue_store.record_queue_once(
            delivery_id=str(committed_delivery_id),
            workspace_id="tenant-b",
            logical_id="different-logical-job",
            kind="synthetic",
            first_seen_at=now,
        )
    except RuntimeError as exc:
        assert str(exc) == "queue delivery identity collision"
    else:
        raise AssertionError("unrelated delivery-ID collision was suppressed")

    # Actual scheduled-tick claim/lease code backed by the canonical SQL schema.
    start = now
    expires = now + timedelta(seconds=30)
    attempts = await asyncio.gather(
        *(
            queue_store.claim_tick(
                workspace_id="tenant-a",
                tick_id="tick-a",
                owner=f"worker-{i}",
                now=start,
                lease_expires_at=expires,
            )
            for i in range(12)
        )
    )
    assert sum(attempts) == 1, attempts
    owner = f"worker-{attempts.index(True)}"
    assert (
        await queue_store.claim_tick(
            workspace_id="tenant-b",
            tick_id="tick-a",
            owner="wrong-tenant",
            now=start,
            lease_expires_at=expires,
        )
        is False
    )
    assert (
        await queue_store.claim_tick(
            workspace_id="tenant-a",
            tick_id="tick-a",
            owner="premature-reclaimer",
            now=start + timedelta(seconds=10),
            lease_expires_at=expires + timedelta(seconds=10),
        )
        is False
    )
    assert (
        await queue_store.claim_tick(
            workspace_id="tenant-a",
            tick_id="tick-a",
            owner="recovery-worker",
            now=start + timedelta(seconds=31),
            lease_expires_at=start + timedelta(seconds=61),
        )
        is True
    )
    tick = await queue_store.get_tick("tenant-a", "tick-a")
    assert tick is not None and tick.attempt == 2
    settled = replace(
        tick,
        status="succeeded",
        updated_at=start + timedelta(seconds=32),
        finished_at=start + timedelta(seconds=32),
    )
    assert await queue_store.settle_tick(settled, expected_owner=owner) is False
    assert await queue_store.settle_tick(settled, expected_owner="recovery-worker") is True
    assert (await queue_store.get_tick("tenant-a", "tick-a")).status == "succeeded"
    assert (
        await queue_store.claim_tick(
            workspace_id="tenant-a",
            tick_id="tick-a",
            owner="third-worker",
            now=start + timedelta(seconds=62),
            lease_expires_at=start + timedelta(seconds=92),
        )
        is False
    )

    return {
        "scope": "LOCAL_REAL_POSTGRES_EXECUTION_STORE",
        "schema": "trendcite.tc_p008.real_store.v1",
        "concurrent_attempts": 24,
        "one_run_per_tenant_key": True,
        "replay_idempotent": True,
        "tenant_isolation": True,
        "queue_ledger_concurrent_attempts": 24,
        "queue_ledger_exactly_one_claim": True,
        "queue_replay_safe": True,
        "schedule_competing_claims": 12,
        "schedule_only_one_owner": True,
        "expired_lease_reclaimed": True,
        "stale_owner_settlement_rejected": True,
        "claim_exhaustion_enforced": True,
        "cloudflare_queue_e2e": "NOT_VERIFIED",
        "production_ready": False,
    }


def main() -> None:
    import psycopg

    name = "tc-p008-adapter-" + uuid.uuid4().hex[:10]
    created = False
    try:
        command(
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1::5432",
            "-e",
            "POSTGRES_PASSWORD=synthetic-local-only-no-production",
            "postgres:17",
        )
        created = True
        mapping = command("docker", "port", name, "5432/tcp")
        port = int(mapping.rsplit(":", 1)[-1])
        for _ in range(35):
            ok = (
                subprocess.run(
                    ["docker", "exec", name, "pg_isready", "-U", "postgres"],
                    capture_output=True,
                    check=False,
                    timeout=5,
                ).returncode
                == 0
            )
            if ok:
                break
            time.sleep(0.4)
        else:
            raise RuntimeError("disposable PostgreSQL did not become ready")

        sql_path = (
            Path(__file__).resolve().parents[1]
            / "src/trendcite/cloud/db/sql/0001_cloud_foundation.sql"
        )
        for attempt in range(24):
            try:
                with psycopg.connect(
                    host="127.0.0.1",
                    port=port,
                    user="postgres",
                    password="synthetic-local-only-no-production",  # noqa: S106
                    dbname="postgres",
                    connect_timeout=2,
                ):
                    break
            except psycopg.OperationalError:
                if attempt == 23:
                    raise
                time.sleep(0.25)

        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user="postgres",
            password="synthetic-local-only-no-production",  # noqa: S106
            dbname="postgres",
            autocommit=True,
        ) as connection:
            connection.execute("CREATE ROLE trendcite_runtime NOLOGIN NOINHERIT")
            connection.execute("CREATE SCHEMA trendcite")
            connection.execute("SET search_path TO trendcite, pg_catalog")
            connection.execute(sql_path.read_text(encoding="utf-8"))
            schedule_path = sql_path.with_name("0004_scheduled_radar_orchestration.sql")
            connection.execute(schedule_path.read_text(encoding="utf-8"))
            ledger_path = sql_path.with_name("0005_queue_delivery_idempotency.sql")
            connection.execute(ledger_path.read_text(encoding="utf-8"))
            connection.execute("GRANT USAGE ON SCHEMA trendcite TO trendcite_runtime")
            connection.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA trendcite "
                "TO trendcite_runtime"
            )
            for tenant, radar, version in (
                ("tenant-a", "radar-1", "ver-1"),
                ("tenant-b", "radar-2", "ver-2"),
            ):
                connection.execute(
                    "INSERT INTO trendcite.cloud_workspace VALUES (%s,%s,%s,%s)",
                    (tenant, tenant, tenant, "2026-10-10T00:00:00+00:00"),
                )
                connection.execute(
                    "INSERT INTO trendcite.cloud_radar VALUES (%s,%s,%s,%s)",
                    (radar, tenant, radar, "2026-10-10T00:00:00+00:00"),
                )
                connection.execute(
                    "INSERT INTO trendcite.cloud_radar_version VALUES (%s,%s,%s,1,%s,%s,%s,3,%s)",
                    (
                        version,
                        radar,
                        tenant,
                        "[]",
                        "[]",
                        "synthetic",
                        "2026-10-10T00:00:00+00:00",
                    ),
                )
            connection.execute(
                "INSERT INTO trendcite.cloud_radar_schedule "
                "(schedule_id,workspace_id,radar_id,enabled,cadence,"
                "utc_offset_minutes,anchor_at,max_catch_up,lease_seconds,"
                "max_attempts,cadence_version,created_at,updated_at) "
                "VALUES (%s,%s,%s,1,%s,0,%s,3,30,2,%s,%s,%s)",
                (
                    "sched-a",
                    "tenant-a",
                    "radar-1",
                    "hourly",
                    "2026-10-10T00:00:00+00:00",
                    "v1",
                    "2026-10-10T00:00:00+00:00",
                    "2026-10-10T00:00:00+00:00",
                ),
            )
            connection.execute(
                "INSERT INTO trendcite.cloud_schedule_tick "
                "(tick_id,schedule_id,workspace_id,radar_id,evaluation_cutoff,"
                "idempotency_key,status,max_attempts,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,'pending',2,%s,%s)",
                (
                    "tick-a",
                    "sched-a",
                    "tenant-a",
                    "radar-1",
                    "2026-10-10T00:00:00+00:00",
                    "tenant-a:tick-a",
                    "2026-10-10T00:00:00+00:00",
                    "2026-10-10T00:00:00+00:00",
                ),
            )
        print(
            json.dumps(
                asyncio.run(
                    exercise(port),
                    loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
                ),
                sort_keys=True,
            )
        )
    finally:
        if created:
            command("docker", "rm", "-f", name, check=False)


if __name__ == "__main__":
    main()
