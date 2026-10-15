"""Verify actual overlapping PostgreSQL backend sessions in isolated Docker.

No ports, external database credentials or production resources.
"""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
import time
import uuid
from datetime import datetime


def invoke(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=30)


def main() -> None:
    container = "tc-p008-overlap-" + uuid.uuid4().hex[:10]
    try:
        invoke(
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "--network",
            "none",
            "-e",
            "POSTGRES_PASSWORD=synthetic-only",
            "postgres:17",
        )
        for _ in range(30):
            if (
                invoke(
                    "docker", "exec", container, "pg_isready", "-U", "postgres", check=False
                ).returncode
                == 0
            ):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("isolated postgres unavailable")
        statement = "SELECT pg_backend_pid(),clock_timestamp(),pg_sleep(2),clock_timestamp();"

        def timed_query(_: int) -> dict[str, str]:
            for attempt in range(5):
                response = invoke(
                    "docker",
                    "exec",
                    container,
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
                    statement,
                    check=False,
                )
                if response.returncode == 0:
                    pid, start, _, end = response.stdout.strip().split("|")
                    return {"pid": pid, "start": start, "end": end}
                if attempt == 4:
                    raise RuntimeError("postgres query failed: " + response.stderr[-300:])
                time.sleep(0.25)
            raise AssertionError("unreachable")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(timed_query, (1, 2)))

        def parse(value: str) -> datetime:
            return datetime.fromisoformat(value.strip().replace(" ", "T"))

        a, b = records
        overlap = max(parse(a["start"]), parse(b["start"])) < min(parse(a["end"]), parse(b["end"]))
        assert a["pid"] != b["pid"], records
        assert overlap, records
        print(
            json.dumps(
                {
                    "scope": "LOCAL_POSTGRES_SYNTHETIC_ONLY",
                    "independent_backends": True,
                    "overlap": True,
                    "records": records,
                    "hosted_supabase_overlap": "NOT_VERIFIED",
                },
                sort_keys=True,
            )
        )
    finally:
        invoke("docker", "rm", "-f", container, check=False)


if __name__ == "__main__":
    main()
