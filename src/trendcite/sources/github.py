"""GitHub adapter: public repository search, unauthenticated and read-only.

Unauthenticated search is rate limited (roughly 10 requests per minute). TrendCite
makes one request per configured query (max 5) and degrades gracefully when limited.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from ..http import Transport, fetch_json
from ..models import EvidenceItem
from ..normalize import make_item
from .base import SourceAdapter, SourceUnavailable

SEARCH = "https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={n}"


def normalize_github_repo(repo: Any, fetched_at: datetime) -> EvidenceItem | None:
    if not isinstance(repo, dict):
        return None
    raw_owner = repo.get("owner")
    owner: dict[str, Any] = raw_owner if isinstance(raw_owner, dict) else {}
    name = repo.get("full_name") or repo.get("name")
    description = repo.get("description") or ""
    topics = repo.get("topics") or []
    return make_item(
        source="github",
        source_label=f"GitHub/{owner.get('login', 'unknown')}",
        title=f"{name}: {description}" if description else name,
        url=repo.get("html_url"),
        published=repo.get("created_at"),
        fetched_at=fetched_at,
        excerpt=" ".join(str(t) for t in topics[:10]),
        author=owner.get("login"),
        metrics={"stars": repo.get("stargazers_count", 0), "forks": repo.get("forks_count", 0)},
        raw={
            "full_name": name,
            "language": repo.get("language"),
            "pushed_at": repo.get("pushed_at"),
        },
    )


def normalize_github_search(payload: Any, fetched_at: datetime) -> list[EvidenceItem]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return []
    items = [normalize_github_repo(r, fetched_at) for r in payload["items"][:50]]
    return [i for i in items if i is not None]


class GitHubAdapter(SourceAdapter):
    name = "github"
    description = "GitHub public repository search (recently created, sorted by stars)"

    def __init__(
        self,
        queries: list[str],
        days: int = 14,
        per_query: int = 15,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(transport)
        self.queries = queries
        self.days = days
        self.per_query = max(1, min(per_query, 50))

    def collect(self, now: datetime) -> list[EvidenceItem]:
        if not self.queries:
            raise SourceUnavailable("no GitHub queries configured")
        since = (now - timedelta(days=self.days)).date().isoformat()
        items: list[EvidenceItem] = []
        errors: list[str] = []
        for query in self.queries[:5]:
            q = quote(f"{query} created:>={since}", safe="")
            try:
                payload = fetch_json(SEARCH.format(q=q, n=self.per_query), transport=self.transport)
            except Exception as exc:
                errors.append(str(exc))
                continue
            items.extend(normalize_github_search(payload, now))
        if not items and errors:
            raise SourceUnavailable("GitHub search unavailable: " + "; ".join(errors))
        return items
