"""Workspace membership authorization queries for the customer API."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .postgres import Connection, Connector

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class AuthorizedWorkspace:
    workspace_id: str
    slug: str
    name: str
    role: str
    created_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "workspace_id": self.workspace_id,
            "slug": self.slug,
            "name": self.name,
            "role": self.role,
            "created_at": self.created_at.isoformat(),
        }


class PostgresAccessStore:
    def __init__(self, connector: Connector, *, runtime_role: str = "trendcite_runtime") -> None:
        if not _IDENTIFIER.fullmatch(runtime_role):
            raise ValueError("runtime role must be a PostgreSQL identifier")
        self._connector = connector
        self._runtime_role = runtime_role

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[Connection]:
        conn = await self._connector()
        try:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL ROLE {self._runtime_role}")
                yield conn
        finally:
            await conn.close()

    async def list_workspaces(self, principal_id: str) -> tuple[AuthorizedWorkspace, ...]:
        async with self._transaction() as conn:
            rows = await conn.fetch(
                """
                SELECT w.workspace_id, w.slug, w.name, w.created_at, m.role
                FROM trendcite.cloud_membership AS m
                JOIN trendcite.cloud_workspace AS w
                  ON w.workspace_id=m.workspace_id
                WHERE m.principal_id=$1
                ORDER BY w.created_at, w.workspace_id
                """,
                principal_id,
            )
            return tuple(_workspace(row) for row in rows)

    async def get_workspace(
        self,
        principal_id: str,
        workspace_id: str,
    ) -> AuthorizedWorkspace | None:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                SELECT w.workspace_id, w.slug, w.name, w.created_at, m.role
                FROM trendcite.cloud_membership AS m
                JOIN trendcite.cloud_workspace AS w
                  ON w.workspace_id=m.workspace_id
                WHERE m.principal_id=$1 AND w.workspace_id=$2
                """,
                principal_id,
                workspace_id,
            )
            return None if row is None else _workspace(row)


def _workspace(row: Any) -> AuthorizedWorkspace:
    created = row["created_at"]
    if not isinstance(created, datetime):
        created = datetime.fromisoformat(str(created))
    return AuthorizedWorkspace(
        workspace_id=str(row["workspace_id"]),
        slug=str(row["slug"]),
        name=str(row["name"]),
        role=str(row["role"]),
        created_at=created,
    )
