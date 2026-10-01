"""Cloudflare Workers Fetch API transport for TrendCite async collectors."""

from __future__ import annotations

import asyncio
from typing import Any

from workers import fetch

from trendcite.http import MAX_BYTES, FetchError


class CloudflareFetchTransport:
    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
    ) -> tuple[int, bytes]:
        async def request_and_read() -> tuple[int, bytes]:
            response = await fetch(url, headers=headers)
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_BYTES:
                        raise FetchError(f"response exceeds {MAX_BYTES} bytes")
                except ValueError:
                    pass

            body: Any = await response.bytes()
            data = bytes(body)
            if len(data) > MAX_BYTES:
                raise FetchError(f"response exceeds {MAX_BYTES} bytes")
            return int(response.status), data

        return await asyncio.wait_for(request_and_read(), timeout=timeout)
