"""Regression: selected and scheduled subtitle export cannot block Qt."""
from __future__ import annotations

import ast
from pathlib import Path


def _method(name):
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    root = ast.parse(source)
    main = next(n for n in root.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    method = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(source, method)


def test_selected_and_scheduled_srt_exports_use_worker():
    for name in ("export_selected_transcript_to_nas", "export_scheduled_transcripts_to_nas"):
        source = _method(name)
        assert "self._start_transcript_export_worker(" in source
        assert "_export_transcript_video_to_nas" not in source
        assert ".exists()" not in source
        assert ".read_text(" not in source


def test_srt_worker_has_independent_sqlite_and_thread():
    source = _method("_start_transcript_export_worker")
    assert "sqlite3.connect(str(db_path), timeout=15)" in source
    assert "conn.close()" in source
    assert "LocalToolWorker(task, self)" in source
    assert "run_transcript_export(" in source
    assert "worker.start()" in source


def test_srt_worker_quota_and_atomic_safeguards():
    code = Path("src/rg_youtube_control/transcript_export_worker.py").read_text(encoding="utf-8")
    assert "def run_transcript_export(" in code
    assert "quota_budget_status(conn)" in code
    assert "CAPTION_TRANSCRIPT_COST" in code
    assert "tmp.replace(path)" in code
    assert "max_new: int = 20" in code
    assert "_VIDEO_ID.fullmatch(video_id)" in code
