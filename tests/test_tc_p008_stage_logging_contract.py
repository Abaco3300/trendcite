"""Offline TC-P008 diagnostic stage contract; does not invoke the Worker."""

from __future__ import annotations

import ast
from pathlib import Path


def test_tc_p008_diagnostic_has_bounded_stage_labels_and_safe_response() -> None:
    tree = ast.parse(Path("deploy/cloudflare/src/main.py").read_text(encoding="utf-8"))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "path"
        and any(
            isinstance(c, ast.Name) and c.id == "TC_P008_OVERLAP_PATH" for c in node.comparators
        )
    ]
    assert len(matches) == 1
    branch = next(
        stmt
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and node.test is matches[0]
        for stmt in [node]
    )
    stage_values = {
        n.value.value
        for n in ast.walk(branch)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "stage" for t in n.targets)
        and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    }
    assert stage_values == {"initialize", "backend_overlap", "transaction_contention"}
    handlers = [n for n in ast.walk(branch) if isinstance(n, ast.ExceptHandler)]
    assert len(handlers) == 1
    handler = handlers[0]
    dumped = ast.dump(handler)
    assert "'stage'" in dumped and "'error_type'" in dumped
    assert "overlap_probe_failed" in dumped
    assert "exc.args" not in dumped
    assert "traceback" not in dumped
    assert "Authorization" not in dumped
