"""Source adapters. Each adapter is read-only and fails gracefully."""

from .base import SourceAdapter, SourceUnavailable
from .devto import DevToAdapter
from .github import GitHubAdapter
from .hackernews import HackerNewsAdapter
from .reddit import RedditAdapter
from .rss import RSSAdapter
from .x import XAdapter

__all__ = [
    "DevToAdapter",
    "GitHubAdapter",
    "HackerNewsAdapter",
    "RSSAdapter",
    "RedditAdapter",
    "SourceAdapter",
    "SourceUnavailable",
    "XAdapter",
]
