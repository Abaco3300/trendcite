"""Normalisation of raw source records into :class:`EvidenceItem` objects."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from .models import EvidenceItem
from .security import (
    MAX_EXCERPT_CHARS,
    MAX_TITLE_CHARS,
    UnsafeURLError,
    canonicalize_url,
    clean_text,
    injection_flags,
)

MAX_AUTHOR_CHARS = 80
MAX_RAW_VALUE_CHARS = 200


def parse_datetime(value: Any) -> datetime | None:
    """Parse epoch seconds, ISO-8601 or RFC-2822 values into aware UTC datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _clean_raw(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in sorted(raw.items()):
        if isinstance(value, bool | int | float) or value is None:
            out[key] = value
        else:
            out[key] = clean_text(value, MAX_RAW_VALUE_CHARS)
    return out


def make_item(
    *,
    source: str,
    source_label: str,
    title: Any,
    url: Any,
    published: Any,
    fetched_at: datetime,
    excerpt: Any = "",
    author: Any = None,
    discussion_url: Any = None,
    metrics: dict[str, Any] | None = None,
    raw: dict[str, Any] | None = None,
) -> EvidenceItem | None:
    """Build a normalised item, or return ``None`` if it lacks required evidence.

    Items without a safe http(s) URL, a title or a parseable date are dropped:
    evidence that cannot be traced is not evidence.
    """
    clean_title = clean_text(title, MAX_TITLE_CHARS)
    if not clean_title:
        return None
    try:
        canonical = canonicalize_url(str(url or ""))
    except UnsafeURLError:
        return None
    published_at = parse_datetime(published)
    if published_at is None:
        return None
    discussion: str | None = None
    if discussion_url:
        try:
            discussion = canonicalize_url(str(discussion_url))
        except UnsafeURLError:
            discussion = None
    clean_excerpt = clean_text(excerpt, MAX_EXCERPT_CHARS)
    clean_metrics: dict[str, float] = {}
    for key, value in (metrics or {}).items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= 0 and number == number:  # excludes NaN
            clean_metrics[key] = number
    flags = injection_flags(f"{clean_title} {clean_excerpt}")
    return EvidenceItem(
        source=source,
        source_label=clean_text(source_label, 120) or source,
        title=clean_title,
        excerpt=clean_excerpt,
        url=canonical,
        published_at=published_at,
        fetched_at=fetched_at.astimezone(UTC),
        author=clean_text(author, MAX_AUTHOR_CHARS) or None,
        discussion_url=discussion,
        metrics=clean_metrics,
        raw=_clean_raw(raw or {}),
        flags=tuple(flags),
    )


def dedupe(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Drop exact duplicates (same source + canonical URL), keeping the first seen."""
    seen: set[tuple[str, str]] = set()
    out: list[EvidenceItem] = []
    for item in items:
        key = (item.source, item.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
