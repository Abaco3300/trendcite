"""DEV Community adapter using the public Forem articles API (read-only, no key)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..http import Transport, fetch_json
from ..models import EvidenceItem
from ..normalize import make_item
from .base import SourceAdapter, SourceUnavailable

API = "https://dev.to/api/articles?per_page={n}"


def normalize_devto_article(record: Any, fetched_at: datetime) -> EvidenceItem | None:
    if not isinstance(record, dict):
        return None
    raw_user = record.get("user")
    user: dict[str, Any] = raw_user if isinstance(raw_user, dict) else {}
    tags = record.get("tag_list") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return make_item(
        source="devto",
        source_label="DEV Community",
        title=record.get("title"),
        url=record.get("canonical_url") or record.get("url"),
        published=record.get("published_at") or record.get("published_timestamp"),
        fetched_at=fetched_at,
        excerpt=record.get("description") or " ".join(str(t) for t in tags[:8]),
        author=user.get("username"),
        metrics={
            "reactions": record.get(
                "positive_reactions_count", record.get("public_reactions_count", 0)
            ),
            "comments": record.get("comments_count", 0),
        },
        raw={"devto_id": record.get("id")},
    )


class DevToAdapter(SourceAdapter):
    name = "devto"
    description = "DEV Community public Forem articles API (popular published articles)"

    def __init__(self, limit: int = 30, transport: Transport | None = None) -> None:
        super().__init__(transport)
        self.limit = max(1, min(limit, 100))

    def collect(self, now: datetime) -> list[EvidenceItem]:
        try:
            payload = fetch_json(API.format(n=self.limit), transport=self.transport)
        except Exception as exc:
            raise SourceUnavailable(f"DEV Community unavailable: {exc}") from exc
        if not isinstance(payload, list):
            raise SourceUnavailable("DEV Community returned an invalid response")
        items = [normalize_devto_article(r, now) for r in payload[: self.limit]]
        return [i for i in items if i is not None]
