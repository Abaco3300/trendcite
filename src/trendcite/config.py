"""Configuration: defaults plus an optional TOML file (``trendcite.toml``).

Configuration only names *what* to read (feeds, subreddits, queries, niche terms).
It never contains credentials; optional LLM keys are read from the environment.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_FEEDS = [
    "https://github.blog/feed/",
    "https://simonwillison.net/atom/everything/",
    "https://blog.pragmaticengineer.com/rss/",
]
DEFAULT_SUBREDDITS = ["startups", "SaaS", "programming"]
DEFAULT_GITHUB_QUERIES = ["ai agent", "developer tools"]
DEFAULT_NICHE = ["ai agents", "developer tools", "startups", "saas"]


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    niche: list[str] = field(default_factory=lambda: list(DEFAULT_NICHE))
    feeds: list[str] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    subreddits: list[str] = field(default_factory=lambda: list(DEFAULT_SUBREDDITS))
    github_queries: list[str] = field(default_factory=lambda: list(DEFAULT_GITHUB_QUERIES))
    hn_limit: int = 30
    sources: list[str] = field(default_factory=lambda: ["hackernews", "github", "rss", "reddit"])
    top: int = 5


def _str_list(value: Any, key: str, limit: int = 50) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"'{key}' must be a list of strings")
    return [v.strip() for v in value if v.strip()][:limit]


def load_config(path: str | Path | None) -> Config:
    cfg = Config()
    if path is None:
        return cfg
    p = Path(path)
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {p}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {p}: {exc}") from exc
    known = {f.name for f in fields(Config)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"unknown config keys: {', '.join(unknown)}")
    for key in ("niche", "feeds", "subreddits", "github_queries", "sources"):
        if key in data:
            setattr(cfg, key, _str_list(data[key], key))
    for key in ("hn_limit", "top"):
        if key in data:
            if not isinstance(data[key], int) or isinstance(data[key], bool):
                raise ConfigError(f"'{key}' must be an integer")
            setattr(cfg, key, data[key])
    return cfg
