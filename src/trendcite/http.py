"""Minimal, safe HTTP GET built on the standard library.

Controls: http(s)-only, private-host refusal, request timeout, bounded response
size, bounded retries with exponential backoff for transient failures, and a
descriptive User-Agent. No cookies, no auth headers, no redirects to non-http(s).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from . import __version__
from .security import UnsafeURLError, ensure_fetchable

log = logging.getLogger("trendcite.http")

USER_AGENT = f"trendcite/{__version__} (+evidence-first trend research; read-only)"
DEFAULT_TIMEOUT = 10.0
MAX_BYTES = 2_000_000
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """A fetch failed after retries or was refused for safety reasons."""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        try:
            ensure_fetchable(newurl)
        except UnsafeURLError as exc:
            raise FetchError(f"unsafe redirect: {exc}") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirectHandler())

# A transport takes (url, timeout) and returns (status, body bytes). Tests inject fakes.
Transport = Callable[[str, float], tuple[int, bytes]]


def _urllib_transport(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(  # scheme validated by ensure_fetchable
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            body = resp.read(MAX_BYTES + 1)
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        return int(exc.code), b""


def fetch_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    backoff: float = 0.75,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """GET ``url`` and return the body, raising :class:`FetchError` on failure."""
    try:
        safe_url = ensure_fetchable(url)
    except UnsafeURLError as exc:
        raise FetchError(str(exc)) from exc
    send = transport or _urllib_transport
    last_error = "unknown error"
    for attempt in range(retries + 1):
        try:
            status, body = send(safe_url, timeout)
        except FetchError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
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
            delay = backoff * (2**attempt)
            log.debug("retrying %s in %.2fs (%s)", safe_url, delay, last_error)
            sleep(delay)
    raise FetchError(f"{safe_url}: {last_error}")


def fetch_json(url: str, **kwargs: Any) -> Any:
    body = fetch_bytes(url, **kwargs)
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise FetchError(f"invalid JSON from {url}") from exc
