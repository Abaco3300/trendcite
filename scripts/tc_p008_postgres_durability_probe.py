"""Opt-in local Docker PostgreSQL durability probe. No network ports or production access.

Uses a disposable postgres:17 container, no external volumes and synthetic identities.
"""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
import uuid


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=35)


def main() -> None:
    name = "tc-p008-durable-" + uuid.uuid4().hex[:10]

    def sql(query: str) -> str:
        process = run(
            "docker",
            "exec",
            name,
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            query,
        )
        return process.stdout.strip()

    try:
        run(
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--read-only=false",
            "-e",
            "POSTGRES_PASSWORD=synthetic-local-only-no-ports",
            "postgres:17",
        )
        import time

        for _ in range(30):
            if (
                run("docker", "exec", name, "pg_isready", "-U", "postgres", check=False).returncode
                == 0
            ):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("local postgres not ready")

        sql(
            "CREATE TABLE synthetic_jobs "
            "(tenant text NOT NULL, job text NOT NULL, effects int NOT NULL DEFAULT 1, "
            "PRIMARY KEY (tenant, job));"
        )
        statement = (
            "INSERT INTO synthetic_jobs(tenant,job) VALUES ('tenant_a','job_1') "
            "ON CONFLICT (tenant,job) DO NOTHING RETURNING job;"
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: sql(statement), range(24)))
        assert sum("job_1" in v for v in outcomes) == 1, outcomes
        assert sql("SELECT count(*) FROM synthetic_jobs;") == "1"
        assert sql("SELECT effects FROM synthetic_jobs WHERE tenant='tenant_a';") == "1"

        # Lost ACK after commit: duplicate must not repeat an effect.
        assert "job_1" not in sql(statement)
        assert sql("SELECT count(*) FROM synthetic_jobs;") == "1"
        sql(
            "INSERT INTO synthetic_jobs(tenant,job) VALUES ('tenant_b','job_1') "
            "ON CONFLICT DO NOTHING;"
        )
        assert sql("SELECT count(*) FROM synthetic_jobs;") == "2"
        result = {
            "schema": "trendcite.tc_p008.postgres_probe.v1",
            "scope": "LOCAL_POSTGRES_SYNTHETIC_ONLY",
            "concurrent_attempts": len(outcomes),
            "single_tenant_a_effect": True,
            "duplicate_ack_loss_safe": True,
            "tenant_b_independent": True,
            "cloudflare_consumer_e2e": "NOT_VERIFIED",
            "production_integration_ready": False,
        }
        print(json.dumps(result, sort_keys=True))
    finally:
        run("docker", "rm", "-f", name, check=False)


if __name__ == "__main__":
    main()
