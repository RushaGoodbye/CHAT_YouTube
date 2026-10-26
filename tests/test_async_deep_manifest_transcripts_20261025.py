"""Deep-review manifest SRT export is bounded, atomic and never blocks Qt."""
from __future__ import annotations

import ast
import json
import os
import sqlite3
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _conn(tmp_path):
    from rg_youtube_control.db import connect
    conn = connect(tmp_path / "rg_youtube_control.db")
    for video_id, profile in [
        ("MEitKm687xo", "main"),
        ("uRGjZXVmD6w", "main"),
        ("OaK9ctTJ9i0", "live"),
    ]:
        conn.execute(
            "INSERT INTO videos(video_id,profile,title,last_synced_at) "
            "VALUES(?,?,?,?)",
            (video_id, profile, "Матеріал для перевірки", "2026-10-25"),
        )
    conn.commit()
    return conn


def _manifest(tmp_path, items):
    path = tmp_path / "NAS" / "PACKAGES" / "deep_review_main.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"items": items, "keep": "operator-note"}),
        encoding="utf-8",
    )
    return path


class FakeClient:
    calls = []

    def __init__(self, profile):
        assert profile == "main"

    def download_best_caption_srt(self, video_id):
        self.calls.append(video_id)
        return (
            {"snippet": {"language": "uk"}},
            "1\n00:00:01,000 --> 00:00:02,000\nДоказовий текст",
        )


def test_deep_manifest_worker_downloads_only_valid_same_profile_ids(tmp_path):
    from rg_youtube_control.transcript_export_worker import (
        run_deep_manifest_transcript_export,
    )
    conn = _conn(tmp_path)
    path = _manifest(tmp_path, [
        {"video_id": "MEitKm687xo"},
        {"video_id": "MEitKm687xo"},
        {"video_id": "OaK9ctTJ9i0"},
        {"video_id": "not-a-valid-id"},
    ])
    FakeClient.calls = []
    try:
        result = run_deep_manifest_transcript_export(
            conn, profile="main", manifest_path=path,
            target_dir=tmp_path / "NAS" / "SRT",
            client_factory=FakeClient, uploader=lambda *a: None,
            bridge_url="http://offline",
        )
        assert result["saved"] == 1 and result["failed"] == 0
        assert result["manifest_updated"] is True
        assert FakeClient.calls == ["MEitKm687xo"]
        updated = json.loads(path.read_text(encoding="utf-8"))
        assert updated["keep"] == "operator-note"
        assert updated["items"][0]["transcript_ready"] is True
        assert "transcript_ready" not in updated["items"][2]
        assert (tmp_path / "NAS" / "SRT" / "MEitKm687xo.srt").exists()
        assert not list(path.parent.glob(".*.tmp"))
    finally:
        conn.close()


def test_deep_manifest_quota_block_does_not_request_network(tmp_path, monkeypatch):
    from rg_youtube_control import transcript_export_worker as worker
    conn = _conn(tmp_path)
    path = _manifest(tmp_path, [{"video_id": "MEitKm687xo"}])
    monkeypatch.setattr(worker, "quota_budget_status", lambda c: {"spendable": 0})

    class NoAPI:
        def __init__(self, **kwargs):
            raise AssertionError("No API allowed when reserve is protected")
    try:
        original = path.read_bytes()
        result = worker.run_deep_manifest_transcript_export(
            conn, profile="main", manifest_path=path,
            target_dir=tmp_path / "SRT",
            client_factory=NoAPI, uploader=lambda *a: None,
            bridge_url="http://offline",
        )
        assert result["quota_blocked"] is True
        assert result["saved"] == 0
        assert path.read_bytes() == original
    finally:
        conn.close()


def test_deep_manifest_never_overwrites_concurrent_editor_manifest(
    tmp_path, monkeypatch,
):
    from rg_youtube_control import transcript_export_worker as worker
    conn = _conn(tmp_path)
    path = _manifest(tmp_path, [{"video_id": "MEitKm687xo"}])
    old_run = worker.run_transcript_export

    def simulated_worker(*args, **kwargs):
        path.write_text(
            json.dumps({"items": [], "keep": "new-operator-manifest"}),
            encoding="utf-8",
        )
        return {
            "items": [{"video_id": "MEitKm687xo", "ok": True,
                       "path": "SRT/MEitKm687xo.srt"}],
            "saved": 1, "failed": 0,
        }
    monkeypatch.setattr(worker, "run_transcript_export", simulated_worker)
    try:
        result = worker.run_deep_manifest_transcript_export(
            conn, profile="main", manifest_path=path,
            target_dir=tmp_path / "SRT",
            client_factory=FakeClient, uploader=lambda *a: None,
            bridge_url="http://offline",
        )
        assert result["saved"] == 1
        assert not result["manifest_updated"]
        assert json.loads(path.read_text(encoding="utf-8"))["keep"] == (
            "new-operator-manifest"
        )
    finally:
        monkeypatch.setattr(worker, "run_transcript_export", old_run)
        conn.close()


def test_deep_transcript_action_contains_zero_qt_thread_unc_or_api_operations():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    root = ast.parse(source)
    window = next(node for node in root.body
                  if isinstance(node, ast.ClassDef)
                  and node.name == "MainWindow")
    method = next(node for node in window.body
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "export_deep_review_transcripts")
    code = ast.get_source_segment(source, method)
    assert "LocalToolWorker(task, self)" in code
    assert "run_deep_manifest_transcript_export(" in code
    assert "sqlite3.connect(str(db_path), timeout=15)" in code
    assert "worker.start()" in code
    assert ".exists()" not in code
    assert ".read_text(" not in code
    assert ".write_text(" not in code
    assert "QApplication.processEvents()" not in code
    assert "self._export_transcript_video_to_nas(" not in code


def test_deep_manifest_qt_button_returns_immediately_and_deduplicates(
    tmp_path, monkeypatch,
):
    import threading
    import time
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ui.MainWindow, "_nas_path",
        lambda self, *args: tmp_path / "simulated-nas",
    )
    source_thread = threading.get_ident()
    thread_ids = []
    def slow_export(conn, **kwargs):
        thread_ids.append(threading.get_ident())
        time.sleep(0.28)
        return {
            "saved": 1, "failed": 0, "errors": [], "pending": 1,
            "existing": 0, "manifest_updated": True,
            "quota_blocked": False,
        }

    monkeypatch.setattr(ui, "run_deep_manifest_transcript_export", slow_export)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        monkeypatch.setattr(window, "_refresh_archive_stats_async", lambda: None)
        monkeypatch.setattr(
            window, "_refresh_transcript_availability_async", lambda: None,
        )
        start = time.monotonic()
        window.export_deep_review_transcripts(confirm=False, notify=False)
        assert time.monotonic() - start < 0.15
        worker = window._deep_transcript_export_worker
        window.export_deep_review_transcripts(confirm=False, notify=False)
        assert window._deep_transcript_export_worker is worker
        deadline = time.monotonic() + 7
        while getattr(window, "_deep_transcript_export_worker", None):
            if time.monotonic() > deadline:
                raise AssertionError("Deep export worker failed to finish")
            app.processEvents()
            time.sleep(0.01)
        assert len(thread_ids) == 1
        assert thread_ids[0] != source_thread
    finally:
        worker = getattr(window, "_deep_transcript_export_worker", None)
        if worker is not None:
            worker.wait(7000)
        window.close()
