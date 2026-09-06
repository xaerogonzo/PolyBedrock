"""polybedrock-core is Windows platform code and must stay UI-free.

The architectural boundary that keeps the shared substrate from degrading into a
mixture of Win32, SQLite, PowerShell, colours and widgets. It is a one-way
dependency: polybedrock-ui may import polybedrock, never the reverse.
"""
from __future__ import annotations

import ast
import pathlib

CORE = pathlib.Path(__file__).resolve().parents[1] / "src" / "polybedrock"

#: Importing any of these from core would mean UI code had leaked into it.
FORBIDDEN = {"customtkinter", "tkinter", "polybedrock.ui"}


def _imported_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_imports_no_ui_toolkit():
    offenders = {}
    for py in CORE.glob("*.py"):
        bad = {n for n in _imported_names(py)
               if any(n == f or n.startswith(f + ".") for f in FORBIDDEN)}
        if bad:
            offenders[py.name] = sorted(bad)
    assert not offenders, f"UI imports leaked into polybedrock-core: {offenders}"


def test_core_ships_no_namespace_init():
    """`polybedrock` is a PEP 420 namespace package shared by two distributions.
    An __init__.py here would shadow polybedrock-ui's contribution and break
    `import polybedrock.ui.theme` in a way that only shows up once both are
    installed."""
    assert not (CORE / "__init__.py").exists()
