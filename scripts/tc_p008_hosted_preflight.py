"""Fail-closed hosted TC-P008 sandbox connection preflight; no SQL mutations.

The credential is read from an environment variable, never a command argument.
This module intentionally does not implement or execute the contention probe.
"""

import argparse
import os
from urllib.parse import urlsplit

EXPECTED_HOST = "db.btjgozzguhuzfdueensf.supabase.co"
EXPECTED_USER = "tc_p008_probe_login"
EXPECTED_PROJECT = "btjgozzguhuzfdueensf"


def validate_hosted_dsn(dsn: str) -> dict[str, str]:
    """Reject libpq aliases, URI override parameters and unsafe routing."""
    try:
        uri = urlsplit(dsn)
        port = uri.port
        host = uri.hostname
        user = uri.username
    except ValueError as exc:
        raise RuntimeError("invalid sandbox connection target") from exc
    if (
        uri.scheme != "postgresql"
        or host != EXPECTED_HOST
        or port != 5432
        or user != EXPECTED_USER
        or uri.path != "/postgres"
        or uri.query
        or uri.fragment
        or uri.password is not None
        or not host
    ):
        raise RuntimeError("dedicated TC-P008 sandbox target required")
    return {"project": EXPECTED_PROJECT, "host": EXPECTED_HOST, "role": EXPECTED_USER}


def connection_from_environment() -> tuple[dict[str, str], str]:
    """Obtain an ephemeral password without printing its value."""
    dsn = os.environ.get("TC_P008_HOSTED_DSN", "")
    metadata = validate_hosted_dsn(dsn)
    password = os.environ.get("TC_P008_HOSTED_PASSWORD", "")
    if not password or "\\n" in password or "\\r" in password:
        raise RuntimeError("protected sandbox password unavailable")
    return metadata, password


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate isolated hosted connection policy")
    parser.add_argument("--check-target", action="store_true", required=True)
    parser.parse_args()
    metadata, _password = connection_from_environment()
    print(f"HOSTED_SANDBOX_TARGET_PASS project={metadata['project']} role={metadata['role']}")
    print("HOSTED_CONNECTION_NOT_ATTEMPTED")
    print("HOSTED_CONTENTION_NOT_VERIFIED")


if __name__ == "__main__":
    main()
