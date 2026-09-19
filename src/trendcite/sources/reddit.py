"""Reddit adapter via Reddit's public per-subreddit Atom feeds.

Reddit publishes read-only feeds for public subreddits. TrendCite uses those rather
than scraping HTML or calling the authenticated Data API. Feeds carry no vote
counts, so Reddit items contribute corroboration and recency, not engagement.
Reddit often rate-limits or blocks anonymous clients; the adapter then reports the
source as unavailable and the run continues with the other sources.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..http import Transport, fetch_bytes
from ..models import EvidenceItem
from .base import SourceAdapter, SourceUnavailable
from .rss import parse_feed

_SUB_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
FEED = "https://www.reddit.com/r/{sub}/top/.rss?t=week"


def parse_reddit_feed(data: bytes, subreddit: str, fetched_at: datetime) -> list[EvidenceItem]:
    return parse_feed(
        data,
        feed_url=FEED.format(sub=subreddit),
        fetched_at=fetched_at,
        source="reddit",
        label=f"r/{subreddit}",
    )


class RedditAdapter(SourceAdapter):
    name = "reddit"
    description = "Reddit public subreddit Atom feeds (no vote counts; degrades if blocked)"

    def __init__(self, subreddits: list[str], transport: Transport | None = None) -> None:
        super().__init__(transport)
        self.subreddits = [s for s in subreddits if _SUB_RE.match(s)]

    def collect(self, now: datetime) -> list[EvidenceItem]:
        if not self.subreddits:
            raise SourceUnavailable("no valid subreddits configured")
        items: list[EvidenceItem] = []
        errors: list[str] = []
        for sub in self.subreddits[:10]:
            try:
                body = fetch_bytes(FEED.format(sub=sub), transport=self.transport, retries=1)
                items.extend(parse_reddit_feed(body, sub, now))
            except Exception as exc:
                errors.append(f"r/{sub}: {exc}")
        if not items:
            raise SourceUnavailable("Reddit unavailable: " + ("; ".join(errors) or "no items"))
        return items
