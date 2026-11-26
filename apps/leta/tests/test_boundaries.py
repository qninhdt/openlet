"""Architectural boundary checks for Leta Layer 1 vs Layer 2 separation of concerns."""

from __future__ import annotations

import ast
from pathlib import Path

LETA_SRC = Path(__file__).resolve().parents[1] / "src" / "leta"


def _iter_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    rel_parts = path.relative_to(LETA_SRC).parts
    pkg_parts = list(rel_parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                up = node.level - 1
                base = pkg_parts[: len(pkg_parts) - up] if up else list(pkg_parts)
                mod = ".".join(["leta", *base, *([node.module] if node.module else [])])
            else:
                mod = node.module or ""
            found.append(mod)
    return found


def test_layer1_has_no_langchain_langgraph_or_runtime_imports() -> None:
    forbidden_prefixes = ("langchain", "langgraph", "leta.runtime")
    violations: list[str] = []
    for path in sorted(LETA_SRC.rglob("*.py")):
        rel = path.relative_to(LETA_SRC).as_posix()
        if rel.startswith("runtime/"):
            continue
        for mod in _iter_imports(path):
            # RuntimeActivities in orchestration/activities.py is the sole Temporal -> Layer 2 entrypoint.
            if rel == "orchestration/activities.py" and mod == "leta.runtime.runner":
                continue
            if mod.startswith(forbidden_prefixes):
                violations.append(f"{rel} imports {mod}")
    assert not violations, "Layer 1 boundary violations:\n" + "\n".join(violations)


def test_layer2_runtime_has_no_temporal_workflow_or_raw_sql() -> None:
    forbidden_prefixes = (
        "temporalio",
        "leta.orchestration",
        "leta.hitl.workflow",
        "leta.schedules.workflow",
    )
    violations: list[str] = []
    for path in sorted((LETA_SRC / "runtime").rglob("*.py")):
        rel = path.relative_to(LETA_SRC).as_posix()
        for mod in _iter_imports(path):
            if mod.startswith(forbidden_prefixes):
                violations.append(f"{rel} imports {mod}")
        text = path.read_text(encoding="utf-8")
        if ".db.connection(" in text:
            violations.append(f"{rel} opens raw DB connection directly")
    assert not violations, "Layer 2 boundary violations:\n" + "\n".join(violations)
