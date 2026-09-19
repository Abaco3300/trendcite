"""Hacker News adapter using the official public Firebase API (read-only, no key)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from ..http import Transport, fetch_json
from ..models import EvidenceItem
from ..normalize import make_item
from .base import SourceAdapter, SourceUnavailable

API = "https://hacker-news.firebaseio.com/v0"
HN_ITEM = "https://news.ycombinator.com/item?id={id}"


def normalize_hn_item(record: Any, fetched_at: datetime) -> EvidenceItem | None:
    """Normalise one HN item JSON object (``type == "story"``) into evidence."""
    if not isinstance(record, dict) or record.get("type") != "story":
        return None
    if record.get("dead") or record.get("deleted"):
        return None
    item_id = record.get("id")
    if not isinstance(item_id, int):
        return None
    discussion = HN_ITEM.format(id=item_id)
    return make_item(
        source="hackernews",
        source_label="Hacker News",
        title=record.get("title"),
        url=record.get("url") or discussion,
        published=record.get("time"),
        fetched_at=fetched_at,
        excerpt=record.get("text", ""),
        author=record.get("by"),
        discussion_url=discussion,
        metrics={"points": record.get("score", 0), "comments": record.get("descendants", 0)},
        raw={"hn_id": item_id},
    )


class HackerNewsAdapter(SourceAdapter):
    name = "hackernews"
    description = "Hacker News official API (top/new story lists)"

    def __init__(
        self,
        limit: int = 30,
        lists: tuple[str, ...] = ("topstories",),
        transport: Transport | None = None,
    ) -> None:
        super().__init__(transport)
        self.limit = max(1, min(limit, 100))
        self.lists = tuple(n for n in lists if n in {"topstories", "newstories", "beststories"})

    def _item(self, item_id: int) -> Any:
        try:
            return fetch_json(
                f"{API}/item/{int(item_id)}.json", transport=self.transport, retries=1
            )
        except Exception:
            return None

    def collect(self, now: datetime) -> list[EvidenceItem]:
        ids: list[int] = []
        for list_name in self.lists or ("topstories",):
            try:
                data = fetch_json(f"{API}/{list_name}.json", transport=self.transport)
            except Exception as exc:
                raise SourceUnavailable(f"Hacker News unavailable: {exc}") from exc
            if isinstance(data, list):
                ids.extend(i for i in data[: self.limit] if isinstance(i, int))
        ids = list(dict.fromkeys(ids))
        with ThreadPoolExecutor(max_workers=6) as pool:
            records = list(pool.map(self._item, ids))
        items = [normalize_hn_item(r, now) for r in records]
        return [i for i in items if i is not None]
