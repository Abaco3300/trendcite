"""Canonical tenant-specific relevance for TrendCite Cloud."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ...signal import SignalBrief
from .. import ids
from ..versions import MATCHER_VERSION
from ._base import iso, require_aware
from .watchlist import MODE_ALL, WatchlistVersion

DECISION_MATCHED = "matched"
DECISION_NO_MATCH = "no_match"
DECISION_EXCLUDED = "excluded"

BAND_MINIMAL = "minimal"
BAND_LOW = "low"
BAND_MATERIAL = "material"
BAND_STRONG = "strong"
BAND_VERY_STRONG = "very_strong"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

STATUS_AVAILABLE = "available"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_ERROR = "error"

REASON_EXACT_TERM = "exact_term"
REASON_RELATED_TERM = "related_term"
REASON_ENTITY = "entity"
REASON_DOMAIN = "domain"
REASON_CONTEXT = "context"
REASON_EXCLUSION = "exclusion"

POLARITY_POSITIVE = "positive"
POLARITY_NEGATIVE = "negative"

MATCH_ACTIVE = "active"
MATCH_STALE = "stale"
MATCH_DISMISSED = "dismissed"
MATCH_MUTED = "muted"

POSITIVE_THRESHOLD = 50.0
GENERIC_ONLY_CAP = 39.0

COMPONENT_EXACT = "exact_phrase"
COMPONENT_ENTITY = "entity"
COMPONENT_RELATED = "related_term"
COMPONENT_DOMAIN = "domain"
COMPONENT_CONTEXT = "context_overlap"

WEIGHTS: dict[str, float] = {
    COMPONENT_EXACT: 30.0,
    COMPONENT_ENTITY: 25.0,
    COMPONENT_RELATED: 15.0,
    COMPONENT_DOMAIN: 15.0,
    COMPONENT_CONTEXT: 15.0,
}

GENERIC_TERMS = frozenset(
    {
        "agent",
        "agents",
        "ai",
        "app",
        "apps",
        "data",
        "platform",
        "server",
        "software",
        "tool",
        "tools",
    }
)


@dataclass(frozen=True)
class MatchReason:
    reason_type: str
    value: str
    field: str
    contribution: float
    polarity: str = POLARITY_POSITIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_type": self.reason_type,
            "value": self.value,
            "field": self.field,
            "contribution": self.contribution,
            "polarity": self.polarity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MatchReason:
        return cls(
            reason_type=str(data["reason_type"]),
            value=str(data["value"]),
            field=str(data["field"]),
            contribution=float(data["contribution"]),
            polarity=str(data.get("polarity", POLARITY_POSITIVE)),
        )


@dataclass(frozen=True)
class RelevanceComponent:
    name: str
    weight: float
    value: float | None
    status: str
    contribution: float
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "value": self.value,
            "status": self.status,
            "contribution": self.contribution,
            "basis": self.basis,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelevanceComponent:
        raw = data.get("value")
        return cls(
            name=str(data["name"]),
            weight=float(data["weight"]),
            value=None if raw is None else float(raw),
            status=str(data["status"]),
            contribution=float(data["contribution"]),
            basis=str(data["basis"]),
        )


@dataclass(frozen=True)
class RelevanceOutcome:
    score: float
    band: str
    confidence: str
    decision: str
    components: tuple[RelevanceComponent, ...]
    reasons: tuple[MatchReason, ...]
    matcher_version: str = MATCHER_VERSION

    @property
    def matched(self) -> bool:
        return self.decision == DECISION_MATCHED

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "band": self.band,
            "confidence": self.confidence,
            "decision": self.decision,
        }


@dataclass(frozen=True)
class RelevanceTarget:
    signal_id: str
    snapshot_id: str
    label: str
    key: str
    related_terms: tuple[str, ...]
    context: tuple[str, ...]

    @classmethod
    def of(cls, brief: SignalBrief) -> RelevanceTarget:
        return cls(
            signal_id=brief.signal.signal_id,
            snapshot_id=brief.snapshot.snapshot_id,
            label=brief.signal.label,
            key=brief.signal.key,
            related_terms=tuple(brief.signal.related_terms),
            context=tuple(o.title for o in brief.observations[:25]),
        )


@dataclass(frozen=True)
class RelevanceEvaluation:
    evaluation_id: str
    workspace_id: str
    watchlist_id: str
    watchlist_version_id: str
    signal_id: str
    snapshot_id: str
    radar_id: str
    radar_run_id: str
    score: float
    band: str
    confidence: str
    decision: str
    reasons: tuple[MatchReason, ...]
    components: tuple[RelevanceComponent, ...]
    matcher_version: str
    evaluated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        watchlist: WatchlistVersion,
        target: RelevanceTarget,
        outcome: RelevanceOutcome,
        evaluated_at: datetime,
        radar_id: str = "",
        radar_run_id: str = "",
    ) -> RelevanceEvaluation:
        return cls(
            evaluation_id=ids.relevance_evaluation_id(
                workspace_id,
                watchlist.version_id,
                target.snapshot_id,
                outcome.matcher_version,
            ),
            workspace_id=workspace_id,
            watchlist_id=watchlist.watchlist_id,
            watchlist_version_id=watchlist.version_id,
            signal_id=target.signal_id,
            snapshot_id=target.snapshot_id,
            radar_id=radar_id,
            radar_run_id=radar_run_id,
            score=outcome.score,
            band=outcome.band,
            confidence=outcome.confidence,
            decision=outcome.decision,
            reasons=outcome.reasons,
            components=outcome.components,
            matcher_version=outcome.matcher_version,
            evaluated_at=require_aware(evaluated_at, "evaluated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "workspace_id": self.workspace_id,
            "watchlist_id": self.watchlist_id,
            "watchlist_version_id": self.watchlist_version_id,
            "signal_id": self.signal_id,
            "snapshot_id": self.snapshot_id,
            "radar_id": self.radar_id,
            "radar_run_id": self.radar_run_id,
            "score": self.score,
            "band": self.band,
            "confidence": self.confidence,
            "decision": self.decision,
            "matcher_version": self.matcher_version,
            "evaluated_at": iso(self.evaluated_at),
        }


@dataclass(frozen=True)
class WatchlistSignalMatch:
    match_id: str
    workspace_id: str
    watchlist_id: str
    signal_id: str
    status: str
    current_relevance_score: float
    current_band: str
    current_confidence: str
    current_evaluation_id: str
    first_matched_at: datetime
    last_matched_at: datetime

    @classmethod
    def from_evaluation(
        cls,
        evaluation: RelevanceEvaluation,
        *,
        matched_at: datetime,
        existing: WatchlistSignalMatch | None = None,
    ) -> WatchlistSignalMatch:
        when = require_aware(matched_at, "matched_at")
        first = when if existing is None else existing.first_matched_at
        status = (
            MATCH_ACTIVE if existing is None or existing.status == MATCH_STALE else existing.status
        )
        return cls(
            match_id=ids.watchlist_signal_match_id(
                evaluation.workspace_id,
                evaluation.watchlist_id,
                evaluation.signal_id,
            ),
            workspace_id=evaluation.workspace_id,
            watchlist_id=evaluation.watchlist_id,
            signal_id=evaluation.signal_id,
            status=status,
            current_relevance_score=evaluation.score,
            current_band=evaluation.band,
            current_confidence=evaluation.confidence,
            current_evaluation_id=evaluation.evaluation_id,
            first_matched_at=first,
            last_matched_at=when,
        )


@dataclass(frozen=True)
class RadarSignalRelevance:
    signal_id: str
    score: float
    band: str
    confidence: str
    winning_watchlist_id: str
    matching_watchlist_ids: tuple[str, ...]


def relevance_band(score: float) -> str:
    bounded = max(0.0, min(100.0, float(score)))
    if bounded < 20:
        return BAND_MINIMAL
    if bounded < 40:
        return BAND_LOW
    if bounded < 60:
        return BAND_MATERIAL
    if bounded < 80:
        return BAND_STRONG
    return BAND_VERY_STRONG


def aggregate_radar(
    signal_id: str,
    evaluations: Iterable[RelevanceEvaluation],
) -> RadarSignalRelevance | None:
    matched = []
    for evaluation in evaluations:
        if evaluation.signal_id == signal_id and evaluation.decision == DECISION_MATCHED:
            matched.append(evaluation)
    if not matched:
        return None
    winner = matched[0]
    for candidate in matched[1:]:
        better_score = candidate.score > winner.score
        tie_break = candidate.score == winner.score and candidate.watchlist_id < winner.watchlist_id
        if better_score or tie_break:
            winner = candidate
    watchlist_ids = sorted(item.watchlist_id for item in matched)
    unique_watchlists = tuple(dict.fromkeys(watchlist_ids))
    return RadarSignalRelevance(
        signal_id=signal_id,
        score=winner.score,
        band=winner.band,
        confidence=winner.confidence,
        winning_watchlist_id=winner.watchlist_id,
        matching_watchlist_ids=unique_watchlists,
    )


class RelevanceService:
    """Pure deterministic matcher for one WatchlistVersion and SignalSnapshot."""

    version = MATCHER_VERSION

    def evaluate_one(
        self,
        watchlist: WatchlistVersion,
        target: RelevanceTarget,
    ) -> RelevanceOutcome:
        fields = _fields(target)
        exclusions = _term_hits(watchlist.exclude_terms, fields)
        if exclusions:
            exclusion_reasons = tuple(
                MatchReason(
                    reason_type=REASON_EXCLUSION,
                    value=term,
                    field=field,
                    contribution=0.0,
                    polarity=POLARITY_NEGATIVE,
                )
                for term, field in exclusions
            )
            return RelevanceOutcome(
                score=0.0,
                band=BAND_MINIMAL,
                confidence=CONFIDENCE_HIGH,
                decision=DECISION_EXCLUDED,
                components=_empty_components(watchlist),
                reasons=exclusion_reasons,
            )

        exact_hits = _term_hits(
            watchlist.include_terms,
            {
                "signal.label": fields["signal.label"],
                "signal.key": fields["signal.key"],
            },
        )
        related_hits = _term_hits(
            watchlist.include_terms,
            {"signal.related_terms": fields["signal.related_terms"]},
        )
        context_hits = _term_hits(
            watchlist.include_terms,
            {"signal.context": fields["signal.context"]},
        )
        entity_hits = _term_hits(watchlist.entities, fields) if watchlist.entities else []
        domain_hits = _term_hits(watchlist.domains, fields) if watchlist.domains else []

        include_hits = {term for term, _field in exact_hits + related_hits + context_hits}
        if watchlist.match_mode == MODE_ALL:
            include_satisfied = len(include_hits) == len(watchlist.include_terms)
        else:
            include_satisfied = bool(include_hits)

        values: dict[str, tuple[float | None, str, str]] = {
            COMPONENT_EXACT: (
                _fraction(exact_hits, watchlist.include_terms),
                STATUS_AVAILABLE,
                _basis(exact_hits),
            ),
            COMPONENT_RELATED: (
                _fraction(related_hits, watchlist.include_terms),
                STATUS_AVAILABLE,
                _basis(related_hits),
            ),
            COMPONENT_CONTEXT: (
                _fraction(context_hits, watchlist.include_terms),
                STATUS_AVAILABLE if target.context else STATUS_INSUFFICIENT_DATA,
                _basis(context_hits) if target.context else "no context available",
            ),
            COMPONENT_ENTITY: (
                _fraction(entity_hits, watchlist.entities) if watchlist.entities else None,
                STATUS_AVAILABLE if watchlist.entities else STATUS_NOT_APPLICABLE,
                _basis(entity_hits) if watchlist.entities else "no entities configured",
            ),
            COMPONENT_DOMAIN: (
                _fraction(domain_hits, watchlist.domains) if watchlist.domains else None,
                STATUS_AVAILABLE if watchlist.domains else STATUS_NOT_APPLICABLE,
                _basis(domain_hits) if watchlist.domains else "no domains configured",
            ),
        }

        measured_weight = 0.0
        raw = 0.0
        for name, (value, status, _basis_text) in values.items():
            if status == STATUS_AVAILABLE and value is not None:
                measured_weight += WEIGHTS[name]
                raw += WEIGHTS[name] * float(value)
        score = round(raw / measured_weight * 100.0, 2) if measured_weight else 0.0

        grouped_hits = (
            (REASON_EXACT_TERM, exact_hits),
            (REASON_RELATED_TERM, related_hits),
            (REASON_CONTEXT, context_hits),
            (REASON_ENTITY, entity_hits),
            (REASON_DOMAIN, domain_hits),
        )
        reasons: list[MatchReason] = []
        seen: set[tuple[str, str]] = set()
        for reason_type, hits in grouped_hits:
            component_name = _component_for_reason(reason_type)
            component_value = values[component_name][0]
            component_total = 0.0
            if component_value is not None and measured_weight:
                component_total = (
                    WEIGHTS[component_name] * float(component_value) / measured_weight * 100.0
                )
            per_reason = component_total / max(1, len(hits))
            for term, field in hits:
                key = (reason_type, term)
                if key in seen:
                    continue
                seen.add(key)
                reasons.append(
                    MatchReason(
                        reason_type=reason_type,
                        value=term,
                        field=field,
                        contribution=round(per_reason, 2),
                    )
                )

        generic_only = bool(include_hits)
        for term in include_hits:
            if not _is_generic(term):
                generic_only = False
                break
        if entity_hits or domain_hits:
            generic_only = False
        if generic_only:
            score = min(score, GENERIC_ONLY_CAP)

        if not include_satisfied:
            decision = DECISION_NO_MATCH
        elif score >= POSITIVE_THRESHOLD:
            decision = DECISION_MATCHED
        else:
            decision = DECISION_NO_MATCH

        confidence = _confidence(reasons, decision)
        components: list[RelevanceComponent] = []
        for name, row in values.items():
            value, status, basis_text = row
            contribution = 0.0
            if value is not None and measured_weight:
                contribution = round(
                    WEIGHTS[name] * float(value) / measured_weight * 100.0,
                    2,
                )
            components.append(
                RelevanceComponent(
                    name=name,
                    weight=WEIGHTS[name],
                    value=value,
                    status=status,
                    contribution=contribution,
                    basis=basis_text,
                )
            )
        return RelevanceOutcome(
            score=score,
            band=relevance_band(score),
            confidence=confidence,
            decision=decision,
            components=tuple(components),
            reasons=tuple(reasons),
        )

    def evaluate_batch(
        self,
        watchlist: WatchlistVersion,
        targets: Sequence[RelevanceTarget],
    ) -> list[RelevanceOutcome]:
        return [self.evaluate_one(watchlist, target) for target in targets]

    @staticmethod
    def aggregate_radar(
        signal_id: str,
        evaluations: Iterable[RelevanceEvaluation],
    ) -> RadarSignalRelevance | None:
        return aggregate_radar(signal_id, evaluations)


def _component_for_reason(reason_type: str) -> str:
    mapping = {
        REASON_EXACT_TERM: COMPONENT_EXACT,
        REASON_RELATED_TERM: COMPONENT_RELATED,
        REASON_CONTEXT: COMPONENT_CONTEXT,
        REASON_ENTITY: COMPONENT_ENTITY,
        REASON_DOMAIN: COMPONENT_DOMAIN,
    }
    return mapping[reason_type]


def _empty_components(
    watchlist: WatchlistVersion,
) -> tuple[RelevanceComponent, ...]:
    rows: list[RelevanceComponent] = []
    for name, weight in WEIGHTS.items():
        applicable = True
        if name == COMPONENT_ENTITY and not watchlist.entities:
            applicable = False
        if name == COMPONENT_DOMAIN and not watchlist.domains:
            applicable = False
        rows.append(
            RelevanceComponent(
                name=name,
                weight=weight,
                value=0.0 if applicable else None,
                status=STATUS_AVAILABLE if applicable else STATUS_NOT_APPLICABLE,
                contribution=0.0,
                basis="excluded before positive scoring" if applicable else "not configured",
            )
        )
    return tuple(rows)


def _confidence(reasons: Sequence[MatchReason], decision: str) -> str:
    if decision == DECISION_EXCLUDED:
        return CONFIDENCE_HIGH
    if decision != DECISION_MATCHED:
        return CONFIDENCE_LOW
    reason_types = {reason.reason_type for reason in reasons}
    if len(reason_types) >= 2:
        return CONFIDENCE_HIGH
    for reason in reasons:
        if reason.reason_type in (REASON_EXACT_TERM, REASON_ENTITY):
            return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _is_generic(term: str) -> bool:
    words = normalize(term).split()
    return bool(words) and all(word in GENERIC_TERMS for word in words)


def _fraction(
    hits: Sequence[tuple[str, str]],
    configured: Sequence[str],
) -> float:
    if not configured:
        return 0.0
    unique_terms = {term for term, _field in hits}
    return min(1.0, len(unique_terms) / len(configured))


def _basis(hits: Sequence[tuple[str, str]]) -> str:
    if not hits:
        return "no match"
    return ", ".join(f"{term!r} in {field}" for term, field in hits)


def _term_hits(
    terms: Sequence[str],
    fields: dict[str, str],
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for term in terms:
        for field, haystack in fields.items():
            if contains_term(haystack, term):
                found.append((term, field))
                break
    return found


def _fields(target: RelevanceTarget) -> dict[str, str]:
    return {
        "signal.label": _haystack([target.label]),
        "signal.key": _haystack([target.key]),
        "signal.related_terms": _haystack(target.related_terms),
        "signal.context": _haystack(target.context),
    }


def normalize(text: str) -> str:
    characters: list[str] = []
    for character in text:
        characters.append(character.lower() if character.isalnum() else " ")
    return " ".join("".join(characters).split())


def _haystack(values: Iterable[str]) -> str:
    parts: list[str] = []
    for value in values:
        normalized = normalize(value)
        if normalized:
            parts.append(f" {normalized} ")
    return " | ".join(parts)


def contains_term(haystack: str, term: str) -> bool:
    needle = normalize(term)
    return bool(needle) and f" {needle} " in haystack


DEFAULT_RELEVANCE_SERVICE = RelevanceService()
