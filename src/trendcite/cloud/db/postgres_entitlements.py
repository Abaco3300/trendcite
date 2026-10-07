"""PostgreSQL entitlement resolution and usage aggregation.

The runtime path is workspace-scoped and server-side. Customer-facing reads can ask
for an additional principal membership check in the same transaction; internal
scheduler enforcement intentionally has no principal because it executes already
tenant-scoped scheduled work.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from ..domain.entitlements import (
    CAPABILITIES,
    EntitlementDecision,
    EntitlementSummary,
    monthly_period,
)
from ..errors import NotFoundError, ValidationError
from .postgres import Connection, Connector

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresEntitlementStore:
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

    async def _require_member(self, conn: Connection, principal_id: str, workspace_id: str) -> None:
        role = await conn.fetchval(
            """
            SELECT role
            FROM trendcite.cloud_membership
            WHERE principal_id=$1 AND workspace_id=$2
            """,
            principal_id,
            workspace_id,
        )
        if role is None:
            raise NotFoundError("workspace not found")

    async def resolve_capability(
        self,
        workspace_id: str,
        capability_key: str,
        *,
        at: datetime,
    ) -> EntitlementDecision:
        async with self._transaction() as conn:
            return await self._resolve_capability(conn, workspace_id, capability_key, at=at)

    async def resolve_capability_for_principal(
        self,
        principal_id: str,
        workspace_id: str,
        capability_key: str,
        *,
        at: datetime,
    ) -> EntitlementDecision:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            return await self._resolve_capability(conn, workspace_id, capability_key, at=at)

    async def summary_for_principal(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        at: datetime,
    ) -> EntitlementSummary:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            plan = await self._active_plan(conn, workspace_id, at=at)
            if plan is None:
                return EntitlementSummary(workspace_id, "", "", {}, {}, {})
            plan_key, display_name, capabilities, quotas = plan
            start, end = monthly_period(at)
            rows = await conn.fetch(
                """
                SELECT kind, COALESCE(SUM(quantity), 0) AS used
                FROM trendcite.cloud_usage_event
                WHERE workspace_id=$1 AND occurred_at >= $2 AND occurred_at < $3
                GROUP BY kind
                ORDER BY kind
                """,
                workspace_id,
                start.isoformat(),
                end.isoformat(),
            )
            usage = {str(row["kind"]): int(row["used"]) for row in rows}
            return EntitlementSummary(
                workspace_id,
                plan_key,
                display_name,
                capabilities,
                quotas,
                usage,
            )

    async def _resolve_capability(
        self,
        conn: Connection,
        workspace_id: str,
        capability_key: str,
        *,
        at: datetime,
    ) -> EntitlementDecision:
        if capability_key not in CAPABILITIES:
            raise ValidationError("unknown entitlement capability")

        plan = await self._active_plan(conn, workspace_id, at=at)
        if plan is None:
            return EntitlementDecision(
                workspace_id=workspace_id,
                plan_key="",
                capability_key=capability_key,
                allowed=False,
                reason="missing_entitlement",
            )

        plan_key, _display_name, capabilities, quotas = plan
        enabled = bool(capabilities.get(capability_key, False))
        if not enabled:
            return EntitlementDecision(
                workspace_id=workspace_id,
                plan_key=plan_key,
                capability_key=capability_key,
                allowed=False,
                reason="capability_disabled",
            )

        quota = quotas.get(capability_key)
        if not isinstance(quota, dict):
            return EntitlementDecision(
                workspace_id=workspace_id,
                plan_key=plan_key,
                capability_key=capability_key,
                allowed=True,
                reason="allowed",
            )

        quota_kind = str(quota.get("kind") or "")
        quota_limit = quota.get("limit")
        if not quota_kind or not isinstance(quota_limit, int) or isinstance(quota_limit, bool):
            raise ValidationError("invalid entitlement quota configuration")
        if quota_limit < 0:
            raise ValidationError("entitlement quota limit must not be negative")

        start, end = monthly_period(at)
        used_value = await conn.fetchval(
            """
            SELECT COALESCE(SUM(quantity), 0)
            FROM trendcite.cloud_usage_event
            WHERE workspace_id=$1 AND kind=$2 AND occurred_at >= $3 AND occurred_at < $4
            """,
            workspace_id,
            quota_kind,
            start.isoformat(),
            end.isoformat(),
        )
        used = int(used_value or 0)
        remaining = max(quota_limit - used, 0)
        return EntitlementDecision(
            workspace_id=workspace_id,
            plan_key=plan_key,
            capability_key=capability_key,
            allowed=used < quota_limit,
            reason="allowed" if used < quota_limit else "quota_exhausted",
            quota_kind=quota_kind,
            quota_limit=quota_limit,
            used=used,
            remaining=remaining,
            period_start=start,
            period_end=end,
        )

    async def _active_plan(
        self,
        conn: Connection,
        workspace_id: str,
        *,
        at: datetime,
    ) -> tuple[str, str, dict[str, bool], dict[str, dict[str, Any]]] | None:
        instant = at.isoformat()
        row = await conn.fetchrow(
            """
            SELECT e.plan_key, p.display_name, p.capabilities, p.quotas
            FROM trendcite.cloud_workspace_entitlement AS e
            JOIN trendcite.cloud_entitlement_plan AS p ON p.plan_key=e.plan_key
            WHERE e.workspace_id=$1
              AND e.effective_from <= $2
              AND (e.effective_until='' OR e.effective_until > $2)
            ORDER BY e.effective_from DESC, e.entitlement_id DESC
            LIMIT 1
            """,
            workspace_id,
            instant,
        )
        if row is None:
            return None
        capabilities_raw = _json_object(row["capabilities"], "capabilities")
        quotas_raw = _json_object(row["quotas"], "quotas")
        capabilities = {str(key): bool(value) for key, value in capabilities_raw.items()}
        quotas: dict[str, dict[str, Any]] = {}
        for key, value in quotas_raw.items():
            if not isinstance(value, dict):
                raise ValidationError("quota entry must be an object")
            quotas[str(key)] = dict(value)
        return str(row["plan_key"]), str(row["display_name"]), capabilities, quotas


def _json_object(value: Any, name: str) -> dict[str, Any]:
    parsed = value if isinstance(value, dict) else json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValidationError(f"{name} must be a JSON object")
    return dict(parsed)
