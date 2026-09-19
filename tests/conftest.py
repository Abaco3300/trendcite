from __future__ import annotations

import hashlib
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from trendcite.models import EvidenceItem
from trendcite.normalize import make_item

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def item(
    title: str,
    *,
    source: str = "rss",
    label: str | None = None,
    url: str | None = None,
    hours_ago: float = 1.0,
    metrics: dict[str, Any] | None = None,
    excerpt: str = "",
) -> EvidenceItem:
    made = make_item(
        source=source,
        source_label=label or f"{source}-feed",
        title=title,
        url=url
        or f"https://example.com/{source}/{hashlib.sha256(title.encode()).hexdigest()[:10]}",
        published=(NOW - timedelta(hours=hours_ago)).isoformat(),
        fetched_at=NOW,
        excerpt=excerpt,
        metrics=metrics,
    )
    assert made is not None
    return made


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs offline: fail loudly if anything opens a network connection."""

    def guard(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network access attempted during an offline test")

    monkeypatch.setattr(socket, "create_connection", guard)
    monkeypatch.setattr(socket.socket, "connect", guard)
