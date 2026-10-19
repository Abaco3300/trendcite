"""Build strict nonprod TC-P008 connection settings without connecting.

Connection parameters are only passed to a caller-provided driver after
separate approval. Never log or serialize a password.
"""

from scripts.tc_p008_hosted_preflight import EXPECTED_HOST, EXPECTED_USER, validate_hosted_dsn


def build_secure_connection_kwargs(dsn: str, password: str) -> dict[str, object]:
    """Exact hosted target, TLS hostname validation and finite connect timeout."""
    validate_hosted_dsn(dsn)
    if not password or not isinstance(password, str) or "\n" in password or "\r" in password:
        raise RuntimeError("protected sandbox password unavailable")
    return {
        "host": EXPECTED_HOST,
        "port": 5432,
        "dbname": "postgres",
        "user": EXPECTED_USER,
        "password": password,
        "sslmode": "verify-full",
        "connect_timeout": 5,
        "application_name": "tc_p008_isolated_probe",
        "options": "-c statement_timeout=8000 -c lock_timeout=5000",
    }
