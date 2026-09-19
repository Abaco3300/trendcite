"""RSS 2.0 / Atom feed adapter (standard library XML parsing only)."""

from __future__ import annotations

import xml.etree.ElementTree as ET  # DTD/entity declarations are rejected in parse_feed
from datetime import datetime
from urllib.parse import urlsplit

from ..http import Transport, fetch_bytes
from ..models import EvidenceItem
from ..normalize import make_item
from .base import SourceAdapter, SourceUnavailable

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_ITEMS_PER_FEED = 50


class FeedParseError(ValueError):
    pass


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def parse_feed(
    data: bytes,
    *,
    feed_url: str,
    fetched_at: datetime,
    source: str = "rss",
    label: str | None = None,
) -> list[EvidenceItem]:
    """Parse RSS/Atom bytes into evidence items.

    Documents containing a DOCTYPE or ENTITY declaration are rejected outright,
    which blocks entity-expansion and external-entity attacks without extra deps.
    """
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FeedParseError("feeds with DTD/entity declarations are not accepted")
    try:
        root = ET.fromstring(data)  # noqa: S314 - DTDs rejected above
    except ET.ParseError as exc:
        raise FeedParseError(f"malformed feed: {exc}") from exc

    default_label = label or urlsplit(feed_url).hostname or feed_url
    items: list[EvidenceItem] = []
    if root.tag == f"{ATOM}feed":
        feed_label = label or _text(root.find(f"{ATOM}title")) or default_label
        for entry in root.findall(f"{ATOM}entry")[:MAX_ITEMS_PER_FEED]:
            link = ""
            for link_el in entry.findall(f"{ATOM}link"):
                if link_el.get("rel", "alternate") == "alternate":
                    link = link_el.get("href", "")
                    break
            item = make_item(
                source=source,
                source_label=feed_label,
                title=_text(entry.find(f"{ATOM}title")),
                url=link,
                published=_text(entry.find(f"{ATOM}published"))
                or _text(entry.find(f"{ATOM}updated")),
                fetched_at=fetched_at,
                excerpt=_text(entry.find(f"{ATOM}summary")) or _text(entry.find(f"{ATOM}content")),
                author=_text(entry.find(f"{ATOM}author/{ATOM}name")),
                raw={"feed": feed_url, "entry_id": _text(entry.find(f"{ATOM}id"))},
            )
            if item:
                items.append(item)
        return items

    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise FeedParseError("not an RSS 2.0 or Atom document")
    feed_label = label or _text(channel.find("title")) or default_label
    for entry in channel.findall("item")[:MAX_ITEMS_PER_FEED]:
        item = make_item(
            source=source,
            source_label=feed_label,
            title=_text(entry.find("title")),
            url=_text(entry.find("link")),
            published=_text(entry.find("pubDate")) or _text(entry.find(f"{DC}date")),
            fetched_at=fetched_at,
            excerpt=_text(entry.find("description")),
            author=_text(entry.find("author")) or _text(entry.find(f"{DC}creator")),
            raw={"feed": feed_url, "guid": _text(entry.find("guid"))},
        )
        if item:
            items.append(item)
    return items


class RSSAdapter(SourceAdapter):
    name = "rss"
    description = "RSS 2.0 / Atom feeds listed in configuration"

    def __init__(self, feeds: list[str], transport: Transport | None = None) -> None:
        super().__init__(transport)
        self.feeds = feeds

    def collect(self, now: datetime) -> list[EvidenceItem]:
        if not self.feeds:
            raise SourceUnavailable("no feeds configured")
        items: list[EvidenceItem] = []
        errors: list[str] = []
        for feed in self.feeds:
            try:
                body = fetch_bytes(feed, transport=self.transport)
                items.extend(parse_feed(body, feed_url=feed, fetched_at=now))
            except Exception as exc:  # one bad feed must not sink the others
                errors.append(f"{feed}: {exc}")
        if not items and errors:
            raise SourceUnavailable("; ".join(errors))
        return items
