from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from trendcite.cloud.auth import AuthenticationError, AuthenticationUpstreamError, AuthPrincipal
from trendcite.cloud.customer_api import (
    ApiRequest,
    CustomerApi,
    is_customer_api_path,
    mutations_enabled,
)
from trendcite.cloud.db.postgres_access import AuthorizedWorkspace
from trendcite.cloud.errors import NotFoundError, PermissionDeniedError

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
TOKENS = {"token-a": "user-a", "token-v": "user-v"}


class FakeAuth:
    def __init__(self, upstream_down: bool = False) -> None:
        self.upstream_down = upstream_down

    async def authenticate(self, authorization: str | None) -> AuthPrincipal:
        if self.upstream_down:
            raise AuthenticationUpstreamError("down")
        scheme, _, token = str(authorization or "").partition(" ")
        if scheme.lower() != "bearer" or token not in TOKENS:
            raise AuthenticationError("bad")
        return AuthPrincipal(principal_id=TOKENS[token], email=f"{TOKENS[token]}@example.test")


@dataclass
class FakeStore:
    members: dict[tuple[str, str], str] = field(
        default_factory=lambda: {("user-a", "ws-a"): "owner", ("user-v", "ws-a"): "viewer"}
    )
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    def _role(self, principal: str, workspace: str, write: bool = False) -> str:
        role = self.members.get((principal, workspace))
        if role is None:
            raise NotFoundError("workspace not found")
        if write and role == "viewer":
            raise PermissionDeniedError("read only")
        return role

    async def list_workspaces(self, principal_id: str) -> tuple[AuthorizedWorkspace, ...]:
        return tuple(
            AuthorizedWorkspace(ws, ws, ws.upper(), role, NOW)
            for (principal, ws), role in self.members.items()
            if principal == principal_id
        )

    async def get_workspace(
        self, principal_id: str, workspace_id: str
    ) -> AuthorizedWorkspace | None:
        role = self.members.get((principal_id, workspace_id))
        return (
            None
            if role is None
            else AuthorizedWorkspace(workspace_id, workspace_id, workspace_id.upper(), role, NOW)
        )

    async def list_watchlists(self, p: str, ws: str) -> list[dict[str, Any]]:
        self._role(p, ws)
        return [{"watchlist_id": "wl-a", "name": "AI", "latest_version": {"version_number": 1}}]

    async def get_watchlist(self, p: str, ws: str, watchlist_id: str) -> dict[str, Any]:
        self._role(p, ws)
        if watchlist_id != "wl-a":
            raise NotFoundError("watchlist not found")
        return {"watchlist_id": watchlist_id, "name": "AI"}

    async def create_watchlist(self, p: str, ws: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("create_watchlist", (p, ws), kw))
        self._role(p, ws, True)
        return {"watchlist_id": "wl-new", "name": kw["name"]}

    async def append_watchlist_version(
        self, p: str, ws: str, wl: str, **kw: Any
    ) -> tuple[dict[str, Any], bool]:
        self.calls.append(("append_watchlist_version", (p, ws, wl), kw))
        self._role(p, ws, True)
        return {"watchlist_id": wl, "version_number": kw["expected_version_number"] + 1}, True

    async def list_radars(self, p: str, ws: str) -> list[dict[str, Any]]:
        self._role(p, ws)
        return []

    async def get_radar(self, p: str, ws: str, radar_id: str) -> dict[str, Any]:
        self._role(p, ws)
        return {"radar_id": radar_id}

    async def create_radar(self, p: str, ws: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("create_radar", (p, ws), kw))
        self._role(p, ws, True)
        return {"radar_id": "r-new"}

    async def append_radar_version(
        self, p: str, ws: str, radar_id: str, **kw: Any
    ) -> tuple[dict[str, Any], bool]:
        self.calls.append(("append_radar_version", (p, ws, radar_id), kw))
        self._role(p, ws, True)
        return {"radar_id": radar_id}, True

    async def list_runs(self, p: str, ws: str, **kw: Any) -> list[dict[str, Any]]:
        self.calls.append(("list_runs", (p, ws), kw))
        self._role(p, ws)
        return []

    async def get_run(self, p: str, ws: str, run_id: str) -> dict[str, Any]:
        self._role(p, ws)
        return {"run_id": run_id}

    async def list_signals(self, p: str, ws: str, **kw: Any) -> list[dict[str, Any]]:
        self._role(p, ws)
        return []

    async def get_signal_history(self, p: str, ws: str, signal_id: str) -> dict[str, Any]:
        self._role(p, ws)
        return {"signal_id": signal_id, "history": []}

    async def list_alerts(self, p: str, ws: str, **kw: Any) -> list[dict[str, Any]]:
        self._role(p, ws)
        return [{"alert_id": "a1", "body": "<img src=x onerror=alert(1)>"}]

    async def list_digests(self, p: str, ws: str, **kw: Any) -> list[dict[str, Any]]:
        self._role(p, ws)
        return []

    async def get_digest(self, p: str, ws: str, digest_id: str) -> dict[str, Any]:
        self._role(p, ws)
        return {"digest_id": digest_id}


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def request(
    api: CustomerApi, method: str, path: str, *, token: str | None = "token-a", body: Any = None
) -> Any:
    return _run(
        api.handle(
            ApiRequest(
                method=method,
                path=path,
                authorization=None if token is None else f"Bearer {token}",
                content_type="application/json",
                body=b"" if body is None else json.dumps(body).encode(),
            )
        )
    )


def make(*, mutations: bool = True, auth: Any = None) -> tuple[CustomerApi, FakeStore]:
    store = FakeStore()
    return CustomerApi(
        auth or FakeAuth(), store, mutations_enabled=mutations, clock=lambda: NOW
    ), store


def test_missing_and_invalid_bearer_are_401() -> None:
    api, _ = make()
    assert request(api, "GET", "/api/v1/session", token=None).status == 401
    assert request(api, "GET", "/api/v1/session", token="forged").status == 401


def test_auth_upstream_failure_is_503() -> None:
    api, _ = make(auth=FakeAuth(upstream_down=True))
    assert request(api, "GET", "/api/v1/session").status == 503


def test_session_lists_only_authorized_workspaces() -> None:
    api, _ = make()
    response = request(api, "GET", "/api/v1/session")
    assert response.status == 200
    assert [w["workspace_id"] for w in response.payload["workspaces"]] == ["ws-a"]


def test_cross_tenant_workspace_is_404_without_existence_leakage() -> None:
    api, _ = make()
    foreign = request(api, "GET", "/api/v1/workspaces/ws-b/watchlists")
    missing = request(api, "GET", "/api/v1/workspaces/nope/watchlists")
    assert foreign.status == missing.status == 404
    assert foreign.payload == missing.payload == {"ok": False, "error": "not_found"}


def test_viewer_can_read_but_cannot_write() -> None:
    api, _ = make()
    assert request(api, "GET", "/api/v1/workspaces/ws-a/watchlists", token="token-v").status == 200
    denied = request(
        api,
        "POST",
        "/api/v1/workspaces/ws-a/watchlists",
        token="token-v",
        body={"name": "x", "include_terms": ["ai"]},
    )
    assert (denied.status, denied.payload["error"]) == (403, "forbidden")


def test_mutations_fail_closed_before_store_write() -> None:
    api, store = make(mutations=False)
    response = request(
        api,
        "POST",
        "/api/v1/workspaces/ws-a/watchlists",
        body={"name": "x", "include_terms": ["ai"]},
    )
    assert (response.status, response.payload["error"]) == (403, "mutations_disabled")
    assert store.calls == []


def test_create_radar_uses_watchlist_ids_contract() -> None:
    api, store = make()
    response = request(
        api,
        "POST",
        "/api/v1/workspaces/ws-a/radars",
        body={
            "name": "Radar",
            "watchlist_ids": ["wl-a"],
            "sources": ["github"],
            "niche": [],
            "top": 5,
        },
    )
    assert response.status == 201
    assert store.calls[-1][2]["watchlist_ids"] == ["wl-a"]


def test_append_uses_expected_version_number() -> None:
    api, store = make()
    response = request(
        api,
        "POST",
        "/api/v1/workspaces/ws-a/watchlists/wl-a/versions",
        body={"base_version_number": 1, "include_terms": ["ai"]},
    )
    assert response.status == 201
    assert store.calls[-1][2]["expected_version_number"] == 1
    assert response.payload["created"] is True


def test_untrusted_alert_body_remains_data() -> None:
    api, _ = make()
    response = request(api, "GET", "/api/v1/workspaces/ws-a/alerts")
    assert response.payload["alerts"][0]["body"] == "<img src=x onerror=alert(1)>"


def test_mutation_enablement_requires_exact_nonprod_flag() -> None:
    env = SimpleNamespace(
        TRENDCITE_CUSTOMER_MUTATIONS="nonprod-enabled",
        TRENDCITE_RUNTIME_ROLE="trendcite_nonprod_runtime",
    )
    assert mutations_enabled(env)
    assert not mutations_enabled(
        SimpleNamespace(
            TRENDCITE_CUSTOMER_MUTATIONS="nonprod-enabled",
            TRENDCITE_RUNTIME_ROLE="trendcite_runtime",
        )
    )


def test_customer_api_path_predicate() -> None:
    assert is_customer_api_path("/api/v1/session")
    assert not is_customer_api_path("/api/v10/x")
