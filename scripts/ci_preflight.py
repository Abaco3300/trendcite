#!/usr/bin/env python3
"""Canonical local CI preflight for TrendCite. Remote CI runs this same script.

Run from anywhere:  python scripts/ci_preflight.py [--skip-build]

Steps (all must pass; a missing tool is a failure, not a skip):
  1. git diff --check (unstaged and staged whitespace/conflict-marker errors)
  2. ruff format --check
  3. ruff check
  4. mypy (strict, configured in pyproject.toml)
  5. pytest (offline, deterministic)
  6. offline demo smoke test (python -m trendcite demo --format json)
  7. build sdist + wheel, install the wheel into a throwaway venv, import-check it
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
# Keep every temporary artefact (build envs, throwaway venv, pip cache) inside the repo.
WORK = ROOT / ".preflight_tmp"


class StepFailed(RuntimeError):
    pass


def run(cmd: list[str], *, cwd: Path = ROOT, capture: bool = False) -> str:
    print(f"    $ {' '.join(cmd)}", flush=True)
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "TMP": str(WORK),
        "TEMP": str(WORK),
        "TMPDIR": str(WORK),
        "PIP_CACHE_DIR": str(WORK / "pip-cache"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    result = subprocess.run(
        cmd, cwd=cwd, env=env, text=True, encoding="utf-8", capture_output=capture, check=False
    )
    if result.returncode != 0:
        if capture:
            sys.stdout.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
        raise StepFailed(f"exit code {result.returncode}: {' '.join(cmd)}")
    return result.stdout if capture else ""


def require_module(name: str) -> None:
    probe = subprocess.run([PY, "-c", f"import {name}"], capture_output=True, check=False)
    if probe.returncode != 0:
        raise StepFailed(f"required tool '{name}' is not installed; run: pip install -e '.[dev]'")


def step_git_diff_check() -> None:
    if shutil.which("git") is None:
        raise StepFailed("git is not installed")
    inside = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if inside.returncode != 0:
        print("    (not a git work tree; skipping git diff --check)")
        return
    run(["git", "diff", "--check"])
    run(["git", "diff", "--cached", "--check"])


def step_format() -> None:
    require_module("ruff")
    run([PY, "-m", "ruff", "format", "--check", "."])


def step_lint() -> None:
    require_module("ruff")
    run([PY, "-m", "ruff", "check", "."])


def step_types() -> None:
    require_module("mypy")
    run([PY, "-m", "mypy"])


def step_tests() -> None:
    require_module("pytest")
    run([PY, "-m", "pytest", "-q"])


def step_demo() -> None:
    out = run([PY, "-m", "trendcite", "demo", "--format", "json"], capture=True)
    data = json.loads(out)
    briefs = data.get("briefs", [])
    if not 3 <= len(briefs) <= 5:
        raise StepFailed(f"demo produced {len(briefs)} briefs (expected 3-5)")
    if any(not b.get("evidence") for b in briefs):
        raise StepFailed("a demo brief has no evidence")
    print(f"    demo OK: {len(briefs)} briefs from {data.get('total_items')} items")


def step_build() -> None:
    require_module("build")
    with tempfile.TemporaryDirectory(prefix="build-", dir=WORK) as tmp:
        dist = Path(tmp) / "dist"
        run([PY, "-m", "build", "--outdir", str(dist), str(ROOT)], capture=True)
        wheels = sorted(dist.glob("trendcite-*.whl"))
        sdists = sorted(dist.glob("trendcite-*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise StepFailed(f"expected one wheel and one sdist, found {wheels + sdists}")
        venv = Path(tmp) / "venv"
        run([PY, "-m", "venv", str(venv)])
        vpy = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(vpy), "-m", "pip", "install", "--quiet", "--no-deps", str(wheels[0])])
        check = (
            "import trendcite, trendcite.cli; "
            "from trendcite.pipeline import run_demo; "
            "r = run_demo(); assert 3 <= len(r.briefs) <= 5, len(r.briefs); "
            "print('    wheel import OK:', trendcite.__version__, len(r.briefs), 'briefs')"
        )
        # Run outside the repo so the installed wheel (not ./src) is imported.
        run([str(vpy), "-c", check], cwd=Path(tmp))


STEPS = [
    ("git diff --check", step_git_diff_check),
    ("ruff format --check", step_format),
    ("ruff check", step_lint),
    ("mypy", step_types),
    ("pytest", step_tests),
    ("offline demo smoke test", step_demo),
    ("build + wheel import check", step_build),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-build", action="store_true", help="skip the slow build step")
    args = parser.parse_args()
    failures: list[str] = []
    started = time.monotonic()
    WORK.mkdir(exist_ok=True)
    for name, func in STEPS:
        if args.skip_build and func is step_build:
            print(f"[SKIP] {name} (--skip-build)")
            continue
        print(f"[RUN ] {name}", flush=True)
        t0 = time.monotonic()
        try:
            func()
        except (StepFailed, json.JSONDecodeError) as exc:
            print(f"[FAIL] {name}: {exc}", flush=True)
            failures.append(name)
            continue
        print(f"[PASS] {name} ({time.monotonic() - t0:.1f}s)", flush=True)
    total = time.monotonic() - started
    shutil.rmtree(WORK, ignore_errors=True)
    if failures:
        failed = ", ".join(failures)
        print(f"\nPREFLIGHT FAILED ({len(failures)} step(s): {failed}) in {total:.1f}s")
        return 1
    print(f"\nPREFLIGHT PASSED in {total:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
