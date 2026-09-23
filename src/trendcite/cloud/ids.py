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

from .versions import CLOUD_ID_VERSION, RUN_IDEMPOTENCY_VERSION, TICK_IDEMPOTENCY_VERSION

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


# --------------------------------------------------------------------------- alerting


def alert_policy_id(workspace: str, radar: str) -> str:
    """One delivery policy per (workspace, radar)."""
    return cloud_id("alert-policy", workspace, radar)


def alert_subject_key(workspace: str, watchlist: str, signal: str) -> str:
    """The thing an alert is *about*, independent of any one event.

    Deduplication and cooldown are different rules over the same subject: dedupe asks
    "is this the same event again", cooldown asks "have we interrupted this tenant
    about this subject recently". Both need one agreed name for the subject, and this
    is it -- workspace + watchlist + signal, never the radar, because moving a
    watchlist onto a second radar must not reset a tenant's quiet period.
    """
    return "|".join((workspace, watchlist, signal))


def alert_baseline_id(workspace: str, watchlist: str, signal: str) -> str:
    """The last *delivered* state of one subject. One row per subject."""
    return cloud_id("alert-baseline", workspace, watchlist, signal)


def alert_candidate_id(
    workspace: str,
    watchlist: str,
    signal: str,
    snapshot: str,
    materiality_version: str,
) -> str:
    """The logical identity of one alertable event.

    Pinned to the snapshot, so the same evaluation reconsidered -- by a retried run,
    a re-run, or a second pass over the same evidence -- is one candidate rather than
    a new one each time. The materiality version joins the identity because a v2
    engine looking at the same snapshot reached its own, separately auditable verdict.
    """
    return cloud_id("alert-candidate", workspace, watchlist, signal, snapshot, materiality_version)


def material_event_id(snapshot: str, kind: str) -> str:
    return cloud_id("material-event", snapshot, kind)


def alert_id(candidate: str) -> str:
    """One Alert per qualified candidate, and the candidate already has identity."""
    return cloud_id("alert", candidate)


def delivery_attempt_id(workspace: str, target_kind: str, target_id: str, attempt: int) -> str:
    """Identity of one attempt. Attempt 2 is a different row, never an overwrite."""
    return cloud_id("delivery-attempt", workspace, target_kind, target_id, str(attempt))


def digest_id(workspace: str, radar: str, digest_date: str) -> str:
    """One digest per radar per day: rebuilding a day is idempotent, not additive."""
    return cloud_id("digest", workspace, radar, digest_date)


def digest_item_id(digest: str, signal: str) -> str:
    """One row per signal per digest, which is what makes "a signal appears once" a
    database fact rather than a sorting convention."""
    return cloud_id("digest-item", digest, signal)


# ------------------------------------------------------------------------- scheduling


def radar_schedule_id(workspace: str, radar: str) -> str:
    """One schedule per (workspace, radar).

    Deliberately not a function of the cadence: changing "daily" to "hourly" is an
    edit to an existing schedule, not the birth of a second one, and a radar that
    could be on two schedules at once is a radar nobody can reason about.
    """
    return cloud_id("radar-schedule", workspace, radar)


def schedule_tick_idempotency_key(schedule: str, evaluation_cutoff: str) -> str:
    """The logical identity of one scheduled execution: *this* schedule at *this*
    boundary.

    The planner is allowed to be dumb and re-derive the same boundary as often as it
    likes -- two planner passes, a restarted worker, an external scheduler that fires
    twice -- because all of them land on this one key. It is not the same thing as a
    run's idempotency key: a tick is the decision to execute, the run is the execution,
    and two schedules pointed at one radar would share a run while keeping their own
    ticks.
    """
    material = "|".join((TICK_IDEMPOTENCY_VERSION, schedule, evaluation_cutoff))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:_ID_CHARS]


def schedule_tick_id(workspace: str, idempotency_key: str) -> str:
    return cloud_id("schedule-tick", workspace, idempotency_key)
