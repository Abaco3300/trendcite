"""Autonomous recovery and operational status models for TC-P007."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

RECOVERY_PENDING_REQUEUE = "pending_requeue"
RECOVERY_FAILED_REQUEUE = "failed_requeue"
RECOVERY_EXPIRED_LEASE_REQUEUE = "expired_lease_requeue"
RECOVERY_EXPIRED_FINAL_TERMINAL = "expired_final_terminal"

RECOVERY_ACTIONS = (
    RECOVERY_PENDING_REQUEUE,
    RECOVERY_FAILED_REQUEUE,
    RECOVERY_EXPIRED_LEASE_REQUEUE,
    RECOVERY_EXPIRED_FINAL_TERMINAL,
)


@dataclass(frozen=True)
class RecoveryCandidate:
    workspace_id: str
    tick_id: str
    schedule_id: str
    status: str
    attempt: int
    max_attempts: int
    action: str
    reason: str


@dataclass(frozen=True)
class AutomationRecoveryResult:
    candidates: int
    requeued: int
    terminalized: int
    already_recorded: int


@dataclass(frozen=True)
class AutomationSummary:
    workspace_id: str
    scheduler_last_seen_at: datetime | None
    scheduler_stale: bool
    enabled_schedules: int
    overdue_schedules: int
    pending_stale_ticks: int
    expired_running_ticks: int
    retryable_failed_ticks: int
    exhausted_failed_ticks: int
    recovery_actions_24h: int
    queue_failures_24h: int
    queue_failures_at_retry_limit_24h: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "scheduler_last_seen_at": (
                None
                if self.scheduler_last_seen_at is None
                else self.scheduler_last_seen_at.isoformat()
            ),
            "scheduler_stale": self.scheduler_stale,
            "enabled_schedules": self.enabled_schedules,
            "overdue_schedules": self.overdue_schedules,
            "pending_stale_ticks": self.pending_stale_ticks,
            "expired_running_ticks": self.expired_running_ticks,
            "retryable_failed_ticks": self.retryable_failed_ticks,
            "exhausted_failed_ticks": self.exhausted_failed_ticks,
            "recovery_actions_24h": self.recovery_actions_24h,
            "queue_failures_24h": self.queue_failures_24h,
            "queue_failures_at_retry_limit_24h": self.queue_failures_at_retry_limit_24h,
        }