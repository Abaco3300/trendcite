"""Regression contract for TC-P008 authorized DARK state validator."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_tc_p008_state_local.py"
CANONICAL = ROOT / ".irmya" / "infrastructure" / "DEPLOYMENT_STATE.yaml"


def _run_validator(tmp_path: Path, state: dict) -> subprocess.CompletedProcess[str]:
    target = tmp_path / ".irmya" / "infrastructure"
    target.mkdir(parents=True)
    (target / "DEPLOYMENT_STATE.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_authorized_bound_dark_passes(tmp_path: Path) -> None:
    state = yaml.safe_load(CANONICAL.read_text(encoding="utf-8"))
    result = _run_validator(tmp_path, state)
    assert result.returncode == 0, result.stderr
    assert "TC_P008_YAML_VALIDATION_PASS" in result.stdout


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hyperdrive_bound", False),
        ("hyperdrive_status", "ACTIVE"),
        ("active", True),
        ("activation_authorized", True),
        ("queues_bound", True),
        ("public_routes", True),
        ("workers_dev", True),
        ("foundation_status", "ACTIVE"),
    ],
)
def test_unsafe_or_stale_production_state_fails_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    state = yaml.safe_load(CANONICAL.read_text(encoding="utf-8"))
    state["production"][field] = value
    result = _run_validator(tmp_path, state)
    assert result.returncode != 0
    assert "TC_P008_YAML_VALIDATION_PASS" not in result.stdout
