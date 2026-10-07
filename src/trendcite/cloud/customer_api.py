"""Transport-neutral customer API for the TrendCite Cloudflare Worker.

The Worker adapts a Fetch ``Request`` into :class:`ApiRequest` and an
:class:`ApiResponse` back into a ``Response``; everything that decides *who may see
what* lives here so it can be tested without the Workers runtime.

Order of checks, each one fail-closed:

1. route match (unknown path -> 404, known path with wrong method -> 405);
2. identity: Supabase Auth bearer token -> principal id (401 / 503);
3. mutation gate: writes require ``TRENDCITE_CUSTOMER_MUTATIONS=nonprod-enabled``
   on a nonprod runtime role (403 ``mutations_disabled``), checked before any
   database access so a disabled gate cannot be used to probe workspaces;
4. membership, inside the store's transaction (404 for non-members, identical to a
   missing workspace; 403 for viewer writes).

Error payloads carry a stable code and nothing else: no exception text, no SQL, no
token. Logs carry the event name and exception class only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import parse_qs

from .auth import AuthenticationError, AuthenticationUpstreamError, AuthPrincipal
from .db.postgres_access import AuthorizedWorkspace
from .errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError

MUTATIONS_FLAG = "TRENDCITE_CUSTOMER_MUTATIONS"
MUTATIONS_ENABLED_VALUE = "nonprod-enabled"
MAX_BODY_BYTES = 64 * 1024
MAX_LIST_ITEMS = 200

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

_ID = r"[A-Za-z0-9_.:-]{1,200}"


class Authenticator(Protocol):
    async def authenticate(self, authorization: str | None) -> AuthPrincipal: ...


class EntitlementStore(Protocol):
    async def summary_for_principal(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        at: datetime,
    ) -> Any: ...


class CustomerStore(Protocol):
    async def list_workspaces(self, principal_id: str) -> tuple[AuthorizedWorkspace, ...]: ...
    async def get_workspace(
        self, principal_id: str, workspace_id: str
    ) -> AuthorizedWorkspace | None: ...
    async def list_watchlists(self, principal_id: str, workspace_id: str) -> Any: ...
    async def get_watchlist(
        self, principal_id: str, workspace_id: str, watchlist_id: str
    ) -> Any: ...
    async def create_watchlist(self, principal_id: str, workspace_id: str, **kw: Any) -> Any: ...
    async def append_watchlist_version(
        self, principal_id: str, workspace_id: str, watchlist_id: str, **kw: Any
    ) -> Any: ...
    async def list_radars(self, principal_id: str, workspace_id: str) -> Any: ...
    async def get_radar(self, principal_id: str, workspace_id: str, radar_id: str) -> Any: ...
    async def create_radar(self, principal_id: str, workspace_id: str, **kw: Any) -> Any: ...
    async def append_radar_version(
        self, principal_id: str, workspace_id: str, radar_id: str, **kw: Any
    ) -> Any: ...
    async def list_runs(self, principal_id: str, workspace_id: str, **kw: Any) -> Any: ...
    async def get_run(self, principal_id: str, workspace_id: str, run_id: str) -> Any: ...
    async def list_signals(self, principal_id: str, workspace_id: str, **kw: Any) -> Any: ...
    async def get_signal_history(
        self, principal_id: str, workspace_id: str, signal_id: str
    ) -> Any: ...
    async def list_alerts(self, principal_id: str, workspace_id: str, **kw: Any) -> Any: ...
    async def list_digests(self, principal_id: str, workspace_id: str, **kw: Any) -> Any: ...
    async def get_digest(self, principal_id: str, workspace_id: str, digest_id: str) -> Any: ...


@dataclass(frozen=True)
class ApiRequest:
    method: str
    path: str
    query: str = ""
    authorization: str | None = None
    content_type: str = ""
    body: bytes = b""


@dataclass(frozen=True)
class ApiResponse:
    status: int
    payload: dict[str, Any]
    headers: Mapping[str, str] = field(default_factory=lambda: dict(SECURITY_HEADERS))


class _HttpError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def mutations_enabled(env: Any) -> bool:
    """True only for an explicit nonprod opt-in on a nonprod runtime role."""

    flag = str(getattr(env, MUTATIONS_FLAG, "") or "").strip()
    role = str(getattr(env, "TRENDCITE_RUNTIME_ROLE", "") or "").strip()
    return flag == MUTATIONS_ENABLED_VALUE and "nonprod" in role


Handler = Callable[["_Context"], Awaitable[Any]]


@dataclass(frozen=True)
class _Route:
    method: str
    pattern: re.Pattern[str]
    handler_name: str
    mutation: bool = False


def _route(method: str, template: str, handler_name: str, *, mutation: bool = False) -> _Route:
    regex = "^" + re.sub(r"\{(\w+)\}", rf"(?P<\1>{_ID})", template) + "/?$"
    return _Route(method, re.compile(regex), handler_name, mutation)


_WS = "/api/v1/workspaces/{workspace_id}"
ROUTES: tuple[_Route, ...] = (
    _route("GET", "/api/v1/session", "session"),
    _route("GET", "/api/v1/workspaces", "workspaces"),
    _route("GET", _WS, "workspace"),
    _route("GET", _WS + "/entitlements", "entitlements"),
    _route("GET", _WS + "/usage", "usage"),
    _route("GET", _WS + "/watchlists", "list_watchlists"),
    _route("POST", _WS + "/watchlists", "create_watchlist", mutation=True),
    _route("GET", _WS + "/watchlists/{watchlist_id}", "get_watchlist"),
    _route(
        "POST",
        _WS + "/watchlists/{watchlist_id}/versions",
        "append_watchlist_version",
        mutation=True,
    ),
    _route("GET", _WS + "/radars", "list_radars"),
    _route("POST", _WS + "/radars", "create_radar", mutation=True),
    _route("GET", _WS + "/radars/{radar_id}", "get_radar"),
    _route("POST", _WS + "/radars/{radar_id}/versions", "append_radar_version", mutation=True),
    _route("GET", _WS + "/runs", "list_runs"),
    _route("GET", _WS + "/runs/{run_id}", "get_run"),
    _route("GET", _WS + "/signals", "list_signals"),
    _route("GET", _WS + "/signals/{signal_id}/history", "signal_history"),
    _route("GET", _WS + "/alerts", "list_alerts"),
    _route("GET", _WS + "/digests", "list_digests"),
    _route("GET", _WS + "/digests/{digest_id}", "get_digest"),
)


def is_customer_api_path(path: str) -> bool:
    return path == "/api/v1" or path.startswith("/api/v1/")


@dataclass(frozen=True)
class _Context:
    principal: AuthPrincipal
    params: dict[str, str]
    query: dict[str, str]
    body: dict[str, Any]


class CustomerApi:
    def __init__(
        self,
        auth: Authenticator,
        store: CustomerStore,
        *,
        mutations_enabled: bool,
        entitlement_store: EntitlementStore | None = None,
        clock: Callable[[], datetime] | None = None,
        log: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._auth = auth
        self._store = store
        self._entitlement_store = entitlement_store
        self._mutations_enabled = mutations_enabled
        self._clock = clock or (lambda: datetime.now(UTC).replace(microsecond=0))
        self._log = log or (lambda _event: None)

    async def handle(self, request: ApiRequest) -> ApiResponse:
        try:
            route, params = self._match(request.method.upper(), request.path)
            principal = await self._authenticate(request.authorization)
            if route.mutation and not self._mutations_enabled:
                raise _HttpError(403, "mutations_disabled")
            ctx = _Context(
                principal=principal,
                params=params,
                query=_query(request.query),
                body=_body(request) if route.mutation else {},
            )
            handler: Handler = getattr(self, "_h_" + route.handler_name)
            status = 201 if route.mutation else 200
            return _ok(status, principal, await handler(ctx))
        except _HttpError as exc:
            return _error(exc.status, exc.code)
        except PermissionDeniedError:
            return _error(403, "forbidden")
        except ConflictError:
            return _error(409, "conflict")
        except ValidationError as exc:
            return _error(400, "invalid_request", detail=_safe_validation(exc))
        except NotFoundError:
            return _error(404, "not_found")
        except (OSError, TimeoutError, ConnectionError) as exc:
            self._log({"event": "trendcite.customer_api.unavailable", "error_type": _t(exc)})
            return _error(503, "unavailable")
        except Exception as exc:
            self._log({"event": "trendcite.customer_api.error", "error_type": _t(exc)})
            return _error(500, "internal_error")

    # ----------------------------------------------------------------- plumbing

    def _match(self, method: str, path: str) -> tuple[_Route, dict[str, str]]:
        allowed = False
        for route in ROUTES:
            found = route.pattern.match(path)
            if found is None:
                continue
            if route.method == method:
                return route, dict(found.groupdict())
            allowed = True
        if allowed:
            raise _HttpError(405, "method_not_allowed")
        raise _HttpError(404, "not_found")

    async def _authenticate(self, authorization: str | None) -> AuthPrincipal:
        try:
            return await self._auth.authenticate(authorization)
        except AuthenticationError as exc:
            raise _HttpError(401, "unauthorized") from exc
        except AuthenticationUpstreamError as exc:
            raise _HttpError(503, "auth_unavailable") from exc

    # ----------------------------------------------------------------- handlers

    async def _h_session(self, ctx: _Context) -> dict[str, Any]:
        workspaces = await self._store.list_workspaces(ctx.principal.principal_id)
        return {
            "email": ctx.principal.email,
            "mutations_enabled": self._mutations_enabled,
            "workspaces": [w.to_dict() for w in workspaces],
        }

    async def _h_workspaces(self, ctx: _Context) -> dict[str, Any]:
        workspaces = await self._store.list_workspaces(ctx.principal.principal_id)
        return {"workspaces": [w.to_dict() for w in workspaces]}

    async def _h_workspace(self, ctx: _Context) -> dict[str, Any]:
        workspace = await self._store.get_workspace(
            ctx.principal.principal_id, ctx.params["workspace_id"]
        )
        if workspace is None:
            raise NotFoundError("workspace not found")
        return {"workspace": workspace.to_dict()}

    async def _h_entitlements(self, ctx: _Context) -> dict[str, Any]:
        if self._entitlement_store is None:
            raise _HttpError(503, "entitlements_unavailable")
        p, ws = _scope(ctx)
        summary = await self._entitlement_store.summary_for_principal(p, ws, at=self._clock())
        return {"entitlements": summary.to_dict()}

    async def _h_usage(self, ctx: _Context) -> dict[str, Any]:
        if self._entitlement_store is None:
            raise _HttpError(503, "entitlements_unavailable")
        p, ws = _scope(ctx)
        summary = await self._entitlement_store.summary_for_principal(p, ws, at=self._clock())
        payload = summary.to_dict()
        return {
            "workspace_id": ws,
            "plan_key": payload["plan_key"],
            "quotas": payload["quotas"],
            "usage": payload["usage"],
        }

    async def _h_list_watchlists(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        return {"watchlists": await self._store.list_watchlists(p, ws)}

    async def _h_get_watchlist(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        return {"watchlist": await self._store.get_watchlist(p, ws, ctx.params["watchlist_id"])}

    async def _h_create_watchlist(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        body = ctx.body
        watchlist = await self._store.create_watchlist(
            p,
            ws,
            name=_str(body, "name"),
            now=self._clock(),
            **_watchlist_terms(body),
        )
        return {"watchlist": watchlist}

    async def _h_append_watchlist_version(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        body = ctx.body
        watchlist, created = await self._store.append_watchlist_version(
            p,
            ws,
            ctx.params["watchlist_id"],
            expected_version_number=_base_version(body),
            now=self._clock(),
            **_watchlist_terms(body),
        )
        return {"watchlist": watchlist, "created": created}

    async def _h_list_radars(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        return {"radars": await self._store.list_radars(p, ws)}

    async def _h_get_radar(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        return {"radar": await self._store.get_radar(p, ws, ctx.params["radar_id"])}

    async def _h_create_radar(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        body = ctx.body
        radar = await self._store.create_radar(
            p,
            ws,
            name=_str(body, "name"),
            now=self._clock(),
            **_radar_config(body),
        )
        return {"radar": radar}

    async def _h_append_radar_version(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        body = ctx.body
        radar, created = await self._store.append_radar_version(
            p,
            ws,
            ctx.params["radar_id"],
            expected_version_number=_base_version(body),
            now=self._clock(),
            **_radar_config(body),
        )
        return {"radar": radar, "created": created}

    async def _h_list_runs(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        runs = await self._store.list_runs(p, ws, **_list_filters(ctx.query))
        return {"runs": runs}

    async def _h_get_run(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        return {"run": await self._store.get_run(p, ws, ctx.params["run_id"])}

    async def _h_list_signals(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        signals = await self._store.list_signals(p, ws, **_list_filters(ctx.query))
        return {"signals": signals}

    async def _h_signal_history(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        history = await self._store.get_signal_history(p, ws, ctx.params["signal_id"])
        return {"signal": history}

    async def _h_list_alerts(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        alerts = await self._store.list_alerts(p, ws, **_list_filters(ctx.query))
        return {"alerts": alerts}

    async def _h_list_digests(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        digests = await self._store.list_digests(p, ws, **_list_filters(ctx.query))
        return {"digests": digests}

    async def _h_get_digest(self, ctx: _Context) -> dict[str, Any]:
        p, ws = _scope(ctx)
        return {"digest": await self._store.get_digest(p, ws, ctx.params["digest_id"])}


# ------------------------------------------------------------------------ helpers


def _ok(status: int, principal: AuthPrincipal, data: dict[str, Any]) -> ApiResponse:
    return ApiResponse(status, {"ok": True, "principal_id": principal.principal_id, **data})


def _error(status: int, code: str, *, detail: str = "") -> ApiResponse:
    payload: dict[str, Any] = {"ok": False, "error": code}
    if detail:
        payload["detail"] = detail
    return ApiResponse(status, payload)


def _t(exc: BaseException) -> str:
    return type(exc).__name__


def _safe_validation(exc: ValidationError) -> str:
    # Domain validation messages describe the caller's own input; bound them anyway.
    return " ".join(str(exc).split())[:200]


def _scope(ctx: _Context) -> tuple[str, str]:
    return ctx.principal.principal_id, ctx.params["workspace_id"]


def _query(raw: str) -> dict[str, str]:
    parsed = parse_qs(raw or "", keep_blank_values=False, max_num_fields=20)
    return {key: values[0] for key, values in parsed.items() if values}


def _limit(query: Mapping[str, str]) -> int | None:
    raw = query.get("limit")
    if raw is None:
        return None
    if not raw.isdigit():
        raise ValidationError("limit must be a positive integer")
    return int(raw)


def _list_filters(query: Mapping[str, str]) -> dict[str, Any]:
    radar_id = query.get("radar_id") or None
    if radar_id is not None and not re.fullmatch(_ID, radar_id):
        raise ValidationError("radar_id is malformed")
    return {"radar_id": radar_id, "limit": _limit(query)}


def _body(request: ApiRequest) -> dict[str, Any]:
    if len(request.body) > MAX_BODY_BYTES:
        raise _HttpError(413, "payload_too_large")
    if request.content_type.split(";")[0].strip().lower() != "application/json":
        raise _HttpError(415, "unsupported_media_type")
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _HttpError(400, "invalid_json") from exc
    if not isinstance(data, dict):
        raise _HttpError(400, "invalid_json")
    return data


def _str(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be a string")
    return value


def _str_list(body: Mapping[str, Any], key: str, *, required: bool = False) -> list[str]:
    value = body.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(f"{key} must be a list of strings")
    if len(value) > MAX_LIST_ITEMS:
        raise ValidationError(f"{key} must contain at most {MAX_LIST_ITEMS} entries")
    return list(value)


def _base_version(body: Mapping[str, Any]) -> int:
    value = body.get("base_version_number")
    # Required for appends so a stale editor gets 409 instead of silently winning.
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValidationError("base_version_number must be a positive integer")
    return value


def _watchlist_terms(body: Mapping[str, Any]) -> dict[str, Any]:
    mode = body.get("match_mode", "any")
    if not isinstance(mode, str):
        raise ValidationError("match_mode must be a string")
    return {
        "include_terms": _str_list(body, "include_terms", required=True),
        "exclude_terms": _str_list(body, "exclude_terms"),
        "match_mode": mode,
        "entities": _str_list(body, "entities"),
        "domains": _str_list(body, "domains"),
    }


def _radar_config(body: Mapping[str, Any]) -> dict[str, Any]:
    top = body.get("top", 5)
    if not isinstance(top, int) or isinstance(top, bool):
        raise ValidationError("top must be an integer")
    return {
        "watchlist_ids": _str_list(body, "watchlist_ids", required=True),
        "sources": _str_list(body, "sources", required=True),
        "niche": _str_list(body, "niche"),
        "top": top,
    }
