"""TC-P008 connection factory preparation.

This module never calls a driver itself; it validates every input before
constructing a callable that could connect when the gated runner invokes it.
"""

from collections.abc import Callable
from typing import Any

from trendcite.cloud.tc_p008_connection_policy import build_secure_connection_kwargs


def prepare_sandbox_connection(
    dsn: str,
    password: str,
    *,
    driver_connect: Callable[..., Any],
    sslrootcert: str | None = None,
) -> Callable[[], Any]:
    """Validate the sandbox target and defer all network activity."""
    if not callable(driver_connect):
        raise RuntimeError("PostgreSQL connection driver unavailable")
    kwargs = build_secure_connection_kwargs(dsn, password, sslrootcert=sslrootcert)

    def connect() -> Any:
        return driver_connect(**kwargs)

    return connect
