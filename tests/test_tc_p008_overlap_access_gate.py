"""Offline guard regression without importing Cloudflare's runtime."""

from __future__ import annotations

import ast
import hmac
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _guard():
    source = Path("deploy/cloudflare/src/main.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    node = next(
        n
        for n in module.body
        if isinstance(n, ast.FunctionDef) and n.name == "_tc_p008_overlap_authorized"
    )
    namespace: dict[str, Any] = {"Any": Any, "hmac": hmac}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<guard>", "exec"), namespace)
    return namespace[node.name]


def test_nonprod_probe_denied_by_default() -> None:
    guard = _guard()
    env = SimpleNamespace(TRENDCITE_RUNTIME_ROLE="trendcite_nonprod_runtime")
    request = SimpleNamespace(method="POST", headers={"Authorization": "Bearer " + "x" * 40})
    assert not guard(env, request)


def test_nonprod_probe_requires_all_guards() -> None:
    guard = _guard()
    key = "a" * 40
    env = SimpleNamespace(
        TRENDCITE_RUNTIME_ROLE="trendcite_nonprod_runtime",
        TRENDCITE_TC_P008_BACKEND_OVERLAP="nonprod-enabled",
        TRENDCITE_TC_P008_OVERLAP_TOKEN=key,
    )
    request = SimpleNamespace(method="POST", headers={"Authorization": "Bearer " + key})
    assert guard(env, request)
    assert not guard(
        SimpleNamespace(**{**vars(env), "TRENDCITE_RUNTIME_ROLE": "trendcite_prod_runtime"}),
        request,
    )
    assert not guard(env, SimpleNamespace(method="GET", headers=request.headers))
    assert not guard(
        env, SimpleNamespace(method="POST", headers={"Authorization": "Bearer invalid"})
    )
    assert not guard(
        SimpleNamespace(**{**vars(env), "TRENDCITE_TC_P008_BACKEND_OVERLAP": "off"}), request
    )
