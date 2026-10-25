"""Regression: checking hundreds of NAS captions must never block Qt."""
from __future__ import annotations

import ast
from pathlib import Path


def _method(name: str) -> str:
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "rg_youtube_control" / "ui.py"
    ).read_text(encoding="utf-8")
    root = ast.parse(source)
    for node in ast.walk(root):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Method absent: {name}")


def test_optimization_table_never_stats_nas_per_video():
    source = _method("reload_optimization_queue")
    assert "_nas_transcript_ids" in source
    assert "QTimer.singleShot(0, self._refresh_transcript_availability_async)" in source
    assert 'f"{row[\'video_id\']}.srt").exists()' not in source
    assert "cached_transcript_ids" in source


def test_transcript_availability_scan_uses_worker_not_qt():
    source = _method("_refresh_transcript_availability_async")
    assert "LocalToolWorker(task, self)" in source
    assert "with os.scandir(path)" in source
    assert ".stat(" not in source
    assert ".is_file(" not in source
    assert "worker.succeeded.connect(succeeded)" in source
    assert "worker.failed.connect(failed)" in source
    assert "worker.start()" in source


def test_cached_transcript_badges_are_repainted_without_full_queue_refresh():
    source = _method("_paint_transcript_availability")
    assert "table.rowCount()" in source
    assert 'table.item(row_index, 3)' in source
    assert 'table.item(row_index, 7)' in source
    assert 'badge.setText("NAS" if visible else "")' in source
    assert "reload_optimization_queue(" not in source
