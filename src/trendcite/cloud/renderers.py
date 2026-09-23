"""Deterministic alert and digest renderers. No LLM, no network, no clock.

The same alert renders to the same bytes on every machine and every run, which is
what makes a rendered payload safe to store on the Alert row and compare in a test.
A renderer that phoned an LLM would make the stored body unreproducible and the
delivery pipeline untestable offline, so it does not.

Every line is traceable to a stored field. Nothing here invents a number, softens a
decline, or adds an adjective the evaluation did not earn.
"""

from __future__ import annotations

from collections.abc import Sequence

from .domain.alerts import AlertCandidate, AlertPayload, MaterialEvent
from .domain.digests import DigestItem, DigestPayload
from .versions import ALERT_RENDERER_VERSION, DIGEST_RENDERER_VERSION

#: Subjects are bounded so no adapter has to truncate one and none can overflow a
#: provider's header limit in a way that differs between providers.
MAX_SUBJECT = 120


def _subject(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= MAX_SUBJECT:
        return collapsed
    return collapsed[: MAX_SUBJECT - 1].rstrip() + "…"


def _event_line(event: MaterialEvent) -> str:
    return f"  - [{event.level}/{event.direction}] {event.detail}"


def render_alert(candidate: AlertCandidate, *, watchlist_name: str = "") -> AlertPayload:
    """Render one qualified candidate as ``alert-renderer-v1``."""
    scope = watchlist_name or candidate.watchlist_id
    subject = _subject(f"[{candidate.materiality}] {candidate.label}")
    lines = [
        subject,
        "",
        f"Watchlist: {scope}",
        f"Signal: {candidate.label}",
        f"Signal id: {candidate.signal_id}",
        f"Snapshot: {candidate.snapshot_id}",
        "",
        f"Signal score: {candidate.signal_score:.1f}/100",
        f"Relevance: {candidate.relevance_score:.1f}/100",
        f"Materiality: {candidate.materiality} ({candidate.materiality_version})",
        f"Observed at: {candidate.observed_at.isoformat()}",
        "",
        "Why now:",
    ]
    lines.extend(_event_line(event) for event in candidate.evaluation.events)
    if candidate.evaluation.coverage_degraded:
        # Stated, never hidden: an alert raised under partial coverage is a claim
        # about what we could see, and the reader is entitled to know that.
        lines.extend(
            [
                "",
                f"Source coverage: {candidate.evaluation.coverage_state}.",
                "Declines are withheld under incomplete coverage.",
            ]
        )
        if candidate.evaluation.withheld_declines:
            withheld = ", ".join(candidate.evaluation.withheld_declines)
            lines.append(f"Withheld decline signals: {withheld}")
    return AlertPayload(
        subject=subject,
        body="\n".join(lines),
        renderer_version=ALERT_RENDERER_VERSION,
    )


def render_digest(
    items: Sequence[DigestItem],
    *,
    radar_name: str,
    digest_date: str,
) -> DigestPayload:
    """Render one day's ranked items as ``digest-renderer-v1``."""
    if not items:
        raise ValueError("an empty digest is never rendered")
    count = len(items)
    noun = "signal" if count == 1 else "signals"
    subject = _subject(f"{radar_name} daily digest {digest_date}: {count} {noun}")
    lines = [subject, "", f"Radar: {radar_name}", f"Window: {digest_date} (UTC)", ""]
    for item in items:
        lines.append(f"{item.rank}. {item.label}")
        lines.append(
            f"   materiality={item.materiality} "
            f"relevance={item.relevance_score:.1f} "
            f"signal={item.signal_score:.1f}"
        )
        lines.append(f"   signal_id={item.signal_id} snapshot={item.snapshot_id}")
    return DigestPayload(
        subject=subject,
        body="\n".join(lines),
        renderer_version=DIGEST_RENDERER_VERSION,
    )
