"""Watchlist and WatchlistVersion: what a tenant is watching, pinned in time.

A Watchlist is a name. A WatchlistVersion is the *content* -- include terms, exclude
terms, match mode -- and it is immutable once written. Editing a watchlist appends a
new version; it never rewrites an old one, because a RadarRun that already ran
against version 2 must keep meaning what it meant.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .. import ids
from ..errors import ValidationError
from ..versions import MATCHER_VERSION
from ._base import iso, normalize_terms, require_aware, require_text

MODE_ANY = "any"
MODE_ALL = "all"
MODES = (MODE_ANY, MODE_ALL)


@dataclass(frozen=True)
class Watchlist:
    """A named, tenant-scoped watchlist. Carries no terms; its versions do."""

    watchlist_id: str
    workspace_id: str
    name: str
    created_at: datetime

    @classmethod
    def create(cls, *, workspace_id: str, name: str, created_at: datetime) -> Watchlist:
        canonical = require_text(name, "watchlist name")
        return cls(
            watchlist_id=ids.watchlist_id(workspace_id, canonical),
            workspace_id=workspace_id,
            name=canonical,
            created_at=require_aware(created_at, "created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "watchlist_id": self.watchlist_id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "created_at": iso(self.created_at),
        }


@dataclass(frozen=True)
class WatchlistVersion:
    """An immutable snapshot of one watchlist's terms.

    ``matcher_version`` is stored rather than looked up at match time: a version
    written when the matcher was v1 stays interpretable after a v2 ships.
    """

    version_id: str
    watchlist_id: str
    workspace_id: str
    version_number: int
    include_terms: tuple[str, ...]
    exclude_terms: tuple[str, ...]
    match_mode: str
    matcher_version: str
    created_at: datetime
    entities: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        watchlist_id: str,
        workspace_id: str,
        version_number: int,
        include_terms: Iterable[str],
        exclude_terms: Iterable[str] = (),
        match_mode: str = MODE_ANY,
        created_at: datetime,
        matcher_version: str = MATCHER_VERSION,
        entities: Iterable[str] = (),
        domains: Iterable[str] = (),
    ) -> WatchlistVersion:
        if version_number < 1:
            raise ValidationError("version_number must be 1 or greater")
        if match_mode not in MODES:
            raise ValidationError(f"match_mode must be one of {', '.join(MODES)}")
        include = normalize_terms(include_terms, "include_terms")
        exclude = normalize_terms(exclude_terms, "exclude_terms")
        normalized_entities = normalize_terms(entities, "entities")
        normalized_domains = normalize_terms(domains, "domains")
        if not include:
            raise ValidationError("a watchlist version needs at least one include term")
        overlap = sorted(set(include) & set(exclude))
        if overlap:
            # An include that is also an exclude has no defensible meaning; refusing it
            # is better than picking a precedence rule the tenant cannot see.
            raise ValidationError(
                f"terms cannot be both included and excluded: {', '.join(overlap)}"
            )
        return cls(
            version_id=ids.watchlist_version_id(
                watchlist_id,
                version_number,
                include,
                exclude,
                match_mode,
                entities=normalized_entities,
                domains=normalized_domains,
            ),
            watchlist_id=watchlist_id,
            workspace_id=workspace_id,
            version_number=version_number,
            include_terms=include,
            exclude_terms=exclude,
            match_mode=match_mode,
            matcher_version=matcher_version,
            created_at=require_aware(created_at, "created_at"),
            entities=normalized_entities,
            domains=normalized_domains,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "watchlist_id": self.watchlist_id,
            "workspace_id": self.workspace_id,
            "version_number": self.version_number,
            "include_terms": list(self.include_terms),
            "exclude_terms": list(self.exclude_terms),
            "match_mode": self.match_mode,
            "matcher_version": self.matcher_version,
            "created_at": iso(self.created_at),
            "entities": list(self.entities),
            "domains": list(self.domains),
        }
