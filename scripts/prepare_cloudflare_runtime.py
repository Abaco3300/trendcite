#!/usr/bin/env python3
"""Build and verify the exact local TrendCite wheel used by Cloudflare Python Workers."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "deploy" / "cloudflare"
WHEELHOUSE = WORKER / "wheelhouse"


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    version = str(data.get("project", {}).get("version", "")).strip()
    if not version:
        raise RuntimeError("pyproject.toml is missing project.version")
    return version


EXPECTED_WHEEL = WHEELHOUSE / f"trendcite-{project_version()}-py3-none-any.whl"

REQUIRED_MEMBERS = {
    "trendcite/cloud/async_application.py",
    "trendcite/cloud/async_delivery.py",
    "trendcite/cloud/async_delivery_service.py",
    "trendcite/cloud/async_execution.py",
    "trendcite/cloud/async_http.py",
    "trendcite/cloud/async_scheduler.py",
    "trendcite/cloud/async_sources.py",
    "trendcite/cloud/db/postgres.py",
    "trendcite/cloud/db/postgres_delivery.py",
    "trendcite/cloud/db/postgres_execution.py",
}


class PackagingError(RuntimeError):
    pass


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        raise PackagingError(f"command failed ({result.returncode}): {' '.join(cmd)}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_wheel(path: Path) -> set[str]:
    if not path.exists():
        raise PackagingError(f"expected wheel was not produced: {path}")
    with zipfile.ZipFile(path) as archive:
        members = set(archive.namelist())
    missing = REQUIRED_MEMBERS - members
    if missing:
        raise PackagingError(
            "local runtime wheel is missing required Cloud modules: " + ", ".join(sorted(missing))
        )
    return members


def main() -> int:
    shutil.rmtree(WHEELHOUSE, ignore_errors=True)
    WHEELHOUSE.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(WHEELHOUSE),
            str(ROOT),
        ]
    )

    wheels = sorted(WHEELHOUSE.glob("trendcite-*.whl"))
    if wheels != [EXPECTED_WHEEL]:
        raise PackagingError(
            f"expected exactly {EXPECTED_WHEEL.name}; produced: "
            + ", ".join(path.name for path in wheels)
        )

    verify_wheel(EXPECTED_WHEEL)
    print(f"wheel={EXPECTED_WHEEL}")
    print(f"sha256={sha256(EXPECTED_WHEEL)}")
    print(f"required_cloud_modules={len(REQUIRED_MEMBERS)}")
    print("PACKAGING SOURCE PROOF = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
