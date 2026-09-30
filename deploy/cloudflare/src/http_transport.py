"""Cloudflare Workers Fetch API transport for TrendCite async collectors."""

from __future__ import annotations

from typing import Any

from js import AbortController, Uint8Array, clearTimeout, setTimeout
from workers import fetch

from trendcite.http import MAX_BYTES, FetchError


class CloudflareFetchTransport:
    async def __call__(
        self,
        url: str,
        timeout: float,
        headers: dict[str, str],
    ) -> tuple[int, bytes]:
        controller = AbortController.new()
        timer = setTimeout(
            lambda: controller.abort(),
            max(1, int(timeout * 1000)),
        )
        try:
            response = await fetch(
                url,
                headers=headers,
                signal=controller.signal,
            )
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_BYTES:
                        raise FetchError(f"response exceeds {MAX_BYTES} bytes")
                except ValueError:
                    pass
            buffer = await response.arrayBuffer()
        finally:
            clearTimeout(timer)

        body: Any = Uint8Array.new(buffer).to_py()
        data = bytes(body)
        if len(data) > MAX_BYTES:
            raise FetchError(f"response exceeds {MAX_BYTES} bytes")
        return int(response.status), data
