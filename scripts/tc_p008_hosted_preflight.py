"""Fail-closed hosted TC-P008 sandbox connection preflight; no SQL mutations.

The credential is read from an environment variable, never a command argument.
This module intentionally does not implement or execute the contention probe.
"""

import argparse
import os

from trendcite.cloud.tc_p008_sandbox_target import (
    EXPECTED_HOST,
    EXPECTED_PROJECT,
    EXPECTED_USER,
    validate_hosted_dsn,
)

__all__ = [
    "EXPECTED_HOST",
    "EXPECTED_PROJECT",
    "EXPECTED_USER",
    "connection_from_environment",
    "validate_hosted_dsn",
]


def connection_from_environment() -> tuple[dict[str, str], str]:
    """Obtain an ephemeral password without printing its value."""
    dsn = os.environ.get("TC_P008_HOSTED_DSN", "")
    metadata = validate_hosted_dsn(dsn)
    password = os.environ.get("TC_P008_HOSTED_PASSWORD", "")
    if not password or "\n" in password or "\r" in password:
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
