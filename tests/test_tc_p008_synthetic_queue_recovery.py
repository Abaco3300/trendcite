"""Offline synthetic Queue/DLQ contract checks. No provider or production calls."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Harness:
    max_attempts: int = 3
    committed: set[str] = field(default_factory=set)
    effects: dict[str, int] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    dlq: dict[str, str] = field(default_factory=dict)

    def deliver(self, key: str, *, fail: bool = False, crash_after_commit: bool = False) -> str:
        if key in self.committed:
            return "DUPLICATE_ACK"
        if key in self.dlq:
            return "QUARANTINED"
        self.attempts[key] = self.attempts.get(key, 0) + 1
        if fail:
            if self.attempts[key] >= self.max_attempts:
                self.dlq[key] = "attempts_exhausted"
                return "DLQ"
            return "RETRY"
        self.committed.add(key)
        self.effects[key] = self.effects.get(key, 0) + 1
        if crash_after_commit:
            return "ACK_LOST"
        return "ACK"

    def replay_dlq(self, key: str, *, approved: bool) -> str:
        if not approved:
            return "BLOCKED"
        if key not in self.dlq:
            return "NOT_FOUND"
        del self.dlq[key]
        self.attempts.pop(key, None)
        return self.deliver(key)


def test_redelivery_after_ack_loss_no_extra_effect() -> None:
    h = Harness()
    assert h.deliver("tenant-a:job-1", crash_after_commit=True) == "ACK_LOST"
    assert h.deliver("tenant-a:job-1") == "DUPLICATE_ACK"
    assert h.effects == {"tenant-a:job-1": 1}


def test_bounded_retries_and_poison_dlq() -> None:
    h = Harness()
    assert [h.deliver("tenant-a:poison", fail=True) for _ in range(3)] == ["RETRY", "RETRY", "DLQ"]
    assert h.deliver("tenant-a:poison") == "QUARANTINED"
    assert h.effects == {}
    assert h.dlq["tenant-a:poison"] == "attempts_exhausted"


def test_dlq_replay_requires_explicit_approval() -> None:
    h = Harness()
    for _ in range(3):
        h.deliver("tenant-b:recovered", fail=True)
    assert h.replay_dlq("tenant-b:recovered", approved=False) == "BLOCKED"
    assert "tenant-b:recovered" in h.dlq
    assert h.replay_dlq("tenant-b:recovered", approved=True) == "ACK"
    assert h.deliver("tenant-b:recovered") == "DUPLICATE_ACK"
    assert h.effects["tenant-b:recovered"] == 1


def test_tenant_and_job_isolation() -> None:
    h = Harness()
    assert h.deliver("tenant-a:42") == "ACK"
    assert h.deliver("tenant-b:42") == "ACK"
    assert len(h.committed) == 2
    assert all(count == 1 for count in h.effects.values())


def test_mixed_duplicate_and_permanent_failure() -> None:
    h = Harness(max_attempts=2)
    assert h.deliver("tenant-a:good") == "ACK"
    assert h.deliver("tenant-a:good") == "DUPLICATE_ACK"
    assert h.deliver("tenant-a:bad", fail=True) == "RETRY"
    assert h.deliver("tenant-a:bad", fail=True) == "DLQ"
    assert h.effects == {"tenant-a:good": 1}
