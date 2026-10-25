"""Regression: startup network probes must never execute in Qt callbacks."""
from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "src/rg_youtube_control/ui.py"


def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    window = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
    )
    return next(
        node for node in window.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _called(method: ast.FunctionDef, name: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
        for node in ast.walk(method)
    )


def test_silent_update_is_threaded():
    method = _method("check_for_updates_silent")
    assert _called(method, "check_for_update")
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Thread"
        for node in ast.walk(method)
    )


def test_free_tool_probe_is_threaded():
    method = _method("refresh_free_tools_status")
    assert _called(method, "probe_free_tools")
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Thread"
        for node in ast.walk(method)
    )


def test_nas_worker_catches_probe_errors():
    method = _method("_start_nas_srt_index")
    assert any(
        isinstance(node, ast.Try)
        and any(
            isinstance(handler.type, ast.Name)
            and handler.type.id == "Exception"
            for handler in node.handlers
        )
        for node in ast.walk(method)
    )
