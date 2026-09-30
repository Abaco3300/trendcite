"""Async, runtime-neutral HTTP primitives for Cloud source acquisition."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from ..http import DEFAULT_TIMEOUT, MAX_BYTES, RETRY_STATUSES, USER_AGENT, FetchError
from ..security import UnsafeURLError, ensure_fetchable


class AsyncHTTPTransport(Protocol):
    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
    ) -> tuple[int, bytes]: ...


AsyncSleep = Callable[[float], Awaitable[None]]


async def fetch_bytes_async(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    backoff: float = 0.75,
    transport: AsyncHTTPTransport,
    sleep: AsyncSleep = asyncio.sleep,
) -> bytes:
    """Fetch bounded bytes without synchronous network I/O."""

    try:
        safe_url = ensure_fetchable(url)
    except UnsafeURLError as exc:
        raise FetchError(str(exc)) from exc

    last_error = "unknown error"
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    for attempt in range(retries + 1):
        try:
            status, body = await transport(safe_url, timeout, headers)
        except FetchError:
            raise
        except Exception as exc:
            last_error = f"network error: {exc.__class__.__name__}"
        else:
            if 200 <= status < 300:
                if len(body) > MAX_BYTES:
                    raise FetchError(f"response exceeds {MAX_BYTES} bytes")
                return body
            last_error = f"HTTP {status}"
            if status not in RETRY_STATUSES:
                break
        if attempt < retries:
            await sleep(backoff * (2**attempt))

    raise FetchError(f"{safe_url}: {last_error}")


async def fetch_json_async(
    url: str,
    *,
    transport: AsyncHTTPTransport,
    **kwargs: Any,
) -> Any:
    body = await fetch_bytes_async(url, transport=transport, **kwargs)
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise FetchError(f"invalid JSON from {url}") from exc
