"""Deterministic identity for every Cloud entity.

Cloud ids are content-addressed rather than random. Two consequences, both of them
the point:

* **Logical uniqueness and database uniqueness are the same thing.** The id of a
  membership *is* a function of (workspace, principal), so a repeated write collides
  on the primary key instead of quietly inserting a second row.
* **A run is reproducible.** Replaying the same request against an empty database
  produces the same ids, so fixtures and golden comparisons stay stable.

Ids are 32 hex characters (128 bits). Core signal ids are 16 and are *never*
re-derived here: a signal keeps the identity :mod:`trendcite.signal` gave it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .versions import CLOUD_ID_VERSION, RUN_IDEMPOTENCY_VERSION

_ID_CHARS = 32


def cloud_id(kind: str, *parts: str) -> str:
    """A stable id for ``kind`` derived from the parts that define its identity."""
    material = "|".join((CLOUD_ID_VERSION, kind, *parts))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:_ID_CHARS]


def workspace_id(slug: str) -> str:
    return cloud_id("workspace", slug)


def membership_id(workspace: str, principal: str) -> str:
    return cloud_id("membership", workspace, principal)


def watchlist_id(workspace: str, name: str) -> str:
    return cloud_id("watchlist", workspace, name)


def watchlist_version_id(
    watchlist: str,
    version_number: int,
    include: Iterable[str],
    exclude: Iterable[str],
    mode: str,
    related: Iterable[str] = (),
    entities: Iterable[str] = (),
    domains: Iterable[str] = (),
) -> str:
    """Content-addressed over the terms themselves.

    An immutable version's id is a fingerprint of what it contains, so a "changed"
    old version is a different row. The relevance term sets (related, entities,
    domains) join the fingerprint *only when a version actually declares one*, so
    every version written before they existed keeps the id it was written with.
    """
    parts = [
        watchlist,
        str(version_number),
        ",".join(include),
        ",".join(exclude),
        mode,
    ]
    relevance = (",".join(related), ",".join(entities), ",".join(domains))
    if any(relevance):
        parts.extend(relevance)
    return cloud_id("watchlist-version", *parts)


def radar_id(workspace: str, name: str) -> str:
    return cloud_id("radar", workspace, name)


def radar_version_id(
    radar: str, version_number: int, watchlist_versions: Iterable[str], sources: Iterable[str]
) -> str:
    return cloud_id(
        "radar-version",
        radar,
        str(version_number),
        ",".join(watchlist_versions),
        ",".join(sources),
    )


def run_idempotency_key(workspace: str, radar_version: str, evaluation_cutoff: str) -> str:
    """The logical identity of a run: *this* pinned config evaluated as of *this* time.

    Two requests that agree on all three are the same run, however many times they are
    submitted. The database enforces it; this function only names it.
    """
    material = "|".join((RUN_IDEMPOTENCY_VERSION, workspace, radar_version, evaluation_cutoff))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:_ID_CHARS]


def run_id(workspace: str, idempotency_key: str) -> str:
    return cloud_id("radar-run", workspace, idempotency_key)


def coverage_id(run: str, source: str) -> str:
    return cloud_id("coverage", run, source)


def run_signal_id(run: str, signal: str) -> str:
    return cloud_id("run-signal", run, signal)


def match_id(workspace: str, radar: str, signal: str) -> str:
    return cloud_id("match", workspace, radar, signal)


def match_evaluation_id(run: str, watchlist_version: str, signal: str) -> str:
    return cloud_id("match-evaluation", run, watchlist_version, signal)


def relevance_evaluation_id(
    workspace: str, watchlist_version: str, snapshot: str, matcher_version: str
) -> str:
    """The logical identity of one relevance evaluation.

    Deliberately *not* a function of the run that happened to produce it. The same
    watchlist version judged against the same pinned signal snapshot by the same
    matcher is one logical evaluation however many runs reach it, which is what makes
    re-evaluation idempotent instead of merely repetitive.
    """
    return cloud_id("relevance-evaluation", workspace, watchlist_version, snapshot, matcher_version)


def watchlist_signal_match_id(workspace: str, watchlist: str, signal: str) -> str:
    """Identity of the current (watchlist, signal) relationship, one row per pair."""
    return cloud_id("watchlist-signal-match", workspace, watchlist, signal)


def usage_event_id(workspace: str, dedupe_key: str) -> str:
    return cloud_id("usage-event", workspace, dedupe_key)
