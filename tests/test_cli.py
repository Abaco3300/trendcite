from __future__ import annotations

import json
from pathlib import Path

import pytest

from trendcite.cli import main
from trendcite.config import ConfigError, load_config


@pytest.mark.usefixtures("no_network")
def test_cli_demo_markdown(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# TrendCite: Content Opportunity Briefs")
    assert "## 1. " in out


@pytest.mark.usefixtures("no_network")
def test_cli_demo_json_to_file(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    assert main(["demo", "--format", "json", "--out", str(target), "--top", "3"]) == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["mode"] == "demo"
    assert len(data["briefs"]) == 3
    assert "draft_outline_not_evidence" in data["briefs"][0]


@pytest.mark.usefixtures("no_network")
def test_cli_demo_llm_flag_without_provider_is_safe(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRENDCITE_LLM_PROVIDER", raising=False)
    assert main(["demo", "--llm"]) == 0
    assert "deterministic output only" in capsys.readouterr().out


def test_cli_sources(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sources"]) == 0
    out = capsys.readouterr().out
    for name in ("hackernews", "github", "rss", "reddit", "x"):
        assert name in out


def test_cli_bad_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = tmp_path / "bad.toml"
    cfg.write_text("unknown_key = 1\n", encoding="utf-8")
    assert main(["live", "--config", str(cfg)]) == 2
    assert "unknown config keys" in capsys.readouterr().err


def test_load_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "trendcite.toml"
    cfg_file.write_text(
        'niche = ["ai agents"]\nfeeds = ["https://example.com/feed"]\nhn_limit = 10\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.niche == ["ai agents"]
    assert cfg.hn_limit == 10
    bad = tmp_path / "bad.toml"
    bad.write_text('hn_limit = "ten"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad)


def test_example_config_is_valid() -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "trendcite.toml"
    cfg = load_config(example)
    assert cfg.feeds and cfg.niche
