"""Release-package preflight for TrendCite.

Builds the wheel and sdist, checks PyPI metadata with Twine, inspects the
wheel payload, and installs the wheel in an isolated environment. This script
never uploads or publishes anything.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "trendcite"


def run(args: list[str], *, cwd: Path = ROOT) -> None:
    print("$", " ".join(args))
    subprocess.run(args, cwd=cwd, check=True)


def read_project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    return str(data["project"]["version"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def validate_wheel(wheel: Path, expected_version: str) -> None:
    required_payload = {
        "trendcite/py.typed",
        "trendcite/cloud/db/sql/0001_cloud_foundation.sql",
        "trendcite/fixtures/demo_meta.json",
    }
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = sorted(required_payload - names)
        if missing:
            raise SystemExit(f"wheel missing required package data: {missing}")
        metadata_name = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            raise SystemExit("wheel METADATA not found")
        metadata = archive.read(metadata_name).decode("utf-8")

    required_metadata = (
        "Name: trendcite",
        f"Version: {expected_version}",
        "Requires-Python: >=3.11",
        "License-Expression: MIT",
    )
    for field in required_metadata:
        if field not in metadata:
            raise SystemExit(f"wheel metadata missing: {field}")


def validate_sdist(sdist: Path) -> None:
    required_suffixes = {
        "/pyproject.toml",
        "/README.md",
        "/LICENSE",
        "/src/trendcite/cloud/db/sql/0001_cloud_foundation.sql",
        "/src/trendcite/fixtures/demo_meta.json",
    }
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
    missing = [
        suffix for suffix in sorted(required_suffixes) if not any(n.endswith(suffix) for n in names)
    ]
    if missing:
        raise SystemExit(f"sdist missing required files: {missing}")


def isolated_install_smoke(wheel: Path, expected_version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="trendcite-package-install-") as tmp:
        venv = Path(tmp) / "venv"
        run([sys.executable, "-m", "venv", str(venv)])
        py = venv_python(venv)
        run([str(py), "-m", "pip", "install", "--quiet", "--no-deps", str(wheel)])
        code = (
            "import trendcite; "
            f"assert trendcite.__version__ == {expected_version!r}; "
            "from trendcite.pipeline import run_demo; "
            "report = run_demo(); "
            "assert 3 <= len(report.briefs) <= 5; "
            "print('isolated wheel OK:', trendcite.__version__, len(report.briefs), 'briefs')"
        )
        run([str(py), "-c", code])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and validate PyPI distributions without publishing."
    )
    parser.add_argument(
        "--expected-version",
        help="Fail unless pyproject.toml contains exactly this version.",
    )
    parser.add_argument(
        "--dist-dir",
        default="dist",
        help="Output directory relative to the repository root (default: dist).",
    )
    args = parser.parse_args()

    version = read_project_version()
    if args.expected_version is not None and version != args.expected_version:
        raise SystemExit(
            f"package version {version!r} does not match expected {args.expected_version!r}"
        )

    dist_dir = Path(args.dist_dir)
    if not dist_dir.is_absolute():
        dist_dir = ROOT / dist_dir
    dist_dir = dist_dir.resolve()
    if dist_dir == ROOT or ROOT not in dist_dir.parents:
        raise SystemExit("dist directory must be inside the repository")
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)

    run([sys.executable, "-m", "build", "--outdir", str(dist_dir), str(ROOT)])
    artifacts = sorted(path for path in dist_dir.iterdir() if path.is_file())
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(artifacts) != 2:
        raise SystemExit(
            f"expected exactly one wheel and one sdist; found {[p.name for p in artifacts]}"
        )

    run([sys.executable, "-m", "twine", "check", *(str(path) for path in artifacts)])
    validate_wheel(wheels[0], version)
    validate_sdist(sdists[0])
    isolated_install_smoke(wheels[0], version)

    print("\nPACKAGE PREFLIGHT PASSED")
    for artifact in artifacts:
        print(f"{artifact.name}  sha256={sha256(artifact)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
