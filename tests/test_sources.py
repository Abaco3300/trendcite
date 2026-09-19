from __future__ import annotations

import json

import pytest

from trendcite.config import Config
from trendcite.http import FetchError, fetch_bytes
from trendcite.pipeline import collect, make_adapters, run_live
from trendcite.sources import (
    GitHubAdapter,
    HackerNewsAdapter,
    RedditAdapter,
    RSSAdapter,
    SourceUnavailable,
    XAdapter,
)
from trendcite.sources.rss import FeedParseError, parse_feed

from .conftest import NOW

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>MCP servers in production</title><link>https://example.com/mcp</link>
<pubDate>Fri, 18 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>"""


class FakeTransport:
    """Maps URL substrings to (status, body). Records calls."""

    def __init__(self, routes: dict[str, tuple[int, bytes]]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> tuple[int, bytes]:
        self.calls.append(url)
        for key, value in self.routes.items():
            if key in url:
                return value
        return 404, b""


def test_fetch_retries_transient_errors_then_succeeds() -> None:
    responses = iter([(503, b""), (429, b""), (200, b"ok")])
    sleeps: list[float] = []
    body = fetch_bytes(
        "https://example.com/x",
        transport=lambda u, t: next(responses),
        sleep=sleeps.append,
        retries=2,
    )
    assert body == b"ok"
    assert sleeps == [0.75, 1.5]


def test_fetch_does_not_retry_client_errors() -> None:
    calls: list[str] = []

    def transport(url: str, timeout: float) -> tuple[int, bytes]:
        calls.append(url)
        return 403, b""

    with pytest.raises(FetchError, match="HTTP 403"):
        fetch_bytes("https://example.com/x", transport=transport, sleep=lambda s: None)
    assert len(calls) == 1


def test_fetch_handles_network_errors() -> None:
    def transport(url: str, timeout: float) -> tuple[int, bytes]:
        raise OSError("connection refused")

    with pytest.raises(FetchError, match="network error"):
        fetch_bytes("https://example.com/x", transport=transport, sleep=lambda s: None)


def test_fetch_refuses_unsafe_urls_without_calling_transport() -> None:
    fake = FakeTransport({})
    with pytest.raises(FetchError):
        fetch_bytes("http://169.254.169.254/latest", transport=fake)
    with pytest.raises(FetchError):
        fetch_bytes("file:///etc/passwd", transport=fake)
    assert fake.calls == []


def test_fetch_rejects_oversized_bodies() -> None:
    with pytest.raises(FetchError, match="exceeds"):
        fetch_bytes("https://example.com/x", transport=lambda u, t: (200, b"x" * 2_000_001))


def test_feed_parser_rejects_dtd_and_entities() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><rss><channel></channel></rss>'
    )
    with pytest.raises(FeedParseError):
        parse_feed(bomb, feed_url="https://example.com/f", fetched_at=NOW)
    with pytest.raises(FeedParseError):
        parse_feed(b"not xml at all", feed_url="https://example.com/f", fetched_at=NOW)


def test_rss_adapter_survives_one_bad_feed() -> None:
    fake = FakeTransport({"good": (200, RSS), "bad": (500, b"")})
    adapter = RSSAdapter(["https://example.com/bad", "https://example.com/good"], transport=fake)
    items = adapter.collect(NOW)
    assert [i.title for i in items] == ["MCP servers in production"]


def test_rss_adapter_all_feeds_failing_raises_unavailable() -> None:
    adapter = RSSAdapter(["https://example.com/bad"], transport=FakeTransport({"bad": (404, b"")}))
    with pytest.raises(SourceUnavailable):
        adapter.collect(NOW)


def test_hackernews_adapter_with_mocked_api() -> None:
    story = {
        "id": 7,
        "type": "story",
        "time": 1789725600,
        "title": "MCP servers",
        "url": "https://example.com/s",
        "score": 50,
        "descendants": 5,
    }
    fake = FakeTransport(
        {
            "topstories.json": (200, json.dumps([7, 8]).encode()),
            "item/7.json": (200, json.dumps(story).encode()),
            "item/8.json": (500, b""),
        }
    )
    items = HackerNewsAdapter(limit=5, transport=fake).collect(NOW)
    assert [i.title for i in items] == ["MCP servers"]


def test_hackernews_adapter_unavailable() -> None:
    with pytest.raises(SourceUnavailable):
        HackerNewsAdapter(transport=FakeTransport({})).collect(NOW)


def test_github_adapter_with_mocked_api() -> None:
    payload = {
        "items": [
            {
                "full_name": "o/mcp",
                "html_url": "https://github.com/o/mcp",
                "description": "MCP server",
                "owner": {"login": "o"},
                "created_at": "2026-09-17T00:00:00Z",
                "stargazers_count": 3,
            }
        ]
    }
    fake = FakeTransport({"api.github.com": (200, json.dumps(payload).encode())})
    items = GitHubAdapter(["mcp"], transport=fake).collect(NOW)
    assert [i.url for i in items] == ["https://github.com/o/mcp"]
    assert "created%3A%3E%3D2026-09-04" in fake.calls[0]


def test_github_rate_limited_is_graceful() -> None:
    fake = FakeTransport({"api.github.com": (403, b"")})
    with pytest.raises(SourceUnavailable, match="GitHub"):
        GitHubAdapter(["mcp"], transport=fake).collect(NOW)


def test_reddit_adapter_blocked_and_invalid_names() -> None:
    adapter = RedditAdapter(["ok_sub", "../../etc", "bad name"], transport=FakeTransport({}))
    assert adapter.subreddits == ["ok_sub"]
    with pytest.raises(SourceUnavailable, match="Reddit unavailable"):
        adapter.collect(NOW)


def test_x_adapter_is_interface_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    with pytest.raises(SourceUnavailable, match="not configured"):
        XAdapter().collect(NOW)
    monkeypatch.setenv("X_BEARER_TOKEN", "placeholder-not-a-real-token")
    with pytest.raises(SourceUnavailable, match="interface only"):
        XAdapter().collect(NOW)


def test_collect_records_failures_and_continues() -> None:
    fake = FakeTransport({"example.com/good": (200, RSS)})
    cfg = Config(sources=["hackernews", "rss", "reddit", "x"], feeds=["https://example.com/good"])
    items, status = collect(make_adapters(cfg, transport=fake), NOW)
    by_name = {s.source: s for s in status}
    assert len(items) == 1
    assert by_name["rss"].ok and by_name["rss"].items == 1
    assert not by_name["hackernews"].ok
    assert not by_name["reddit"].ok
    assert not by_name["x"].ok


def test_run_live_with_everything_down_still_returns_report() -> None:
    report = run_live(Config(), transport=FakeTransport({}), now=NOW)
    assert report.briefs == []
    assert report.total_items == 0
    assert all(not s.ok for s in report.source_status)


def test_unknown_source_rejected() -> None:
    with pytest.raises(ValueError, match="unknown source"):
        make_adapters(Config(sources=["myspace"]))
