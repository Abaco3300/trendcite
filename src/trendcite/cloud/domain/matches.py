"""Match and MatchEvaluation: current state and the history that produced it.

These are two different questions and they get two different tables:

:class:`Match`
    "Is signal S currently on radar R for workspace W?" One row per
    (workspace, radar, signal), updated in place. This is what a tenant reads.
:class:`MatchEvaluation`
    "What did the matcher decide, and why, when run X evaluated signal S against
    watchlist version V?" Append-only, one row per (run, watchlist version, signal),
    never updated. This is what makes a match auditable after the fact.

Collapsing them would make the current view cheap and the audit trail impossible, so
they stay separate even though the first is derivable from the second.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from .. import ids
from ..errors import ValidationError
from ..versions import MATCHER_VERSION
from ._base import iso, require_aware

# ---------------------------------------------------------------------------- decisions

#: The signal satisfies the watchlist's include rule and hits no exclude term.
DECISION_MATCHED = "matched"
#: The signal does not satisfy the include rule.
DECISION_NO_MATCH = "no_match"
#: The signal hit an exclude term. Distinct from ``no_match`` so a tenant can tell
#: "my watchlist never described this" from "my watchlist deliberately rejected it".
DECISION_EXCLUDED = "excluded"
DECISIONS = (DECISION_MATCHED, DECISION_NO_MATCH, DECISION_EXCLUDED)

# ------------------------------------------------------------------------ match status

MATCH_ACTIVE = "active"
MATCH_DROPPED = "dropped"
MATCH_STATUSES = (MATCH_ACTIVE, MATCH_DROPPED)


@dataclass(frozen=True)
class MatchEvaluation:
    """One append-only, explainable matcher decision."""

    evaluation_id: str
    workspace_id: str
    radar_id: str
    run_id: str
    watchlist_version_id: str
    signal_id: str
    decision: str
    strength: float
    matched_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    matched_fields: tuple[str, ...]
    explanation: str
    matcher_version: str
    evaluated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        radar_id: str,
        run_id: str,
        watchlist_version_id: str,
        signal_id: str,
        decision: str,
        strength: float,
        matched_terms: Iterable[str] = (),
        excluded_terms: Iterable[str] = (),
        matched_fields: Iterable[str] = (),
        explanation: str,
        evaluated_at: datetime,
        matcher_version: str = MATCHER_VERSION,
    ) -> MatchEvaluation:
        if decision not in DECISIONS:
            raise ValidationError(f"decision must be one of {', '.join(DECISIONS)}")
        return cls(
            evaluation_id=ids.match_evaluation_id(run_id, watchlist_version_id, signal_id),
            workspace_id=workspace_id,
            radar_id=radar_id,
            run_id=run_id,
            watchlist_version_id=watchlist_version_id,
            signal_id=signal_id,
            decision=decision,
            strength=round(float(strength), 4),
            matched_terms=tuple(matched_terms),
            excluded_terms=tuple(excluded_terms),
            matched_fields=tuple(matched_fields),
            explanation=" ".join(explanation.split())[:400],
            matcher_version=matcher_version,
            evaluated_at=require_aware(evaluated_at, "evaluated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "run_id": self.run_id,
            "watchlist_version_id": self.watchlist_version_id,
            "signal_id": self.signal_id,
            "decision": self.decision,
            "strength": self.strength,
            "matched_terms": list(self.matched_terms),
            "excluded_terms": list(self.excluded_terms),
            "matched_fields": list(self.matched_fields),
            "explanation": self.explanation,
            "matcher_version": self.matcher_version,
            "evaluated_at": iso(self.evaluated_at),
        }


@dataclass(frozen=True)
class Match:
    """The current state of one signal on one radar, for one workspace."""

    match_id: str
    workspace_id: str
    radar_id: str
    signal_id: str
    status: str
    strength: float
    watchlist_version_id: str
    matcher_version: str
    first_matched_at: datetime
    last_matched_at: datetime
    last_run_id: str

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        radar_id: str,
        signal_id: str,
        strength: float,
        watchlist_version_id: str,
        matched_at: datetime,
        run_id: str,
        matcher_version: str = MATCHER_VERSION,
    ) -> Match:
        when = require_aware(matched_at, "matched_at")
        return cls(
            match_id=ids.match_id(workspace_id, radar_id, signal_id),
            workspace_id=workspace_id,
            radar_id=radar_id,
            signal_id=signal_id,
            status=MATCH_ACTIVE,
            strength=round(float(strength), 4),
            watchlist_version_id=watchlist_version_id,
            matcher_version=matcher_version,
            first_matched_at=when,
            last_matched_at=when,
            last_run_id=run_id,
        )

    def reaffirmed(
        self,
        *,
        strength: float,
        watchlist_version_id: str,
        matched_at: datetime,
        run_id: str,
    ) -> Match:
        """A later run matched this signal again. ``first_matched_at`` never moves."""
        return replace(
            self,
            status=MATCH_ACTIVE,
            strength=round(float(strength), 4),
            watchlist_version_id=watchlist_version_id,
            last_matched_at=require_aware(matched_at, "matched_at"),
            last_run_id=run_id,
        )

    def dropped(self, *, run_id: str) -> Match:
        """A later run did not match this signal.

        The row is kept, not deleted: "this used to be on my radar and no longer is"
        is information, and deleting it would silently rewrite the tenant's history.
        """
        return replace(self, status=MATCH_DROPPED, last_run_id=run_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "signal_id": self.signal_id,
            "status": self.status,
            "strength": self.strength,
            "watchlist_version_id": self.watchlist_version_id,
            "matcher_version": self.matcher_version,
            "first_matched_at": iso(self.first_matched_at),
            "last_matched_at": iso(self.last_matched_at),
            "last_run_id": self.last_run_id,
        }
