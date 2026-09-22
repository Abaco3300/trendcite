"""The single place where observation identity and de-duplication are decided.

Source adapters report *what they saw*. They do not decide what counts as the same
thing; that decision lives here, so every source gets the same rules and a new
adapter inherits them for free.

Two different questions are answered by two different keys:

``observation_id``
    "Is this the same record from the same source?" Used to de-duplicate a single
    run and to line up metric readings across runs. Resolved with a fixed hierarchy:

    1. **native external id** - the id the source itself assigns (Hacker News item
       id, GitHub ``full_name``, RSS ``guid``, Atom ``entry_id``). Most reliable:
       survives URL rewrites, tracking parameters and title edits.
    2. **canonical URL** - the normalised story key, when the source gives no id.
    3. **content fingerprint** - a hash of the normalised title plus the head of the
       excerpt, when there is no usable URL either.

    The id is always scoped by source. The same article seen on Hacker News and in
    an RSS mirror is *two* observations of *one* story, and TrendCite needs both:
    dropping one would hide that two channels carried it, and merging them would
    invent corroboration that does not exist.

``story_key``
    "Is this the same underlying story, whichever channel carried it?" Scheme,
    ``www.`` and a trailing slash are ignored. This is what corroboration,
    diversity and the cluster gates count, so a syndicated echo can never inflate
    them.

Both keys are pure functions of already-sanitised inputs; nothing here fetches,
parses or trusts remote content.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .versions import OBSERVATION_IDENTITY_VERSION

#: Where each adapter records the id the source itself assigned, best first.
#: An adapter that reports none simply falls through to the URL rule.
NATIVE_ID_FIELDS: dict[str, tuple[str, ...]] = {
    "hackernews": ("hn_id",),
    "github": ("full_name",),
    "rss": ("entry_id", "guid"),
    "reddit": ("entry_id", "guid"),
}

#: Identity strategies, in the order they are tried.
STRATEGY_NATIVE_ID = "native_id"
STRATEGY_CANONICAL_URL = "canonical_url"
STRATEGY_FINGERPRINT = "fingerprint"
STRATEGIES = (STRATEGY_NATIVE_ID, STRATEGY_CANONICAL_URL, STRATEGY_FINGERPRINT)

_FINGERPRINT_CHARS = 160
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
_ID_CHARS = 16


def story_key_for_url(url: str) -> str:
    """Identity of the underlying content, independent of the channel it came through.

    Scheme, ``www.`` and a trailing slash are ignored; the stored URL is unchanged.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}?{parts.query}" if parts.query else f"{host}{path}"


def content_fingerprint(title: str, excerpt: str = "") -> str:
    """Stable hash of the normalised title plus the head of the excerpt.

    Case, punctuation and whitespace runs are ignored so that the same post
    re-published with cosmetic differences fingerprints identically.
    """
    blob = _NON_WORD_RE.sub(" ", f"{title} {excerpt}".lower()).strip()
    return hashlib.sha256(blob[:_FINGERPRINT_CHARS].encode()).hexdigest()[:_ID_CHARS]


def native_id(source: str, raw: dict[str, Any] | None) -> str | None:
    """The id the source assigned to this record, or ``None`` if it gave none."""
    for field in NATIVE_ID_FIELDS.get(source, ()):
        value = (raw or {}).get(field)
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


@dataclass(frozen=True)
class ObservationIdentity:
    """How one observation was identified, and the value that identified it."""

    observation_id: str
    strategy: str  # one of STRATEGIES
    basis: str  # the value the id was derived from, kept for auditability
    story_key: str
    version: str = OBSERVATION_IDENTITY_VERSION

    def to_dict(self) -> dict[str, str]:
        return {
            "observation_id": self.observation_id,
            "strategy": self.strategy,
            "basis": self.basis,
            "story_key": self.story_key,
            "version": self.version,
        }


def resolve_identity(
    *,
    source: str,
    url: str,
    title: str,
    excerpt: str = "",
    raw: dict[str, Any] | None = None,
) -> ObservationIdentity:
    """Apply the identity hierarchy: native external id -> canonical URL -> fingerprint."""
    key = story_key_for_url(url)
    native = native_id(source, raw)
    if native is not None:
        strategy, basis = STRATEGY_NATIVE_ID, native
    elif key:
        strategy, basis = STRATEGY_CANONICAL_URL, key
    else:
        strategy, basis = STRATEGY_FINGERPRINT, content_fingerprint(title, excerpt)
    digest = hashlib.sha256(
        f"{OBSERVATION_IDENTITY_VERSION}|{source}|{strategy}|{basis}".encode()
    ).hexdigest()
    return ObservationIdentity(
        observation_id=digest[:_ID_CHARS], strategy=strategy, basis=basis, story_key=key
    )
