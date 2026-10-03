from __future__ import annotations

import json
from typing import Any

from trendcite.cloud import ids
from trendcite.cloud.async_delivery import (
    POSTMARK_EMAIL_URL,
    PostmarkConfig,
    PostmarkDeliveryAdapter,
)
from trendcite.cloud.delivery import DeliveryEnvelope


class FakePostTransport:
    def __init__(
        self, *, status: int = 200, response: dict[str, Any] | bytes | None = None
    ) -> None:
        self.status = status
        self.response = (
            response
            if response is not None
            else {
                "ErrorCode": 0,
                "Message": "OK",
                "MessageID": "message-123",
            }
        )
        self.calls: list[tuple[str, float, dict[str, str], bytes]] = []

    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, bytes]:
        self.calls.append((url, timeout, dict(headers), body))
        if isinstance(self.response, bytes):
            payload = self.response
        else:
            payload = json.dumps(self.response).encode()
        return self.status, payload


class FailingTransport:
    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, bytes]:
        raise RuntimeError("server-token-secret-must-not-leak")


def envelope() -> DeliveryEnvelope:
    return DeliveryEnvelope(
        workspace_id="workspace-1",
        target_kind="alert",
        target_id="alert-1",
        attempt_number=1,
        subject="TrendCite signal",
        body="Evidence-backed update",
        renderer_version="alert-renderer-v1",
    )


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def config(
    *,
    token: str = "POSTMARK_API_TEST",
    recipient: str = "recipient@example.com",
) -> PostmarkConfig:
    return PostmarkConfig(
        server_token=token,
        sender="TrendCite <sender@example.com>",
        recipient_for_workspace=lambda workspace_id: recipient,
    )


def test_postmark_success_uses_official_endpoint_headers_and_json_shape() -> None:
    transport = FakePostTransport()
    adapter = PostmarkDeliveryAdapter(transport, config())

    result = _run(adapter.deliver(envelope()))

    assert result.ok
    assert result.provider == "postmark"
    assert result.reference == "message-123"
    assert len(transport.calls) == 1

    url, timeout, headers, raw_body = transport.calls[0]
    assert url == POSTMARK_EMAIL_URL
    assert timeout == 15.0
    assert headers == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Postmark-Server-Token": "POSTMARK_API_TEST",
    }
    body = json.loads(raw_body)
    assert body == {
        "From": "TrendCite <sender@example.com>",
        "To": "recipient@example.com",
        "Subject": "TrendCite signal",
        "TextBody": "Evidence-backed update",
        "MessageStream": "outbound",
        "Metadata": {
            "tc_attempt": ids.delivery_attempt_id("workspace-1", "alert", "alert-1", 1),
        },
    }


def test_postmark_nonzero_error_code_is_provider_failure() -> None:
    transport = FakePostTransport(
        status=200,
        response={"ErrorCode": 300, "Message": "Invalid email request", "MessageID": ""},
    )
    result = _run(PostmarkDeliveryAdapter(transport, config()).deliver(envelope()))

    assert not result.ok
    assert result.provider == "postmark"
    assert "ErrorCode 300" in result.detail


def test_postmark_http_failure_is_provider_failure() -> None:
    transport = FakePostTransport(
        status=401,
        response={"ErrorCode": 10, "Message": "Unauthorized", "MessageID": ""},
    )
    result = _run(PostmarkDeliveryAdapter(transport, config()).deliver(envelope()))

    assert not result.ok
    assert "HTTP 401" in result.detail


def test_postmark_transport_exception_does_not_leak_secret() -> None:
    secret = "server-token-secret-must-not-leak"
    adapter = PostmarkDeliveryAdapter(FailingTransport(), config(token=secret))

    result = _run(adapter.deliver(envelope()))

    assert not result.ok
    assert secret not in result.detail
    assert "RuntimeError" in result.detail


def test_postmark_missing_recipient_fails_without_network_call() -> None:
    transport = FakePostTransport()
    adapter = PostmarkDeliveryAdapter(transport, config(recipient=""))

    result = _run(adapter.deliver(envelope()))

    assert not result.ok
    assert "no recipient" in result.detail
    assert transport.calls == []


def test_postmark_invalid_json_is_failure_without_exception() -> None:
    transport = FakePostTransport(status=502, response=b"not-json")
    result = _run(PostmarkDeliveryAdapter(transport, config()).deliver(envelope()))

    assert not result.ok
    assert "invalid JSON" in result.detail
