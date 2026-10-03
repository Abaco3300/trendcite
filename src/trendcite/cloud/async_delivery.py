"""Async transactional-delivery adapters for the Cloudflare execution plane."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from . import ids
from .delivery import DeliveryEnvelope, DeliveryResult

POSTMARK_EMAIL_URL = "https://api.postmarkapp.com/email"
POSTMARK_PROVIDER = "postmark"
POSTMARK_CHANNEL = "email"
POSTMARK_MESSAGE_STREAM = "outbound"
DEFAULT_DELIVERY_TIMEOUT = 15.0


class AsyncPostTransport(Protocol):
    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, bytes]: ...


class AsyncDeliveryPort(Protocol):
    @property
    def channel(self) -> str: ...

    async def deliver(self, envelope: DeliveryEnvelope) -> DeliveryResult: ...


RecipientResolver = Callable[[str], str | Awaitable[str]]


@dataclass(frozen=True)
class PostmarkConfig:
    server_token: str
    sender: str
    recipient_for_workspace: RecipientResolver
    message_stream: str = POSTMARK_MESSAGE_STREAM
    timeout: float = DEFAULT_DELIVERY_TIMEOUT

    def __post_init__(self) -> None:
        if not self.server_token.strip():
            raise ValueError("Postmark server token is required")
        if not self.sender.strip():
            raise ValueError("Postmark sender is required")
        if not self.message_stream.strip():
            raise ValueError("Postmark message stream is required")
        if self.timeout <= 0:
            raise ValueError("Postmark timeout must be greater than zero")


@dataclass
class PostmarkDeliveryAdapter:
    transport: AsyncPostTransport
    config: PostmarkConfig

    @property
    def channel(self) -> str:
        return POSTMARK_CHANNEL

    async def deliver(self, envelope: DeliveryEnvelope) -> DeliveryResult:
        recipient = self.config.recipient_for_workspace(envelope.workspace_id)
        if hasattr(recipient, "__await__"):
            recipient = await recipient
        recipient_text = str(recipient).strip()
        if not recipient_text:
            return DeliveryResult(
                ok=False,
                provider=POSTMARK_PROVIDER,
                detail="no recipient configured for workspace",
            )

        attempt_id = ids.delivery_attempt_id(
            envelope.workspace_id,
            envelope.target_kind,
            envelope.target_id,
            envelope.attempt_number,
        )
        payload = {
            "From": self.config.sender,
            "To": recipient_text,
            "Subject": envelope.subject,
            "TextBody": envelope.body,
            "MessageStream": self.config.message_stream,
            "Metadata": {"tc_attempt": attempt_id},
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": self.config.server_token,
        }
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        try:
            status, response_body = await self.transport(
                POSTMARK_EMAIL_URL,
                self.config.timeout,
                headers,
                body,
            )
        except Exception as exc:
            return DeliveryResult(
                ok=False,
                provider=POSTMARK_PROVIDER,
                detail=f"transport error: {type(exc).__name__}",
            )

        try:
            response = json.loads(response_body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return DeliveryResult(
                ok=False,
                provider=POSTMARK_PROVIDER,
                detail=f"invalid JSON response (HTTP {status})",
            )

        error_code = response.get("ErrorCode")
        message = str(response.get("Message") or "").strip()
        reference = str(response.get("MessageID") or "").strip()

        if 200 <= status < 300 and error_code == 0:
            return DeliveryResult(
                ok=True,
                provider=POSTMARK_PROVIDER,
                reference=reference,
            )

        detail = f"HTTP {status}"
        if error_code is not None:
            detail += f" / ErrorCode {error_code}"
        if message:
            detail += f": {message}"
        return DeliveryResult(
            ok=False,
            provider=POSTMARK_PROVIDER,
            detail=detail[:200],
        )
