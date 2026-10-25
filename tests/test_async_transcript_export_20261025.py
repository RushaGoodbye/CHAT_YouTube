"""Regression: manual SRT export never blocks Qt, drains quota, or corrupts NAS files."""
import ast
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _conn(tmp_path):
    from rg_youtube_control.db import connect
    return connect(tmp_path / "rg_youtube_control.db")


def _row(video_id="MEitKm687xo"):
    return {"video_id": video_id, "title": "ПЕРЕМОЖНІ НОВИНИ",
            "scheduled_publish_at": "2026-10-25T19:00:00"}


def test_transcript_worker_downloads_to_atomic_srt_and_reports(tmp_path):
    from rg_youtube_control.transcript_export_worker import run_transcript_export
    from rg_youtube_control.service import today_quota_units
    conn = _conn(tmp_path)
    calls = []
    uploads = []

    class FakeClient:
        def __init__(self, profile):
            calls.append(("client", profile))

        def download_best_caption_srt(self, video_id):
            calls.append(("download", video_id))
            return {"snippet": {"language": "uk"}}, "1\n00:00:00,000 --> 00:00:02,000\nТекст"

    folder = tmp_path / "NAS" / "SRT"
    try:
        result = run_transcript_export(
            conn, profile="main", rows=[_row()], target_dir=folder,
            client_factory=FakeClient,
            uploader=lambda *a: uploads.append(a),
            bridge_url="http://offline-bridge",
        )
        assert result["saved"] == 1 and result["failed"] == 0
        assert result["already"] == 0
        assert today_quota_units(conn) == 250
        assert (folder / "MEitKm687xo.srt").is_file()
        assert "Текст" in (folder / "MEitKm687xo.srt").read_text(encoding="utf-8")
        metadata = json.loads(
            (folder / "MEitKm687xo.json").read_text(encoding="utf-8")
        )
        assert metadata["channel_profile"] == "main"
        assert metadata["language"] == "uk"
        assert uploads and uploads[0][1] == "MEitKm687xo"
        assert (folder / "_last_transcript_report_main.json").is_file()
        assert not list(folder.glob(".*.tmp"))
        second = run_transcript_export(
            conn, profile="main", rows=[_row()], target_dir=folder,
            client_factory=FakeClient, uploader=lambda *a: None,
            bridge_url="http://offline-bridge",
        )
        assert second["already"] == 1 and second["saved"] == 0
        assert calls.count(("download", "MEitKm687xo")) == 1
        assert today_quota_units(conn) == 250
    finally:
        conn.close()


def test_transcript_worker_rejects_too_many_missing_before_any_api(tmp_path):
    import pytest
    from rg_youtube_control.transcript_export_worker import run_transcript_export
    conn = _conn(tmp_path)
    class Forbidden:
        def __init__(self, **kwargs):
            raise AssertionError("YouTube API cannot be accessed")
    try:
        ids = [f"VideoId{i:04d}" for i in range(21)]
        assert all(len(video_id) == 11 for video_id in ids)
        with pytest.raises(ValueError, match="ліміт"):
            run_transcript_export(
                conn, profile="main",
                rows=[_row(video_id) for video_id in ids],
                target_dir=tmp_path / "missing", max_new=20,
                client_factory=Forbidden, uploader=lambda *a: None,
                bridge_url="http://bridge",
            )
    finally:
        conn.close()


def test_missing_caption_charges_only_list_cost(tmp_path):
    from rg_youtube_control.transcript_export_worker import run_transcript_export
    from rg_youtube_control.service import today_quota_units
    conn = _conn(tmp_path)
    class Missing:
        def __init__(self, profile): pass
        def download_best_caption_srt(self, video_id):
            raise RuntimeError("Для цього відео не знайдено доступних субтитрів.")
    try:
        result = run_transcript_export(
            conn, profile="main", rows=[_row()],
            target_dir=tmp_path / "share", client_factory=Missing,
            uploader=lambda *a: None, bridge_url="http://bridge",
        )
        assert result["failed"] == 1 and result["saved"] == 0
        assert today_quota_units(conn) == 50
        assert not (tmp_path / "share" / "MEitKm687xo.srt").exists()
    finally:
        conn.close()


def test_transcript_worker_ui_free_and_uses_separate_connection():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    main = next(x for x in ast.parse(source).body
                if isinstance(x, ast.ClassDef) and x.name == "MainWindow")
    method = next(x for x in main.body
                  if isinstance(x, ast.FunctionDef)
                  and x.name == "_start_transcript_export_worker")
    worker_task = next(x for x in method.body
                       if isinstance(x, ast.FunctionDef) and x.name == "task")
    assert not any(
        isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
        and x.value.id == "self" for x in ast.walk(worker_task)
    )
    code = ast.get_source_segment(source, method)
    assert "sqlite3.connect(str(db_path), timeout=15)" in code
    assert "conn.close()" in code
    assert "LocalToolWorker(task, self)" in code

    for method_name in (
        "export_selected_transcript_to_nas",
        "export_scheduled_transcripts_to_nas",
    ):
        method = next(x for x in main.body
                      if isinstance(x, ast.FunctionDef) and x.name == method_name)
        code = ast.get_source_segment(source, method)
        assert "self._start_transcript_export_worker(" in code
        assert "self._export_transcript_video_to_nas(" not in code
        assert ".exists()" not in code


def test_scheduled_transcript_button_nonblocking_and_no_duplicate(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a: QMessageBox.StandardButton.Yes,
    )
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a: messages.append(str(a[-1])),
    )
    monkeypatch.setattr(
        ui.MainWindow, "_nas_path",
        lambda self, *a: tmp_path / "offline",
    )

    threads = []
    main_thread = threading.get_ident()
    def slow_worker(conn, **kwargs):
        threads.append(threading.get_ident())
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        time.sleep(0.25)
        return {"already": 0, "saved": 1, "failed": 0,
                "errors": [], "items": [{
                    "ok": True, "downloaded": True,
                    "path": str(tmp_path / "offline" / "MEitKm687xo.srt"),
                }], "report_error": "", "report_path": str(tmp_path / "report")}
    monkeypatch.setattr(ui, "run_transcript_export", slow_worker)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "scheduled_publish_at,last_synced_at) VALUES (?,?,?,?,?,?)",
            ("MEitKm687xo", "main", "Збір", "private",
             "2026-10-26T19:00:00", "2026-10-25"),
        )
        window.conn.commit()
        monkeypatch.setattr(window, "reload_optimization_queue", lambda: None)
        started = time.monotonic()
        window.export_scheduled_transcripts_to_nas()
        assert time.monotonic() - started < 0.15
        worker = window._transcript_export_worker
        window.export_scheduled_transcripts_to_nas()
        assert window._transcript_export_worker is worker
        deadline = time.monotonic() + 8
        while getattr(window, "_transcript_export_worker", None) is not None:
            if time.monotonic() > deadline:
                raise AssertionError("SRT worker stalled")
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert threads == [threads[0]] and threads[0] != main_thread
        assert any("Нових транскриптів: 1" in message for message in messages)
    finally:
        worker = getattr(window, "_transcript_export_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()
