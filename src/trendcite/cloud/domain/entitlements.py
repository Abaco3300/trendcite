"""Server-side entitlement and quota decisions for TrendCite Pro.

Entitlements are separate from identity and workspace membership:
Supabase Auth answers who, cloud_membership answers which workspace, and this
module answers which capability and how much.

No price, checkout or payment-provider state appears here. TC-P006 is noncommercial.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..errors import ValidationError

CAP_RADAR_RUN = "radar_run"
CAP_WATCHLIST_WRITE = "watchlist_write"
CAP_RADAR_WRITE = "radar_write"
CAP_SIGNAL_HISTORY = "signal_history"
CAP_ALERT_VIEW = "alert_view"
CAP_DIGEST_VIEW = "digest_view"

CAPABILITIES = (
    CAP_RADAR_RUN,
    CAP_WATCHLIST_WRITE,
    CAP_RADAR_WRITE,
    CAP_SIGNAL_HISTORY,
    CAP_ALERT_VIEW,
    CAP_DIGEST_VIEW,
)

PLAN_NONPROD_LIMITED = "nonprod_limited"
PLAN_NONPROD_FULL = "nonprod_full"

NONPROD_PLAN_DEFINITIONS: dict[str, dict[str, Any]] = {
    PLAN_NONPROD_LIMITED: {
        "display_name": "Nonprod Limited",
        "capabilities": {
            CAP_RADAR_RUN: True,
            CAP_WATCHLIST_WRITE: True,
            CAP_RADAR_WRITE: True,
            CAP_SIGNAL_HISTORY: True,
            CAP_ALERT_VIEW: True,
            CAP_DIGEST_VIEW: True,
        },
        "quotas": {CAP_RADAR_RUN: {"kind": "radar_run", "limit": 10}},
    },
    PLAN_NONPROD_FULL: {
        "display_name": "Nonprod Full",
        "capabilities": {key: True for key in CAPABILITIES},
        "quotas": {},
    },
}


def monthly_period(at: datetime) -> tuple[datetime, datetime]:
    """Return the UTC calendar-month window containing the supplied instant."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValidationError("entitlement evaluation time must be timezone-aware")
    instant = at.astimezone(UTC)
    start = datetime(instant.year, instant.month, 1, tzinfo=UTC)
    if instant.month == 12:
        end = datetime(instant.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(instant.year, instant.month + 1, 1, tzinfo=UTC)
    return start, end


@dataclass(frozen=True)
class EntitlementDecision:
    workspace_id: str
    plan_key: str
    capability_key: str
    allowed: bool
    reason: str
    quota_kind: str = ""
    quota_limit: int | None = None
    used: int = 0
    remaining: int | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "plan_key": self.plan_key,
            "capability_key": self.capability_key,
            "allowed": self.allowed,
            "reason": self.reason,
            "quota_kind": self.quota_kind,
            "quota_limit": self.quota_limit,
            "used": self.used,
            "remaining": self.remaining,
            "period_start": None if self.period_start is None else self.period_start.isoformat(),
            "period_end": None if self.period_end is None else self.period_end.isoformat(),
        }


@dataclass(frozen=True)
class EntitlementSummary:
    workspace_id: str
    plan_key: str
    display_name: str
    capabilities: dict[str, bool]
    quotas: dict[str, dict[str, Any]]
    usage: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "plan_key": self.plan_key,
            "display_name": self.display_name,
            "capabilities": dict(self.capabilities),
            "quotas": dict(self.quotas),
            "usage": dict(self.usage),
        }
