"""Cloud error types, and the one place an exception is turned into a stored message.

A failed RadarRun stores *why* it failed. That text is tenant-visible, so it must
never carry a filesystem path, a connection string or an unbounded stack message:
:func:`safe_error` is the only sanctioned way to produce it.
"""

from __future__ import annotations

import re

#: Stored error detail is bounded; a run row is not a log sink.
MAX_ERROR_DETAIL = 200

# Anything path-shaped ("C:\...", "/home/...", "\server\share") is redacted before
# it can reach a stored, tenant-visible error message.
_PATH = re.compile(r"(?:[A-Za-z]:[\/]|\\|(?<![\w.])/)[^\s'\"]*")


class CloudError(RuntimeError):
    """Base class for every error the Cloud layer raises deliberately."""


class ValidationError(CloudError):
    """A caller supplied input the domain refuses (empty name, naive datetime, ...)."""


class NotFoundError(CloudError):
    """A referenced entity does not exist, or does not exist *in this workspace*."""


class ConflictError(CloudError):
    """The write conflicts with something already stored (duplicate name, ...)."""


class TenantIsolationError(CloudError):
    """A write tried to link entities belonging to two different workspaces.

    Kept distinct from :class:`NotFoundError` on purpose: this is the signal that a
    caller attempted cross-tenant linkage, which is a governance event, not a typo.
    """


class MigrationError(CloudError):
    """The migration ledger disagrees with the migrations on disk."""


class ExecutionError(CloudError):
    """Signal execution failed. The run is recorded FAILED with a safe message."""


def safe_error(exc: BaseException) -> tuple[str, str]:
    """Reduce an exception to a stored ``(code, detail)`` pair.

    ``code`` is the exception class name, which is stable and carries no data.
    ``detail`` is the message with newlines collapsed, paths redacted and length
    bounded, so that storing it can never leak the host or exhaust a column.
    """
    code = type(exc).__name__
    detail = " ".join(str(exc).split())
    detail = _PATH.sub("<path>", detail)
    if len(detail) > MAX_ERROR_DETAIL:
        detail = detail[: MAX_ERROR_DETAIL - 1].rstrip() + "\u2026"
    return code, detail
