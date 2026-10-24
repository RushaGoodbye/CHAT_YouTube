"""Verify Qt background tasks do not capture the GUI SQLite connection."""
import ast
from pathlib import Path


def test_local_background_tasks_do_not_use_gui_connection():
    tree = ast.parse(
        Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    )
    main_window = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
    )
    for method in main_window.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        for sub in ast.walk(method):
            if not isinstance(sub, ast.FunctionDef):
                continue
            if sub is method or sub.name not in ("task", "resilient_task", "target"):
                continue
            captured = [
                node.lineno for node in ast.walk(sub)
                if isinstance(node, ast.Attribute)
                and node.attr == "conn"
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
            ]
            assert not captured, (
                f"{method.name}.{sub.name} touches UI-owned SQLite connection "
                f"at {captured}"
            )
