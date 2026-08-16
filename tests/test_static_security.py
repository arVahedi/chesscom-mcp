from __future__ import annotations

import ast
from pathlib import Path


def test_runtime_has_no_forbidden_capabilities() -> None:
    root = Path("src/chess_com_mcp")
    forbidden_imports = {"subprocess", "pickle", "marshal"}
    forbidden_calls = {"eval", "exec"}
    violations: list[str] = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_imports:
                        violations.append(f"{path}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden_imports:
                    violations.append(f"{path}:{node.lineno}: from {node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                violations.append(f"{path}:{node.lineno}: {node.func.id}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os" and node.func.attr == "system":
                    violations.append(f"{path}:{node.lineno}: os.system")
    assert violations == []
