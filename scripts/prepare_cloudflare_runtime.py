#!/usr/bin/env python3
"""Build and verify the exact local TrendCite wheel used by Cloudflare Python Workers."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "deploy" / "cloudflare"
WHEELHOUSE = WORKER / "wheelhouse"
WORKER_PYPROJECT = WORKER / "pyproject.toml"
GENERATED_RUNTIME_DIRS = (
    WORKER / "python_modules",
    WORKER / ".venv",
    WORKER / ".venv-workers",
)
GENERATED_RUNTIME_FILES = (
    WORKER / "pylock.toml",
    WORKER / "uv.lock",
)


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
    "trendcite/cloud/auth.py",
    "trendcite/cloud/async_delivery.py",
    "trendcite/cloud/async_delivery_service.py",
    "trendcite/cloud/async_execution.py",
    "trendcite/cloud/async_http.py",
    "trendcite/cloud/async_scheduler.py",
    "trendcite/cloud/async_sources.py",
    "trendcite/cloud/db/postgres.py",
    "trendcite/cloud/db/postgres_access.py",
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


def sync_worker_source() -> None:
    text = WORKER_PYPROJECT.read_text(encoding="utf-8")
    replacement = f'trendcite = {{ path = "wheelhouse/{EXPECTED_WHEEL.name}" }}'
    pattern = r'trendcite = \{ path = "wheelhouse/trendcite-[^"]+\.whl" \}'
    updated, count = re.subn(pattern, replacement, text)
    if count != 1:
        raise PackagingError(
            "worker pyproject must contain exactly one local TrendCite wheel source"
        )
    WORKER_PYPROJECT.write_text(updated, encoding="utf-8")


def clear_generated_runtime() -> None:
    for path in GENERATED_RUNTIME_DIRS:
        shutil.rmtree(path, ignore_errors=True)
    for path in GENERATED_RUNTIME_FILES:
        path.unlink(missing_ok=True)


def uv_executable() -> Path:
    resolved = shutil.which("uv")
    if resolved:
        return Path(resolved)
    sibling = Path(sys.executable).with_name("uv.exe" if os.name == "nt" else "uv")
    if sibling.exists():
        return sibling
    raise PackagingError(
        "uv is required for Cloudflare Python dependency sync; install uv before deploy"
    )


def sync_vendor() -> None:
    uv = uv_executable()
    env = os.environ.copy()
    env["PATH"] = str(uv.parent) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [str(uv), "run", "pywrangler", "sync"],
        cwd=WORKER,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise PackagingError(f"pywrangler sync failed ({result.returncode})")


def verify_vendor(path: Path) -> None:
    vendor = WORKER / "python_modules"
    if not vendor.exists():
        raise PackagingError("pywrangler sync did not create python_modules")

    with zipfile.ZipFile(path) as archive:
        for member in REQUIRED_MEMBERS | {"trendcite/__init__.py"}:
            expected = archive.read(member)
            actual_path = vendor / Path(member)
            if not actual_path.exists():
                raise PackagingError(f"vendored runtime is missing {member}")
            if actual_path.read_bytes() != expected:
                raise PackagingError(f"vendored runtime differs from wheel: {member}")

    lock = WORKER / "pylock.toml"
    lock_text = lock.read_text(encoding="utf-8")
    version = project_version()
    if f'version = "{version}"' not in lock_text:
        raise PackagingError("pylock does not contain current TrendCite version")
    if f"wheelhouse/trendcite-{version}-py3-none-any.whl" not in lock_text:
        raise PackagingError("pylock does not point to current TrendCite wheel")


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
    sync_worker_source()
    clear_generated_runtime()
    sync_vendor()
    verify_vendor(EXPECTED_WHEEL)
    print(f"wheel={EXPECTED_WHEEL}")
    print(f"sha256={sha256(EXPECTED_WHEEL)}")
    print(f"worker_source=wheelhouse/{EXPECTED_WHEEL.name}")
    print("vendor_sync=PASS")
    print(f"required_cloud_modules={len(REQUIRED_MEMBERS)}")
    print("PACKAGING SOURCE PROOF = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
