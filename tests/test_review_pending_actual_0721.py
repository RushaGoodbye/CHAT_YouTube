"""0.7.21 regression: persisted Ready must never hide packages needing review."""
import json
import os
import sqlite3
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from rg_youtube_control.ui import MainWindow


SHOIGU = [
    "Увольнение Шойгу: коррупция или план?",
    "Шойгу уволен: за что и по какому плану?",
    "Увольнение Шойгу: коррупция или стратегия?",
]


def _fixture():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE videos(
            video_id TEXT PRIMARY KEY, profile TEXT,
            scheduled_publish_at TEXT
        );
        CREATE TABLE optimization_drafts(
            video_id TEXT PRIMARY KEY,
            status TEXT, generation TEXT, quality_state TEXT,
            title_variants_json TEXT, updated_at TEXT
        );
    """)
    entries = [
        ("shoigu-draft", "main", "draft", "local-seo",
         "review", json.dumps(SHOIGU, ensure_ascii=False), "2026-10-12 12:00:00"),
        ("old-ready", "main", "ready", "legacy",
         "", "[]", "2026-10-11 12:00:00"),
        ("safe-ready", "main", "ready", "safe-metadata-0.7.6",
         "safe_metadata", "[]", "2026-10-10 12:00:00"),
        ("live-only", "live", "ready", "legacy",
         "", "[]", "2026-10-10 12:00:00"),
    ]
    for video, profile, status, generation, quality, variants, updated in entries:
        conn.execute("INSERT INTO videos VALUES(?,?,NULL)", (video, profile))
        conn.execute(
            "INSERT INTO optimization_drafts VALUES(?,?,?,?,?,?)",
            (video, status, generation, quality, variants, updated),
        )
    conn.commit()
    return conn


def test_review_queue_includes_invalid_ready_without_any_db_mutation():
    conn = _fixture()
    try:
        window = SimpleNamespace(conn=conn, current_profile="main")
        all_rows = MainWindow._pending_seo_review_rows(window)
        assert [x["video_id"] for x in all_rows] == ["shoigu-draft", "old-ready"]
        assert len(MainWindow._pending_seo_review_rows(window, limit=1)) == 1
        assert conn.execute(
            "SELECT status FROM optimization_drafts WHERE video_id='old-ready'"
        ).fetchone()[0] == "ready"
    finally:
        conn.close()


def test_bulk_accept_cannot_approve_old_ready_without_ab(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    conn = _fixture()
    notices = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *_args: notices.append(_args[-1])
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *_args: notices.append(_args[-1])
    )
    try:
        window = SimpleNamespace(
            conn=conn,
            current_profile="main",
            _pending_seo_review_rows=lambda limit=None:
                MainWindow._pending_seo_review_rows(
                    SimpleNamespace(conn=conn, current_profile="main"), limit
                ),
            _review_one_draft_dialog=lambda *_: "accept",
            reload_optimization_queue=lambda: None,
            reload_action_log=lambda: None,
            update_dashboard=lambda: None,
        )
        MainWindow.review_draft_queue(window)
        states = dict(conn.execute(
            "SELECT video_id,status FROM optimization_drafts"
        ).fetchall())
        assert states["old-ready"] == "ready"
        assert states["shoigu-draft"] == "draft"
        assert any("A/B" in notice for notice in notices)
        assert any("повторюють" in notice for notice in notices)
    finally:
        conn.close()


def test_review_queue_does_not_auto_delete_legacy_when_empty(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    conn = _fixture()
    conn.execute("DELETE FROM optimization_drafts WHERE video_id IN ('old-ready','shoigu-draft')")
    conn.commit()
    dialogs = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *_args: dialogs.append(_args[-1])
    )
    try:
        window = SimpleNamespace(
            _pending_seo_review_rows=lambda limit=None: [],
        )
        MainWindow.review_draft_queue(window)
        assert dialogs and "немає" in dialogs[0]
        assert conn.execute(
            "SELECT COUNT(*) FROM optimization_drafts"
        ).fetchone()[0] == 2
    finally:
        conn.close()
