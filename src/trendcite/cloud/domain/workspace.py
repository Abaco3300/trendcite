"""Workspace and Membership: the tenant boundary.

The Workspace *is* the tenant. Every tenant-scoped row carries its ``workspace_id``,
every repository read is filtered by it, and no service accepts two entities from
different workspaces in one call. There is no "global admin" object here on purpose:
a Cloud Foundation that ships a cross-tenant escape hatch has no tenant boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .. import ids
from ..errors import ValidationError
from ._base import iso, require_aware, require_text

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER)

#: Roles permitted to create or change watchlists, radars and runs.
WRITE_ROLES = frozenset({ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER})

_SLUG_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def normalize_slug(value: str) -> str:
    """A workspace slug: lowercase, ``[a-z0-9-]``, no leading or trailing dash."""
    cleaned = "-".join(value.strip().lower().split()).strip("-")
    if not cleaned:
        raise ValidationError("workspace slug must not be blank")
    if len(cleaned) > 60:
        raise ValidationError("workspace slug must be at most 60 characters")
    bad = sorted(set(cleaned) - _SLUG_ALLOWED)
    if bad:
        raise ValidationError(f"workspace slug may not contain {''.join(bad)!r}")
    return cleaned


@dataclass(frozen=True)
class Workspace:
    """One tenant."""

    workspace_id: str
    slug: str
    name: str
    created_at: datetime

    @classmethod
    def create(cls, *, slug: str, name: str, created_at: datetime) -> Workspace:
        canonical = normalize_slug(slug)
        return cls(
            workspace_id=ids.workspace_id(canonical),
            slug=canonical,
            name=require_text(name, "workspace name"),
            created_at=require_aware(created_at, "created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "slug": self.slug,
            "name": self.name,
            "created_at": iso(self.created_at),
        }


@dataclass(frozen=True)
class Membership:
    """A principal's role inside exactly one workspace."""

    membership_id: str
    workspace_id: str
    principal_id: str
    role: str
    created_at: datetime

    @classmethod
    def create(
        cls, *, workspace_id: str, principal_id: str, role: str, created_at: datetime
    ) -> Membership:
        principal = require_text(principal_id, "principal_id")
        if role not in ROLES:
            raise ValidationError(f"role must be one of {', '.join(ROLES)}")
        return cls(
            membership_id=ids.membership_id(workspace_id, principal),
            workspace_id=workspace_id,
            principal_id=principal,
            role=role,
            created_at=require_aware(created_at, "created_at"),
        )

    @property
    def may_write(self) -> bool:
        return self.role in WRITE_ROLES

    def to_dict(self) -> dict[str, Any]:
        return {
            "membership_id": self.membership_id,
            "workspace_id": self.workspace_id,
            "principal_id": self.principal_id,
            "role": self.role,
            "created_at": iso(self.created_at),
        }
