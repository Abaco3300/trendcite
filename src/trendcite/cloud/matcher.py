"""WatchlistMatcher v1: deterministic, explainable, and deliberately boring.

A tenant has to be able to answer "why is this on my radar?" without reading code, so
every decision this module makes is reducible to a sentence naming the exact terms
and the exact fields that produced it. That rules out fuzzy similarity, embeddings
and stemming -- all of which would make the matcher better at guessing and much worse
at explaining.

The rules, in full:

**Normalisation.** Text and terms are lowercased, stripped of punctuation, and
whitespace-collapsed. A term matches a field when it occurs there as a whole token
sequence, so ``"ai"`` matches ``"ai agents"`` but not ``"chain"``.

**Exclusion wins.** Exclude terms are checked first. One hit means ``excluded``,
whatever the include terms say -- a tenant who said "not crypto" meant it.

**Include mode.** ``any`` matches on one include hit; ``all`` requires every include
term. The mode is stored on the watchlist version, not chosen at match time.

**Strength.** The fraction of include terms that hit, weighted by the *strongest*
field each one hit (see :data:`FIELD_WEIGHTS`). Matching a term in the topic label
means more than matching it in the title of one piece of evidence, and the number
says so. Strength never affects the decision; it only ranks matches that already
qualify.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ..signal import SignalBrief
from .domain.matches import DECISION_EXCLUDED, DECISION_MATCHED, DECISION_NO_MATCH
from .domain.watchlist import MODE_ALL, WatchlistVersion
from .versions import MATCHER_VERSION

# --------------------------------------------------------------------------- fields

#: The signal's display label.
FIELD_LABEL = "label"
#: The signal's canonical topic key.
FIELD_KEY = "key"
#: Terms the clustering layer associated with the signal.
FIELD_RELATED = "related_terms"
#: Titles of the evidence backing the signal.
FIELD_EVIDENCE = "evidence_title"

#: How much a hit in each field counts towards strength. A term found in the topic
#: itself is stronger evidence of relevance than one found in a single headline.
FIELD_WEIGHTS: dict[str, float] = {
    FIELD_LABEL: 1.0,
    FIELD_KEY: 1.0,
    FIELD_RELATED: 0.75,
    FIELD_EVIDENCE: 0.5,
}

#: Deterministic field order, so explanations read the same way every time.
FIELD_ORDER = (FIELD_LABEL, FIELD_KEY, FIELD_RELATED, FIELD_EVIDENCE)

#: How many evidence titles are considered. Bounded so one huge cluster cannot make a
#: match arbitrarily expensive, and fixed so the result stays reproducible.
MAX_EVIDENCE_TITLES = 25

_NON_WORD = re.compile(r"[^0-9a-z]+")


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


def _haystack(values: Iterable[str]) -> str:
    """One padded, normalised string per field, so token-boundary checks are substrings."""
    parts = [normalize(v) for v in values]
    return " | ".join(f" {p} " for p in parts if p)


def contains_term(haystack: str, term: str) -> bool:
    """True when ``term`` occurs in ``haystack`` as a complete token sequence."""
    needle = normalize(term)
    return bool(needle) and f" {needle} " in haystack


@dataclass(frozen=True)
class MatchTarget:
    """The matchable projection of one signal. Built once, matched against many lists."""

    signal_id: str
    label: str
    key: str
    related_terms: tuple[str, ...]
    evidence_titles: tuple[str, ...]

    @classmethod
    def of(cls, brief: SignalBrief) -> MatchTarget:
        """Project a core :class:`~trendcite.signal.SignalBrief` into matchable text."""
        return cls(
            signal_id=brief.signal.signal_id,
            label=brief.signal.label,
            key=brief.signal.key,
            related_terms=tuple(brief.signal.related_terms),
            evidence_titles=tuple(o.title for o in brief.observations[:MAX_EVIDENCE_TITLES]),
        )

    def fields(self) -> dict[str, str]:
        """Normalised, padded haystacks keyed by field name."""
        return {
            FIELD_LABEL: _haystack([self.label]),
            FIELD_KEY: _haystack([self.key]),
            FIELD_RELATED: _haystack(self.related_terms),
            FIELD_EVIDENCE: _haystack(self.evidence_titles),
        }


@dataclass(frozen=True)
class TermHit:
    """One term, and the best field it was found in."""

    term: str
    field: str

    @property
    def weight(self) -> float:
        return FIELD_WEIGHTS[self.field]


@dataclass(frozen=True)
class MatchOutcome:
    """A decision, its strength, and the sentence that justifies it."""

    decision: str
    strength: float
    matched_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    matched_fields: tuple[str, ...]
    explanation: str
    matcher_version: str = MATCHER_VERSION

    @property
    def matched(self) -> bool:
        return self.decision == DECISION_MATCHED

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "strength": self.strength,
            "matched_terms": list(self.matched_terms),
            "excluded_terms": list(self.excluded_terms),
            "matched_fields": list(self.matched_fields),
            "explanation": self.explanation,
            "matcher_version": self.matcher_version,
        }


def _hits(terms: Sequence[str], fields: dict[str, str]) -> list[TermHit]:
    """Every term that hit, recorded against the strongest field it hit in."""
    found: list[TermHit] = []
    for term in terms:
        for field in FIELD_ORDER:  # strongest field first
            if contains_term(fields[field], term):
                found.append(TermHit(term=term, field=field))
                break
    return found


def _describe(hits: Sequence[TermHit]) -> str:
    return ", ".join(f"{h.term!r} in {h.field}" for h in hits)


class WatchlistMatcher:
    """Evaluates one signal against one watchlist version. Stateless and pure."""

    version = MATCHER_VERSION

    def evaluate(self, watchlist: WatchlistVersion, target: MatchTarget) -> MatchOutcome:
        fields = target.fields()

        # Exclusion is checked first and short-circuits: an excluded signal is never
        # reported as a weak match, because "I said not this" is not a matter of degree.
        excluded = _hits(watchlist.exclude_terms, fields)
        if excluded:
            return MatchOutcome(
                decision=DECISION_EXCLUDED,
                strength=0.0,
                matched_terms=(),
                excluded_terms=tuple(h.term for h in excluded),
                matched_fields=tuple(dict.fromkeys(h.field for h in excluded)),
                explanation=f"excluded by {_describe(excluded)}",
            )

        included = _hits(watchlist.include_terms, fields)
        total = len(watchlist.include_terms)
        strength = round(sum(h.weight for h in included) / total, 4) if total else 0.0
        mode = watchlist.match_mode
        satisfied = len(included) == total if mode == MODE_ALL else bool(included)

        if satisfied:
            explanation = (
                f"matched {len(included)}/{total} include term(s) "
                f"(mode={mode}): {_describe(included)}"
            )
            decision = DECISION_MATCHED
        elif included:
            explanation = (
                f"only {len(included)}/{total} include term(s) matched and mode={mode} "
                f"requires all: {_describe(included)}"
            )
            decision = DECISION_NO_MATCH
        else:
            explanation = f"no include term matched (mode={mode}, {total} term(s) tried)"
            decision = DECISION_NO_MATCH

        return MatchOutcome(
            decision=decision,
            strength=strength if satisfied else 0.0,
            matched_terms=tuple(h.term for h in included),
            excluded_terms=(),
            matched_fields=tuple(dict.fromkeys(h.field for h in included)),
            explanation=explanation,
        )


#: The default matcher. Stateless, so one shared instance is safe.
DEFAULT_MATCHER = WatchlistMatcher()
