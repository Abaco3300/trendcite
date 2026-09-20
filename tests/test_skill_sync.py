from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The Claude Code project skill (native discovery in a cloned repository) and the
# standard Agent Skills copy (`gh skill install`) must stay byte-for-byte identical.
PROJECT_SKILL = REPO_ROOT / ".claude" / "skills" / "trendcite" / "SKILL.md"
STANDARD_SKILL = REPO_ROOT / "skills" / "trendcite" / "SKILL.md"


def test_both_skill_copies_exist() -> None:
    for path in (PROJECT_SKILL, STANDARD_SKILL):
        assert path.is_file(), f"missing skill file: {path.relative_to(REPO_ROOT).as_posix()}"


def test_skill_copies_are_byte_identical() -> None:
    project = PROJECT_SKILL.read_bytes()
    standard = STANDARD_SKILL.read_bytes()
    assert project == standard, (
        f"{PROJECT_SKILL.relative_to(REPO_ROOT).as_posix()} and "
        f"{STANDARD_SKILL.relative_to(REPO_ROOT).as_posix()} have diverged "
        f"({len(project)} vs {len(standard)} bytes). "
        "Edit one and copy it over the other so both distribution paths ship the same skill."
    )
