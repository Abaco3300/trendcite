"""The delivery boundary: one port, one local adapter, and nothing provider-shaped
above it.

:class:`DeliveryPort` is the whole contract. It takes a rendered, provider-neutral
:class:`DeliveryEnvelope` and returns a :class:`DeliveryResult`. It does not know what
an Alert is, it cannot read the database, and it is never called inside a transaction:
a network call holding a write lock is how a slow provider turns into a stalled
tenant.

The only adapter here is :class:`LocalDeliveryAdapter`, which delivers to memory. It
is deliberately the *only* one. Shipping an SMTP or webhook adapter in this build
would make "is delivery wired up" a question about credentials rather than about code,
and that is a decision for a human, not for a commit. A second adapter is a new class
implementing the same protocol, not a change to anything above it.
"""

from __future__ import annotations

from collections.abc import Container
from dataclasses import dataclass, field
from typing import Protocol

from .domain.alerts import CHANNEL_LOCAL, TARGET_KINDS
from .errors import ValidationError


@dataclass(frozen=True)
class DeliveryEnvelope:
    """What is handed to a provider: rendered content and the reference it is about.

    Carries no address, no credential and no provider option. Routing is the
    adapter's business, so an envelope is safe to log, store and compare.
    """

    workspace_id: str
    target_kind: str
    target_id: str
    attempt_number: int
    subject: str
    body: str
    renderer_version: str

    def __post_init__(self) -> None:
        if self.target_kind not in TARGET_KINDS:
            raise ValidationError(f"target_kind must be one of {', '.join(TARGET_KINDS)}")
        if self.attempt_number < 1:
            raise ValidationError("attempt_number must be 1 or greater")


@dataclass(frozen=True)
class DeliveryResult:
    """What the provider said. ``provider`` and ``reference`` are the only
    provider-specific values in the system, and they end up on a DeliveryAttempt."""

    ok: bool
    provider: str
    reference: str = ""
    detail: str = ""


class DeliveryPort(Protocol):
    """A channel that can accept a rendered payload.

    Implementations must not raise for ordinary provider failures: a refused send is a
    ``DeliveryResult(ok=False, ...)``, which is data the retry logic can act on. An
    exception is reserved for a programming error.
    """

    @property
    def channel(self) -> str: ...

    def deliver(self, envelope: DeliveryEnvelope) -> DeliveryResult: ...


@dataclass
class LocalDeliveryAdapter:
    """In-process delivery. Deterministic success, with failure on demand.

    ``fail_targets`` makes failure a property of *which* payload is being sent rather
    than of how many times it has been tried, so a test can say "this alert's provider
    is broken" without also saying "and it is broken forever". ``fail_attempts_below``
    does the opposite: it fails the first N attempts and then succeeds, which is what a
    transient outage looks like and is how the retry-then-succeed path is exercised.
    """

    provider: str = "local-memory"
    fail_targets: Container[str] = frozenset()
    fail_attempts_below: int = 0
    delivered: list[DeliveryEnvelope] = field(default_factory=list)
    attempts: list[DeliveryEnvelope] = field(default_factory=list)

    @property
    def channel(self) -> str:
        return CHANNEL_LOCAL

    def deliver(self, envelope: DeliveryEnvelope) -> DeliveryResult:
        self.attempts.append(envelope)
        if envelope.target_id in self.fail_targets:
            return DeliveryResult(
                ok=False,
                provider=self.provider,
                detail="local adapter was configured to refuse this target",
            )
        if envelope.attempt_number < self.fail_attempts_below:
            return DeliveryResult(
                ok=False,
                provider=self.provider,
                detail=f"transient local failure on attempt {envelope.attempt_number}",
            )
        self.delivered.append(envelope)
        # Derived from the envelope rather than randomly generated, so the same send
        # produces the same reference and a stored attempt stays comparable.
        reference = f"{envelope.target_kind}:{envelope.target_id}:{envelope.attempt_number}"
        return DeliveryResult(ok=True, provider=self.provider, reference=reference)
