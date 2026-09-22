"""Deterministic, versioned evaluation of a candidate signal.

This is the only module that turns evidence into a SignalScore. Three rules govern
everything below:

1. **Deterministic.** Same evidence set + same ``SIGNAL_EVALUATION_VERSION`` => same
   numbers, on any machine, in any order. No randomness, no wall-clock reads, no
   iteration over unordered sets where order could leak into a result.
2. **Never fake a metric.** A component whose inputs do not exist is reported
   ``INSUFFICIENT_DATA`` and its weight is removed from the denominator. It is not
   quietly scored 0 (which would look like "measured, and bad") and not quietly
   scored 0.5 (which would invent a middling fact). An RSS feed carrying no vote
   counts is *unknown* reach, not *low* reach.
3. **Score, confidence and relevance are three different questions.** The SignalScore
   says how strong the signal is. Confidence says how much the evidence can support
   any claim at all. Relevance says how well it matches the user's niche. Collapsing
   them is what makes trend scores unfalsifiable, so they stay separate fields.

The score is a weighted sum over the components that *were* measured, renormalised by
the measured weight::

    score = 100 * sum(value_i * weight_i) / sum(weight_i)    over measured components

Components (each in [0, 1]):

Recency
    Mean of ``0.5 ** (age_hours / 48)`` over the evidence, by event time. Always
    measurable: an observation without a parseable date never becomes evidence.
Velocity
    Is the signal *accelerating*? With stored history, the growth in distinct stories
    per day since the previous snapshot, against a reference of one new story a day.
    Without history, an in-run arrival-skew proxy: how far the evidence bunches into
    the recent half of its own time window. INSUFFICIENT_DATA when the evidence is
    too small or too narrow in time for either to mean anything.
Novelty
    Is this actually new, or merely present? Two independent ways of being un-novel
    are combined by taking the worse:
      * *lexical saturation* - a topic term that already appears across a large share
        of everything collected is background noise, not news. This is the
        "new-but-not-novel" case: a freshly formed cluster about a term the corpus
        is saturated with.
      * *prior sightings* - with history, novelty halves for each previous run that
        already reported this signal.
Corroboration
    Independent sources: the largest number of source adapters that can each be
    paired with a *different* underlying story. 1 -> 0.0, 2 -> 0.5, 3+ -> 1.0. One
    link mirrored through two channels is one source, not two.
SourceDiversity
    Distinct publishers (feed, subreddit, repo owner, HN): ``min(1, (n - 1) / 3)``.
    Deliberately distinct from corroboration: three subreddits are three publishers
    but one source type.
EngagementStrength
    Mean of the top three within-source engagement percentiles. INSUFFICIENT_DATA
    when no observation in the set carries metrics at all.
Persistence
    Is it lasting? Distinct calendar days covered by the evidence, ``min(1, (d-1)/3)``,
    raised by the number of consecutive runs that already reported the signal when
    history is available. A one-hour spike scores 0 here; a week-long conversation
    scores 1.

Counterevidence is always explicit and always points at the observations that caused
it, so "this looks strong" and "here is why it might not be" arrive together.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .observation import Observation
from .signal import (
    INSUFFICIENT_DATA,
    MEASURED,
    STATE_DORMANT,
    STATE_EMERGING,
    STATE_INSUFFICIENT_DATA,
    STATE_REACTIVATED,
    STATE_SUSTAINED,
    CandidateSignal,
    ComponentScore,
    Counterevidence,
    EvidenceSetVersion,
    Signal,
    SignalBrief,
    SignalEvaluation,
    SignalSnapshot,
    sort_snapshots,
)
from .text import CRITICAL_RE, feature_text, phrase_in, tokenize
from .versions import SIGNAL_EVALUATION_VERSION

# ----------------------------------------------------------------------------- tuning
# Every constant here is part of SIGNAL_EVALUATION_VERSION. Changing one changes
# published numbers, so it must come with a version bump.

HALF_LIFE_HOURS = 48.0

#: Velocity: one new distinct story per day is a full-marks arrival rate.
VELOCITY_REFERENCE_STORIES_PER_DAY = 1.0
#: Below this many stories, or this narrow a time window, arrival skew is noise.
VELOCITY_MIN_STORIES = 3
VELOCITY_MIN_SPAN_HOURS = 6.0
#: Guards against a division blow-up when two snapshots are nearly simultaneous.
VELOCITY_MIN_ELAPSED_HOURS = 1.0

#: Novelty: a term carried by this share of the whole run's corpus is background noise.
NOVELTY_SATURATION_REFERENCE = 0.25
#: Novelty halves for each previous run that already reported the signal.
NOVELTY_HISTORY_DECAY = 0.5

#: Persistence: this many distinct calendar days of evidence scores full marks.
PERSISTENCE_FULL_DAYS = 4
#: ... or this many consecutive runs reporting the signal.
PERSISTENCE_FULL_RUNS = 3

#: Evidence older than this makes the signal dormant rather than emerging.
DORMANT_AGE_HOURS = 14 * 24.0
#: A gap longer than this between stored snapshots counts as a reactivation.
REACTIVATION_GAP_HOURS = 14 * 24.0
#: Evidence older than a week is called out as counterevidence.
STALE_AGE_HOURS = 7 * 24.0

#: Below this share of measured weight, the evaluation refuses to claim a score.
MIN_MEASURED_WEIGHT = 0.5
#: High confidence additionally requires this share of the components to be measured.
HIGH_CONFIDENCE_MEASURED_WEIGHT = 0.75

# Counterevidence codes.
CE_SINGLE_SOURCE = "single_source"
CE_SYNDICATED_ECHO = "syndicated_echo"
CE_CONTRADICTED = "contradicted"
CE_NO_ENGAGEMENT_METRICS = "no_engagement_metrics"
CE_STALE_EVIDENCE = "stale_evidence"
CE_SMALL_SAMPLE = "small_sample"
CE_INCOHESIVE_EVIDENCE = "incohesive_evidence"
CE_PROMPT_INJECTION = "prompt_injection_attempt"


@dataclass(frozen=True)
class SignalWeights:
    """Component weights. Must sum to 1.0; see :func:`check_weights`."""

    recency: float = 0.20
    velocity: float = 0.15
    novelty: float = 0.10
    corroboration: float = 0.20
    source_diversity: float = 0.10
    engagement_strength: float = 0.15
    persistence: float = 0.10

    def as_dict(self) -> dict[str, float]:
        return {
            "recency": self.recency,
            "velocity": self.velocity,
            "novelty": self.novelty,
            "corroboration": self.corroboration,
            "source_diversity": self.source_diversity,
            "engagement_strength": self.engagement_strength,
            "persistence": self.persistence,
        }


SIGNAL_WEIGHTS = SignalWeights()
COMPONENT_ORDER = tuple(SIGNAL_WEIGHTS.as_dict())


def check_weights(weights: SignalWeights = SIGNAL_WEIGHTS) -> None:
    total = sum(weights.as_dict().values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"signal weights must sum to 1.0, got {total}")


# ---------------------------------------------------------------------------- helpers


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def age_hours(observation: Observation, now: datetime) -> float:
    """Age by *event* time. Future-dated items count as age 0, never negative."""
    return max(0.0, (now - observation.event_time).total_seconds() / 3600.0)


def _measured(name: str, weight: float, value: float, basis: str) -> ComponentScore:
    return ComponentScore(
        name=name, weight=weight, value=round(_clamp01(value), 3), status=MEASURED, basis=basis
    )


def _unknown(name: str, weight: float, basis: str) -> ComponentScore:
    return ComponentScore(
        name=name, weight=weight, value=None, status=INSUFFICIENT_DATA, basis=basis
    )


def independent_source_count(observations: Sequence[Observation]) -> int:
    """Sources that can each be paired with a different underlying story.

    A maximum bipartite matching over (source -> story key), computed with
    deterministic augmenting paths so the answer never depends on set ordering.
    """
    keys_by_source: dict[str, list[str]] = defaultdict(list)
    for obs in observations:
        if obs.story_key not in keys_by_source[obs.source]:
            keys_by_source[obs.source].append(obs.story_key)
    owner: dict[str, str] = {}  # story key -> source that claimed it

    def augment(source: str, seen: set[str]) -> bool:
        for key in keys_by_source[source]:
            if key in seen:
                continue
            seen.add(key)
            if key not in owner or augment(owner[key], seen):
                owner[key] = source
                return True
        return False

    for source in sorted(keys_by_source):
        augment(source, set())
    return len(owner)


# ------------------------------------------------------------------------- components


def recency_component(
    observations: Sequence[Observation], now: datetime, weight: float
) -> ComponentScore:
    if not observations:
        return _unknown("recency", weight, "no evidence")
    ages = [age_hours(o, now) for o in observations]
    value = sum(0.5 ** (a / HALF_LIFE_HOURS) for a in ages) / len(ages)
    return _measured(
        "recency",
        weight,
        value,
        f"{HALF_LIFE_HOURS:.0f} h half-life over {len(ages)} item(s); "
        f"newest {min(ages):.0f} h, oldest {max(ages):.0f} h",
    )


def velocity_component(
    observations: Sequence[Observation],
    now: datetime,
    weight: float,
    history: Sequence[SignalSnapshot] = (),
) -> ComponentScore:
    """Cross-run arrival rate when history exists; in-run arrival skew otherwise."""
    stories = {o.story_key for o in observations}
    previous = sort_snapshots(history)
    if previous:
        last = previous[-1]
        elapsed = max(VELOCITY_MIN_ELAPSED_HOURS, (now - last.captured_at).total_seconds() / 3600.0)
        gained = len(stories) - last.story_count
        per_day = (gained / elapsed) * 24.0
        value = _clamp01(per_day / VELOCITY_REFERENCE_STORIES_PER_DAY)
        return _measured(
            "velocity",
            weight,
            value,
            f"{gained:+d} distinct story/stories in {elapsed:.0f} h since the previous "
            f"snapshot ({per_day:+.2f}/day against a reference of "
            f"{VELOCITY_REFERENCE_STORIES_PER_DAY:.0f}/day)",
        )

    ages = sorted(age_hours(o, now) for o in observations)
    span = (ages[-1] - ages[0]) if ages else 0.0
    if len(stories) < VELOCITY_MIN_STORIES or span < VELOCITY_MIN_SPAN_HOURS:
        return _unknown(
            "velocity",
            weight,
            f"no stored history, and {len(stories)} story/stories over a {span:.0f} h window "
            f"is below the {VELOCITY_MIN_STORIES}-story / {VELOCITY_MIN_SPAN_HOURS:.0f} h "
            "floor for an in-run arrival estimate",
        )
    midpoint = ages[0] + span / 2.0
    recent = sum(1 for a in ages if a <= midpoint)
    share = recent / len(ages)
    value = _clamp01((share - 0.5) * 2.0)
    return _measured(
        "velocity",
        weight,
        value,
        f"no stored history; {recent}/{len(ages)} item(s) fall in the recent half of a "
        f"{span:.0f} h window (a flat 50% arrival rate scores 0)",
    )


def novelty_component(
    observations: Sequence[Observation],
    candidate_key: str,
    corpus: Sequence[Observation],
    weight: float,
    history: Sequence[SignalSnapshot] = (),
) -> ComponentScore:
    """Lexical saturation, made worse by every previous run that already saw this signal."""
    if not corpus:
        return _unknown("novelty", weight, "no corpus to measure saturation against")
    hits = 0
    for obs in corpus:
        tokens = tokenize(feature_text(obs.source, obs.title, obs.excerpt))
        if phrase_in(candidate_key, tokens):
            hits += 1
    saturation = hits / len(corpus)
    lexical = _clamp01(1.0 - saturation / NOVELTY_SATURATION_REFERENCE)
    basis = (
        f"the topic term appears in {hits}/{len(corpus)} collected item(s) "
        f"({saturation:.0%}); saturation at or above "
        f"{NOVELTY_SATURATION_REFERENCE:.0%} scores 0"
    )
    prior_runs = len(history)
    if prior_runs:
        decayed = NOVELTY_HISTORY_DECAY**prior_runs
        basis += f"; halved {prior_runs} time(s) for previous run(s) that already reported it"
        return _measured("novelty", weight, min(lexical, decayed), basis)
    return _measured("novelty", weight, lexical, basis)


def corroboration_component(observations: Sequence[Observation], weight: float) -> ComponentScore:
    n = independent_source_count(observations)
    value = 0.0 if n <= 1 else 0.5 if n == 2 else 1.0
    return _measured(
        "corroboration",
        weight,
        value,
        f"{n} independent source(s), i.e. source adapters that each link a different "
        f"underlying story",
    )


def source_diversity_component(
    observations: Sequence[Observation], weight: float
) -> ComponentScore:
    publishers = {o.publisher for o in observations}
    value = min(1.0, max(0, len(publishers) - 1) / 3)
    return _measured(
        "source_diversity",
        weight,
        value,
        f"{len(publishers)} distinct publisher(s) (feed, subreddit, repo owner or site)",
    )


def engagement_strength_component(
    observations: Sequence[Observation], percentiles: dict[str, float], weight: float
) -> ComponentScore:
    """Top-3 within-source percentiles, or INSUFFICIENT_DATA. Never a stand-in number."""
    values = sorted(
        (
            percentiles[o.evidence_item_id]
            for o in observations
            if o.evidence_item_id in percentiles
        ),
        reverse=True,
    )
    if not values:
        sources = ", ".join(sorted({o.source for o in observations})) or "none"
        return _unknown(
            "engagement_strength",
            weight,
            f"no observation in this evidence set carries engagement metrics "
            f"(source(s): {sources}); reach is unknown, not low",
        )
    top = values[:3]
    return _measured(
        "engagement_strength",
        weight,
        sum(top) / len(top),
        f"mean of the top {len(top)} within-source engagement percentile(s) over "
        f"{len(values)} measurable item(s) this run",
    )


def persistence_component(
    observations: Sequence[Observation],
    weight: float,
    history: Sequence[SignalSnapshot] = (),
) -> ComponentScore:
    days = {o.event_time.date() for o in observations}
    by_days = min(1.0, max(0, len(days) - 1) / (PERSISTENCE_FULL_DAYS - 1))
    basis = f"evidence spans {len(days)} distinct day(s)"
    runs = len(sort_snapshots(history))
    if runs:
        by_runs = min(1.0, runs / PERSISTENCE_FULL_RUNS)
        basis += f"; reported in {runs} previous run(s)"
        return _measured("persistence", weight, max(by_days, by_runs), basis)
    return _measured("persistence", weight, by_days, basis)


# -------------------------------------------------------------------- counterevidence


def collect_counterevidence(
    candidate: CandidateSignal,
    observations: Sequence[Observation],
    now: datetime,
    engagement: ComponentScore,
) -> tuple[Counterevidence, ...]:
    """Reasons to trust the signal less, each tied to the evidence that caused it."""
    out: list[Counterevidence] = []
    stories = {o.story_key for o in observations}
    sources = independent_source_count(observations)

    if sources <= 1:
        names = ", ".join(sorted({o.source for o in observations})) or "none"
        out.append(
            Counterevidence(
                CE_SINGLE_SOURCE,
                f"Only {sources} independent source ({names}). Attention inside one "
                f"community is not the same as a trend.",
                tuple(o.observation_id for o in observations),
            )
        )
    echoes = [
        o for o in observations if sum(1 for x in observations if x.story_key == o.story_key) > 1
    ]
    if echoes:
        out.append(
            Counterevidence(
                CE_SYNDICATED_ECHO,
                f"{len(observations) - len(stories)} observation(s) repeat a story already "
                f"carried by another channel. Repeats are counted once, but they inflate "
                f"how busy the topic looks.",
                tuple(o.observation_id for o in echoes),
            )
        )
    if len(stories) <= 2:
        out.append(
            Counterevidence(
                CE_SMALL_SAMPLE,
                f"Small sample: {len(stories)} distinct story/stories. Early signal, not a trend.",
                tuple(o.observation_id for o in observations),
            )
        )
    critical = [o for o in observations if CRITICAL_RE.search(o.title)]
    if critical:
        out.append(
            Counterevidence(
                CE_CONTRADICTED,
                f"{len(critical)} item(s) are critical or cautionary about this topic "
                f'(e.g. "{critical[0].title}"). The signal includes pushback, not only uptake.',
                tuple(o.observation_id for o in critical),
            )
        )
    if engagement.status == INSUFFICIENT_DATA:
        out.append(
            Counterevidence(
                CE_NO_ENGAGEMENT_METRICS,
                "No source in this evidence set publishes engagement metrics, so reach is "
                "unknown. The score was computed without an engagement component.",
                tuple(o.observation_id for o in observations),
            )
        )
    stale = [o for o in observations if age_hours(o, now) > STALE_AGE_HOURS]
    if stale:
        out.append(
            Counterevidence(
                CE_STALE_EVIDENCE,
                f"{len(stale)} item(s) are over a week old; part of this signal is not new.",
                tuple(o.observation_id for o in stale),
            )
        )
    if not candidate.cohesive:
        out.append(
            Counterevidence(
                CE_INCOHESIVE_EVIDENCE,
                "The evidence agrees on little more than a single word, so the grouping "
                "itself may be wrong.",
                tuple(o.observation_id for o in observations),
            )
        )
    flagged = [o for o in observations if o.flags]
    if flagged:
        out.append(
            Counterevidence(
                CE_PROMPT_INJECTION,
                f"{len(flagged)} item(s) contain text shaped like instructions to an AI "
                f"system. Held as inert data; nothing was executed or followed.",
                tuple(o.observation_id for o in flagged),
            )
        )
    return tuple(out)


# ------------------------------------------------------------------- confidence, state


def confidence_label(
    observations: Sequence[Observation], *, cohesive: bool, measured_weight: float
) -> str:
    """How much the evidence can support *any* claim. Independent of the score."""
    sources = independent_source_count(observations)
    stories = len({o.story_key for o in observations})
    publishers = len({o.publisher for o in observations})
    if (
        sources >= 3
        and stories >= 4
        and publishers >= 3
        and cohesive
        and measured_weight >= HIGH_CONFIDENCE_MEASURED_WEIGHT
    ):
        return "high"
    if sources >= 2 or stories >= 3:
        return "medium"
    return "low"


def signal_state(
    observations: Sequence[Observation],
    now: datetime,
    *,
    measured_weight: float,
    persistence: ComponentScore,
    history: Sequence[SignalSnapshot] = (),
) -> str:
    """Where the signal sits in its life cycle. Checked most-specific first."""
    if measured_weight < MIN_MEASURED_WEIGHT:
        return STATE_INSUFFICIENT_DATA
    newest = min((age_hours(o, now) for o in observations), default=float("inf"))
    if newest > DORMANT_AGE_HOURS:
        return STATE_DORMANT
    previous = sort_snapshots(history)
    if previous:
        gap = (now - previous[-1].captured_at).total_seconds() / 3600.0
        if gap > REACTIVATION_GAP_HOURS or previous[-1].state == STATE_DORMANT:
            return STATE_REACTIVATED
        return STATE_SUSTAINED
    if persistence.value is not None and persistence.value >= 0.5:
        return STATE_SUSTAINED
    return STATE_EMERGING


# ------------------------------------------------------------------------- evaluation


def evaluate(
    candidate: CandidateSignal,
    *,
    now: datetime,
    corpus: Sequence[Observation],
    percentiles: dict[str, float],
    relevance: float,
    history: Sequence[SignalSnapshot] = (),
    weights: SignalWeights = SIGNAL_WEIGHTS,
) -> SignalEvaluation:
    """Evaluate one candidate signal. Pure: same inputs, same output, always."""
    check_weights(weights)
    observations = list(candidate.observations)
    w = weights

    components = (
        recency_component(observations, now, w.recency),
        velocity_component(observations, now, w.velocity, history),
        novelty_component(observations, candidate.canonical_key, corpus, w.novelty, history),
        corroboration_component(observations, w.corroboration),
        source_diversity_component(observations, w.source_diversity),
        engagement_strength_component(observations, percentiles, w.engagement_strength),
        persistence_component(observations, w.persistence, history),
    )

    measured_weight = sum(c.weight for c in components if c.status == MEASURED)
    earned = sum(c.contribution for c in components)
    score = round(100.0 * earned / measured_weight, 1) if measured_weight > 0 else 0.0

    engagement = next(c for c in components if c.name == "engagement_strength")
    counterevidence = collect_counterevidence(candidate, observations, now, engagement)
    confidence = confidence_label(
        observations, cohesive=candidate.cohesive, measured_weight=measured_weight
    )
    persistence = next(c for c in components if c.name == "persistence")
    state = signal_state(
        observations,
        now,
        measured_weight=measured_weight,
        persistence=persistence,
        history=history,
    )

    notes: list[str] = []
    unmeasured = [c.name for c in components if c.status == INSUFFICIENT_DATA]
    if unmeasured:
        notes.append(
            "Score computed over "
            f"{measured_weight:.0%} of the component weight; "
            f"{', '.join(unmeasured)} had no data and were excluded rather than assumed."
        )
    if state == STATE_INSUFFICIENT_DATA:
        notes.append(
            f"Too little of the evidence could be measured (under "
            f"{MIN_MEASURED_WEIGHT:.0%} of component weight) to claim a signal strength."
        )

    return SignalEvaluation(
        evaluation_version=SIGNAL_EVALUATION_VERSION,
        evaluated_at=now,
        score=score,
        components=components,
        measured_weight=measured_weight,
        confidence=confidence,
        relevance=round(relevance, 3),
        state=state,
        counterevidence=counterevidence,
        notes=tuple(notes),
    )


def build_signal_brief(
    candidate: CandidateSignal,
    *,
    now: datetime,
    corpus: Sequence[Observation],
    percentiles: dict[str, float],
    relevance: float,
    history: Sequence[SignalSnapshot] = (),
    weights: SignalWeights = SIGNAL_WEIGHTS,
) -> SignalBrief:
    """Promote a candidate, evaluate it, and package the result with its audit trail."""
    ordered = sort_snapshots(history)
    first_seen = ordered[0].captured_at if ordered else now
    signal = Signal.promote(candidate, now=now, first_seen_at=first_seen)
    evidence_set = EvidenceSetVersion.of(candidate.observations, created_at=now)
    evaluation = evaluate(
        candidate,
        now=now,
        corpus=corpus,
        percentiles=percentiles,
        relevance=relevance,
        history=history,
        weights=weights,
    )
    snapshot = SignalSnapshot.of(
        signal,
        evaluation,
        evidence_set,
        source_count=len({o.source for o in candidate.observations}),
    )
    return SignalBrief(
        signal=signal,
        evaluation=evaluation,
        evidence_set=evidence_set,
        observations=candidate.observations,
        snapshot=snapshot,
    )


def dormancy_cutoff(now: datetime) -> datetime:
    """The event time at or before which a signal counts as dormant."""
    return now - timedelta(hours=DORMANT_AGE_HOURS)
