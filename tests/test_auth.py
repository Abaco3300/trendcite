from __future__ import annotations

import json
from typing import Any

import pytest

from trendcite.cloud.auth import (
    AsyncSupabaseAuth,
    AuthenticationError,
    AuthenticationUpstreamError,
    SupabaseAuthConfig,
)


class FakeTransport:
    def __init__(self, status: int, payload: dict[str, Any] | bytes) -> None:
        self.status = status
        self.payload = payload
        self.calls: list[tuple[str, float, dict[str, str]]] = []

    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
    ) -> tuple[int, bytes]:
        self.calls.append((url, timeout, dict(headers)))
        if isinstance(self.payload, bytes):
            body = self.payload
        else:
            body = json.dumps(self.payload).encode()
        return self.status, body


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def config() -> SupabaseAuthConfig:
    return SupabaseAuthConfig(
        supabase_url="https://project.supabase.co",
        publishable_key="sb_publishable_public",
    )


def test_valid_bearer_token_returns_principal() -> None:
    transport = FakeTransport(
        200,
        {"id": "user-123", "email": "user@example.com"},
    )
    auth = AsyncSupabaseAuth(transport, config())

    principal = _run(auth.authenticate("Bearer token-123"))

    assert principal.principal_id == "user-123"
    assert principal.email == "user@example.com"
    url, timeout, headers = transport.calls[0]
    assert url == "https://project.supabase.co/auth/v1/user"
    assert timeout == 10.0
    assert headers["Authorization"] == "Bearer token-123"
    assert headers["apikey"] == "sb_publishable_public"


@pytest.mark.parametrize("value", [None, "", "Basic abc", "Bearer ", "token"])
def test_missing_or_malformed_authorization_is_rejected(value: str | None) -> None:
    auth = AsyncSupabaseAuth(FakeTransport(200, {"id": "ignored"}), config())
    with pytest.raises(AuthenticationError):
        _run(auth.authenticate(value))


def test_supabase_401_is_authentication_error() -> None:
    auth = AsyncSupabaseAuth(FakeTransport(401, {"message": "invalid"}), config())
    with pytest.raises(AuthenticationError):
        _run(auth.authenticate("Bearer bad-token"))


def test_supabase_5xx_is_upstream_error() -> None:
    auth = AsyncSupabaseAuth(FakeTransport(503, {"message": "down"}), config())
    with pytest.raises(AuthenticationUpstreamError):
        _run(auth.authenticate("Bearer token"))


def test_invalid_json_is_upstream_error() -> None:
    auth = AsyncSupabaseAuth(FakeTransport(200, b"not-json"), config())
    with pytest.raises(AuthenticationUpstreamError):
        _run(auth.authenticate("Bearer token"))
