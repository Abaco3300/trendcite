"""Shared value helpers for the Cloud domain.

Domain objects are plain frozen dataclasses with no knowledge of storage. What they
do own is their own validity: a Workspace with a blank slug, or a RadarRun pinned to
a naive datetime, must be impossible to construct rather than merely discouraged.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from ..errors import ValidationError

#: Names and slugs are bounded so a domain object can never overflow a column.
MAX_NAME = 120
MAX_TERM = 80
MAX_TERMS = 200


def require_aware(value: datetime, field: str) -> datetime:
    """Return ``value`` in UTC, refusing naive datetimes.

    A naive datetime is ambiguous, and ``astimezone`` would silently resolve it using
    the *server's* local zone. For a tenant-facing evaluation cutoff that is not a
    rounding error, it is a wrong answer, so it is rejected at the boundary.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValidationError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def iso(value: datetime) -> str:
    """Canonical storage form: UTC, ISO-8601. Lexical order matches chronological."""
    return require_aware(value, "timestamp").isoformat()


def parse_iso(value: str) -> datetime:
    """Read back a stored timestamp."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"not an ISO-8601 timestamp: {value!r}") from exc
    return require_aware(parsed, "timestamp")


def require_text(value: str, field: str, *, limit: int = MAX_NAME) -> str:
    """A non-blank, whitespace-collapsed, length-bounded string."""
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValidationError(f"{field} must not be blank")
    if len(cleaned) > limit:
        raise ValidationError(f"{field} must be at most {limit} characters")
    return cleaned


def normalize_terms(terms: Iterable[str], field: str) -> tuple[str, ...]:
    """Lowercase, de-duplicate and sort terms.

    Sorting is what makes a watchlist version content-addressable: the same terms
    entered in a different order are the same version, not a spurious new one.
    """
    seen: set[str] = set()
    for raw in terms:
        cleaned = " ".join(str(raw).split()).lower()
        if not cleaned:
            continue
        if len(cleaned) > MAX_TERM:
            raise ValidationError(f"{field} entry must be at most {MAX_TERM} characters")
        seen.add(cleaned)
    if len(seen) > MAX_TERMS:
        raise ValidationError(f"{field} must contain at most {MAX_TERMS} terms")
    return tuple(sorted(seen))
