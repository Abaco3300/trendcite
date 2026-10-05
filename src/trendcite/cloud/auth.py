"""Supabase Auth validation boundary for TrendCite customer API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

DEFAULT_AUTH_TIMEOUT = 10.0


class AsyncGetTransport(Protocol):
    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
    ) -> tuple[int, bytes]: ...


class AuthenticationError(Exception):
    """Raised when a request has no valid authenticated principal."""


class AuthenticationUpstreamError(Exception):
    """Raised when Supabase Auth cannot be reached or gives an invalid response."""


@dataclass(frozen=True)
class AuthPrincipal:
    principal_id: str
    email: str


@dataclass(frozen=True)
class SupabaseAuthConfig:
    supabase_url: str
    publishable_key: str
    timeout: float = DEFAULT_AUTH_TIMEOUT

    def __post_init__(self) -> None:
        if not self.supabase_url.strip():
            raise ValueError("Supabase URL is required")
        if not self.publishable_key.strip():
            raise ValueError("Supabase publishable key is required")
        if self.timeout <= 0:
            raise ValueError("auth timeout must be greater than zero")


@dataclass
class AsyncSupabaseAuth:
    transport: AsyncGetTransport
    config: SupabaseAuthConfig

    async def authenticate(self, authorization: str | None) -> AuthPrincipal:
        token = _bearer_token(authorization)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "apikey": self.config.publishable_key,
        }
        try:
            status, raw = await self.transport(
                self.config.supabase_url.rstrip("/") + "/auth/v1/user",
                self.config.timeout,
                headers,
            )
        except Exception as exc:
            raise AuthenticationUpstreamError(type(exc).__name__) from exc

        if status in {401, 403}:
            raise AuthenticationError("invalid bearer token")
        if status != 200:
            raise AuthenticationUpstreamError(f"unexpected auth status {status}")

        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise AuthenticationUpstreamError("invalid auth JSON") from exc

        principal_id = str(payload.get("id") or "").strip()
        if not principal_id:
            raise AuthenticationUpstreamError("auth response missing user id")
        return AuthPrincipal(
            principal_id=principal_id,
            email=str(payload.get("email") or "").strip(),
        )


def _bearer_token(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if not value:
        raise AuthenticationError("missing authorization header")
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("invalid authorization header")
    return token.strip()
