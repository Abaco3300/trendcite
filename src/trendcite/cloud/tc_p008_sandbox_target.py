"""Packaged allowlist for the dedicated TC-P008 PostgreSQL sandbox target.

Pure validation only: never connects, never reads secrets. Lives inside the
installable package so runtime modules do not import the unpackaged
``scripts`` tree.
"""

from urllib.parse import urlsplit

EXPECTED_PROJECT = "btjgozzguhuzfdueensf"
EXPECTED_ROLE = "tc_p008_probe_login"
EXPECTED_DB_PATH = "/postgres"

# Direct connection (IPv6-only on the Supabase Free plan) and the provider's
# session-mode pooler (IPv4). Transaction mode (port 6543) is never allowed:
# it multiplexes backends and would invalidate two-session evidence.
SANDBOX_TARGETS: dict[str, tuple[str, int, str]] = {
    "direct": ("db.btjgozzguhuzfdueensf.supabase.co", 5432, EXPECTED_ROLE),
    "session-pooler": (
        "aws-0-us-east-1.pooler.supabase.com",
        5432,
        f"{EXPECTED_ROLE}.{EXPECTED_PROJECT}",
    ),
}

EXPECTED_HOST = SANDBOX_TARGETS["direct"][0]
EXPECTED_USER = EXPECTED_ROLE


def sandbox_dsn(transport: str) -> str:
    """Password-free DSN for an allowlisted transport."""
    if transport not in SANDBOX_TARGETS:
        raise RuntimeError("dedicated TC-P008 sandbox target required")
    host, port, user = SANDBOX_TARGETS[transport]
    return f"postgresql://{user}@{host}:{port}{EXPECTED_DB_PATH}"


def validate_hosted_dsn(dsn: str) -> dict[str, str]:
    """Reject libpq aliases, URI override parameters and unsafe routing."""
    try:
        uri = urlsplit(dsn)
        port = uri.port
        host = uri.hostname
        user = uri.username
    except ValueError as exc:
        raise RuntimeError("invalid sandbox connection target") from exc
    transport = next(
        (name for name, target in SANDBOX_TARGETS.items() if target == (host, port, user)),
        None,
    )
    if (
        transport is None
        or uri.scheme != "postgresql"
        or uri.path != EXPECTED_DB_PATH
        or uri.query
        or uri.fragment
        or uri.password is not None
        or not host
        or not user
    ):
        raise RuntimeError("dedicated TC-P008 sandbox target required")
    return {
        "project": EXPECTED_PROJECT,
        "host": host,
        "port": str(port),
        "user": user,
        "role": EXPECTED_ROLE,
        "transport": transport,
    }
