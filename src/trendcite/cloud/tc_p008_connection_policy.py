"""Build strict nonprod TC-P008 connection settings without connecting.

Connection parameters are only passed to a caller-provided driver after
separate approval. Never log or serialize a password.
"""

from pathlib import Path

from trendcite.cloud.tc_p008_sandbox_target import validate_hosted_dsn

_PEM_MARKER = b"-----BEGIN CERTIFICATE-----"


def _validated_root_certificate(sslrootcert: str) -> str:
    """Require an explicit, readable PEM trust anchor for verify-full.

    Supabase database endpoints present certificates chained to the provider's
    own root CA, which is not in public trust stores. Without an explicit
    trust anchor libpq would fall back to a per-user default file; an absent
    or wrong file must fail here, before any network activity.
    """
    if not isinstance(sslrootcert, str) or not sslrootcert.strip():
        raise RuntimeError("TC-P008 TLS root certificate required")
    path = Path(sslrootcert)
    try:
        head = path.read_bytes()[:4096]
    except OSError as exc:
        raise RuntimeError("TC-P008 TLS root certificate unreadable") from exc
    if _PEM_MARKER not in head:
        raise RuntimeError("TC-P008 TLS root certificate is not PEM")
    return str(path.resolve())


def build_secure_connection_kwargs(
    dsn: str, password: str, *, sslrootcert: str | None = None
) -> dict[str, object]:
    """Exact hosted target, TLS hostname validation and finite connect timeout."""
    target = validate_hosted_dsn(dsn)
    if not isinstance(password, str) or not password or "\n" in password or "\r" in password:
        raise RuntimeError("protected sandbox password unavailable")
    kwargs: dict[str, object] = {
        "host": target["host"],
        "port": int(target["port"]),
        "dbname": "postgres",
        "user": target["user"],
        "password": password,
        "sslmode": "verify-full",
        "connect_timeout": 5,
        "application_name": "tc_p008_isolated_probe",
    }
    if target["transport"] == "direct":
        # The pooler may reject arbitrary startup parameters; the role itself
        # carries identical timeouts (rolconfig) and the runner sets them again
        # with SET LOCAL, so the pooler path loses no bound.
        kwargs["options"] = "-c statement_timeout=8000 -c lock_timeout=5000"
    if sslrootcert is not None:
        kwargs["sslrootcert"] = _validated_root_certificate(sslrootcert)
    return kwargs
