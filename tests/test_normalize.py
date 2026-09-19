from __future__ import annotations

from datetime import UTC, datetime

from trendcite.normalize import dedupe, make_item, parse_datetime
from trendcite.sources.github import normalize_github_repo
from trendcite.sources.hackernews import normalize_hn_item
from trendcite.sources.rss import parse_feed

from .conftest import NOW, item


def test_parse_datetime_formats() -> None:
    expected = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    assert parse_datetime(1789732800) == expected
    assert parse_datetime("2026-09-18T12:00:00Z") == expected
    assert parse_datetime("Fri, 18 Sep 2026 12:00:00 GMT") == expected
    assert parse_datetime("2026-09-18T14:00:00+02:00") == expected
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None


def test_make_item_normalises_fields() -> None:
    made = make_item(
        source="rss",
        source_label="Feed",
        title="  <b>Hello</b> &amp; welcome\x00 ",
        url="HTTPS://Example.COM:443/post?utm_source=x&id=7#frag",
        published="2026-09-18T10:00:00Z",
        fetched_at=NOW,
        excerpt="<p>Body</p>",
        author="  Ann ",
        metrics={"points": "12", "bad": "x", "neg": -1},
    )
    assert made is not None
    assert made.title == "Hello & welcome"
    assert made.url == "https://example.com/post?id=7"
    assert made.excerpt == "Body"
    assert made.author == "Ann"
    assert made.metrics == {"points": 12.0}
    assert made.published_at.tzinfo is not None


def test_make_item_drops_untraceable_evidence() -> None:
    base = {"source": "rss", "source_label": "f", "fetched_at": NOW}
    assert make_item(title="t", url="javascript:alert(1)", published="2026-09-18", **base) is None
    assert make_item(title="t", url="", published="2026-09-18", **base) is None
    assert make_item(title="", url="https://example.com", published="2026-09-18", **base) is None
    assert make_item(title="t", url="https://example.com", published="garbage", **base) is None


def test_long_text_is_bounded() -> None:
    made = make_item(
        source="rss",
        source_label="f",
        title="x" * 5000,
        url="https://example.com/a",
        published="2026-09-18",
        fetched_at=NOW,
        excerpt="y" * 50_000,
    )
    assert made is not None
    assert len(made.title) <= 300
    assert len(made.excerpt) <= 1200


def test_hn_normalisation() -> None:
    record = {
        "id": 1,
        "type": "story",
        "by": "pg",
        "time": 1789732800,
        "title": "Hello",
        "url": "https://example.com/x",
        "score": 10,
        "descendants": 4,
    }
    got = normalize_hn_item(record, NOW)
    assert got is not None
    assert got.source == "hackernews"
    assert got.discussion_url == "https://news.ycombinator.com/item?id=1"
    assert got.metrics == {"points": 10.0, "comments": 4.0}
    assert got.engagement() == 12.0
    assert normalize_hn_item({**record, "type": "job"}, NOW) is None
    assert normalize_hn_item({**record, "dead": True}, NOW) is None
    ask = normalize_hn_item({**record, "url": None}, NOW)
    assert ask is not None and ask.url == "https://news.ycombinator.com/item?id=1"


def test_github_normalisation() -> None:
    repo = {
        "full_name": "o/r",
        "html_url": "https://github.com/o/r",
        "description": "desc",
        "owner": {"login": "o"},
        "created_at": "2026-09-10T00:00:00Z",
        "stargazers_count": 100,
        "forks_count": 8,
        "topics": ["a", "b"],
    }
    got = normalize_github_repo(repo, NOW)
    assert got is not None
    assert got.title == "o/r: desc"
    assert got.engagement() == 102.0
    assert got.author == "o"
    assert got.raw["full_name"] == "o/r"


def test_rss_and_atom_parsing() -> None:
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
      <item><title>A</title><link>https://example.com/a</link>
      <pubDate>Fri, 18 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>F</title>
      <entry><title>B</title><link href="https://example.com/b"/>
      <updated>2026-09-18T10:00:00Z</updated><author><name>N</name></author></entry></feed>"""
    a = parse_feed(rss, feed_url="https://example.com/rss", fetched_at=NOW)
    b = parse_feed(atom, feed_url="https://example.com/atom", fetched_at=NOW)
    assert [(i.title, i.source_label) for i in a] == [("A", "T")]
    assert [(i.title, i.author) for i in b] == [("B", "N")]
    assert a[0].raw["feed"] == "https://example.com/rss"


def test_dedupe_keeps_first() -> None:
    one = item("Same", url="https://example.com/same")
    two = item("Same again", url="https://example.com/same")
    other_source = item("Same", url="https://example.com/same", source="hackernews")
    assert dedupe([one, two, other_source]) == [one, other_source]
