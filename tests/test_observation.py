"""The centralised identity and observation layer.

The rule under test throughout: adapters report what they saw, and this layer alone
decides what counts as the same thing.
"""

from __future__ import annotations

from datetime import timedelta

from trendcite.identity import (
    STRATEGY_CANONICAL_URL,
    STRATEGY_FINGERPRINT,
    STRATEGY_NATIVE_ID,
    content_fingerprint,
    native_id,
    resolve_identity,
    story_key_for_url,
)
from trendcite.normalize import dedupe, make_item
from trendcite.observation import (
    Observation,
    ObservationSnapshot,
    dedupe_observations,
    observe,
    story_keys,
)

from .conftest import NOW, item

# ------------------------------------------------------------------ identity hierarchy


def test_native_id_wins_over_the_url() -> None:
    identity = resolve_identity(
        source="hackernews",
        url="https://example.com/a",
        title="A story",
        raw={"hn_id": 4242},
    )
    assert identity.strategy == STRATEGY_NATIVE_ID
    assert identity.basis == "4242"


def test_canonical_url_is_used_when_the_source_gives_no_id() -> None:
    identity = resolve_identity(source="rss", url="https://Example.com/a/", title="A story")
    assert identity.strategy == STRATEGY_CANONICAL_URL
    assert identity.basis == "example.com/a"


def test_fingerprint_is_the_last_resort() -> None:
    identity = resolve_identity(source="rss", url="", title="A story", excerpt="body")
    assert identity.strategy == STRATEGY_FINGERPRINT
    assert identity.basis == content_fingerprint("A story", "body")


def test_native_id_survives_a_rewritten_url() -> None:
    """The same Hacker News story behind a changed link is still one observation."""
    first = resolve_identity(
        source="hackernews", url="https://example.com/v1", title="T", raw={"hn_id": 7}
    )
    second = resolve_identity(
        source="hackernews", url="https://example.com/v2?utm=x", title="T", raw={"hn_id": 7}
    )
    assert first.observation_id == second.observation_id
    assert first.story_key != second.story_key  # different links, same record


def test_identity_is_scoped_by_source() -> None:
    """One link on two channels is two observations of one story, and must stay so."""
    url = "https://example.com/post"
    hn = resolve_identity(source="hackernews", url=url, title="T")
    rss = resolve_identity(source="rss", url=url, title="T")
    assert hn.observation_id != rss.observation_id
    assert hn.story_key == rss.story_key


def test_fingerprint_ignores_case_and_punctuation() -> None:
    assert content_fingerprint("The Same Story!", "body") == content_fingerprint(
        "the   same, story", "body"
    )


def test_fingerprint_separates_different_stories() -> None:
    assert content_fingerprint("story one") != content_fingerprint("story two")


def test_native_id_fields_are_per_source() -> None:
    assert native_id("github", {"full_name": "owner/repo"}) == "owner/repo"
    assert native_id("rss", {"guid": "urn:x"}) == "urn:x"
    assert native_id("rss", {"entry_id": "atom-1", "guid": "urn:x"}) == "atom-1"
    assert native_id("rss", {"guid": "   "}) is None
    assert native_id("x", {"anything": "1"}) is None


def test_story_key_ignores_scheme_www_and_trailing_slash() -> None:
    assert (
        story_key_for_url("http://www.example.com/a/")
        == story_key_for_url("https://example.com/a")
        == "example.com/a"
    )


# ------------------------------------------------------------------------ deduplication


def test_dedupe_collapses_one_record_seen_twice() -> None:
    made = [
        make_item(
            source="hackernews",
            source_label="Hacker News",
            title=title,
            url=url,
            published=NOW.isoformat(),
            fetched_at=NOW,
            raw={"hn_id": 99},
        )
        for title, url in (
            ("Original title", "https://example.com/a"),
            ("Edited title", "https://example.com/a?utm_source=x"),
        )
    ]
    items = [m for m in made if m is not None]
    assert len(items) == 2
    assert len(dedupe(items)) == 1  # same hn_id, so one observation


def test_dedupe_keeps_a_mirror_from_another_channel() -> None:
    """Corroboration logic needs both records; identity must not silently merge them."""
    url = "https://example.com/post"
    hn = item("Mirrored post", source="hackernews", label="Hacker News", url=url)
    rss = item("Mirrored post", source="rss", label="mirror-feed", url=url)
    assert len(dedupe([hn, rss])) == 2
    assert len(story_keys(observe([hn, rss], ingested_at=NOW))) == 1


def test_dedupe_observations_keeps_the_first() -> None:
    first = item("Same thing", source="rss", label="feed", url="https://example.com/x")
    again = item("Same thing", source="rss", label="feed", url="https://example.com/x/")
    kept = dedupe_observations(observe([first, again], ingested_at=NOW))
    assert len(kept) == 1
    assert kept[0].title == "Same thing"


# --------------------------------------------------------------------- time semantics


def test_observation_separates_event_observed_and_ingested_time() -> None:
    later = NOW + timedelta(hours=2)
    obs = Observation.from_evidence(item("A post", hours_ago=5), ingested_at=later)
    assert obs.event_time == NOW - timedelta(hours=5)  # when it happened
    assert obs.observed_at == NOW  # when the source showed it
    assert obs.ingested_at == later  # when this run took it in


def test_observation_engagement_is_none_not_zero_without_metrics() -> None:
    """Unknown reach and no reach are different facts."""
    quiet = Observation.from_evidence(item("No metrics", source="rss"), ingested_at=NOW)
    loud = Observation.from_evidence(
        item("Metrics", source="hackernews", metrics={"points": 10, "comments": 4}),
        ingested_at=NOW,
    )
    assert quiet.engagement() is None
    assert loud.engagement() == 12.0


def test_observation_dict_joins_back_to_the_evidence_row() -> None:
    evidence = item("Joinable", source="hackernews", label="Hacker News")
    obs = Observation.from_evidence(evidence, ingested_at=NOW)
    assert obs.to_dict()["observation_id"] == evidence.to_dict()["observation_id"]
    assert obs.to_dict()["evidence_item_id"] == evidence.to_dict()["id"]


def test_observation_snapshot_captures_metrics_at_a_time() -> None:
    obs = Observation.from_evidence(
        item("Snap", source="hackernews", metrics={"points": 7}), ingested_at=NOW
    )
    snap = ObservationSnapshot.of(obs, captured_at=NOW)
    assert snap.observation_id == obs.observation_id
    assert snap.metrics == {"points": 7.0}
    assert snap.captured_at == NOW
