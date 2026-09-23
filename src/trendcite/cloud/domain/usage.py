"""UsageEvent: what a workspace consumed, counted exactly once.

Metering is the one place where "write it twice" is not a tidiness problem but a
correctness problem: a retried run that meters twice overstates what the tenant did.
So a usage event carries a ``dedupe_key`` describing the *logical* thing consumed,
and the database holds a uniqueness constraint on (workspace, dedupe_key). Writing
the same event again is a no-op, not an increment.

The keys are derived from the pinned run identity, so retrying a failed run produces
exactly the same keys and therefore exactly the same totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .. import ids
from ..errors import ValidationError
from ._base import iso, require_aware, require_text

#: One radar execution that reached a terminal, successful state.
USAGE_RADAR_RUN = "radar_run"
#: Signals evaluated and persisted by a run.
USAGE_SIGNAL_EVALUATED = "signal_evaluated"
#: Signals the run matched onto the radar.
USAGE_MATCH_RECORDED = "match_recorded"

# Alerting and delivery observability. These are metered the same way runs are --
# keyed by the logical entity rather than by the attempt -- so replaying a run, a
# delivery retry or a digest rebuild reports the same totals it reported the first
# time. Suppressions are counted as deliberately as sends: a workspace whose alerts
# are all being suppressed is a fact worth being able to see.
USAGE_ALERT_CANDIDATE = "alert_candidate"
USAGE_ALERT_CREATED = "alert_created"
USAGE_ALERT_SUPPRESSED = "alert_suppressed"
USAGE_DIGEST_CREATED = "digest_created"
USAGE_DELIVERY_ATTEMPT = "delivery_attempt"
USAGE_DELIVERY_SUCCESS = "delivery_success"
USAGE_DELIVERY_FAILURE = "delivery_failure"

#: One scheduled execution, keyed by the tick rather than by the attempt. A tick that
#: failed and was retried is one piece of scheduled work, not two, so an unreliable
#: source cannot inflate what a tenant is shown as having consumed. The radar run this
#: tick drives meters itself separately under ``radar_run``, and deliberately so: "the
#: scheduler asked for this" and "a run happened" are different claims, and a tick that
#: never reached a run should still be visible.
USAGE_SCHEDULED_TICK = "scheduled_tick"

USAGE_KINDS = (
    USAGE_RADAR_RUN,
    USAGE_SIGNAL_EVALUATED,
    USAGE_MATCH_RECORDED,
    USAGE_ALERT_CANDIDATE,
    USAGE_ALERT_CREATED,
    USAGE_ALERT_SUPPRESSED,
    USAGE_DIGEST_CREATED,
    USAGE_DELIVERY_ATTEMPT,
    USAGE_DELIVERY_SUCCESS,
    USAGE_DELIVERY_FAILURE,
    USAGE_SCHEDULED_TICK,
)


def run_dedupe_key(kind: str, run_id: str) -> str:
    """The logical identity of a run-scoped usage event.

    Derived from the run, not from the attempt: attempt 2 of a failed run meters the
    same thing attempt 1 would have.
    """
    if kind not in USAGE_KINDS:
        raise ValidationError(f"usage kind must be one of {', '.join(USAGE_KINDS)}")
    return f"{kind}:{run_id}"


def entity_dedupe_key(kind: str, entity_id: str) -> str:
    """The logical identity of an entity-scoped usage event.

    Alerting entities already have content-addressed ids, so keying the meter off the
    entity means a re-decided candidate, a re-sent alert or a rebuilt digest meters
    once. A delivery *attempt* is keyed by the attempt, because attempt 2 genuinely is
    a second unit of work.
    """
    if kind not in USAGE_KINDS:
        raise ValidationError(f"usage kind must be one of {', '.join(USAGE_KINDS)}")
    if not entity_id:
        raise ValidationError("entity_id must not be blank")
    return f"{kind}:{entity_id}"


@dataclass(frozen=True)
class UsageEvent:
    """One metered, de-duplicated unit of tenant consumption."""

    event_id: str
    workspace_id: str
    kind: str
    quantity: int
    occurred_at: datetime
    run_id: str
    dedupe_key: str

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        kind: str,
        quantity: int,
        occurred_at: datetime,
        run_id: str = "",
        dedupe_key: str | None = None,
    ) -> UsageEvent:
        if kind not in USAGE_KINDS:
            raise ValidationError(f"usage kind must be one of {', '.join(USAGE_KINDS)}")
        if quantity < 0:
            raise ValidationError("usage quantity must not be negative")
        key = dedupe_key if dedupe_key is not None else run_dedupe_key(kind, run_id)
        key = require_text(key, "dedupe_key", limit=200)
        return cls(
            event_id=ids.usage_event_id(workspace_id, key),
            workspace_id=workspace_id,
            kind=kind,
            quantity=quantity,
            occurred_at=require_aware(occurred_at, "occurred_at"),
            run_id=run_id,
            dedupe_key=key,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "workspace_id": self.workspace_id,
            "kind": self.kind,
            "quantity": self.quantity,
            "occurred_at": iso(self.occurred_at),
            "run_id": self.run_id,
            "dedupe_key": self.dedupe_key,
        }
