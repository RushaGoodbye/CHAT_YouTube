"""Periodic comment scans must not access GUI SQLite from their QThread."""
import ast
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_comment_worker_is_thread_affine_and_qt_signal_bound():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def background_scan_all_channels(")
    end = source.index("\n    def ", start + 6)
    body = source[start:end]
    assert "LocalToolWorker(task, self)" in body
    assert "scan_channel_comments(" in body
    assert "worker_conn = sqlite3.connect(str(db_path), timeout=15)" in body
    assert "worker_conn.close()" in body
    tree = ast.parse("class T:\n" + body)
    task = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "task"
    )
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "conn"
        and isinstance(node.value, ast.Name) and node.value.id == "self"
        for node in ast.walk(task)
    )


def test_comment_scan_worker_reads_both_channels_without_gui_sqlite(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)

    class Client:
        def __init__(self, profile):
            self.profile = profile

        def credentials(self):
            return True

    def scan(client, conn, channel_id, **kwargs):
        assert kwargs["auto_reply"] is False
        conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",
            (f"qa_comments_{client.profile}", channel_id),
        )
        conn.commit()
        return {"seen": 3, "auto_replied": 0, "api_reads": 1}

    monkeypatch.setattr(ui, "YouTubeClient", Client)
    monkeypatch.setattr(ui, "scan_channel_comments", scan)
    window = ui.MainWindow()
    try:
        window.background_box.setChecked(True)
        window.background_scan_all_channels()
        deadline = time.monotonic() + 15
        while getattr(window, "_comment_scan_worker", None) is not None:
            if time.monotonic() > deadline:
                raise AssertionError("Background comment worker did not finish")
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        for profile, channel_id in ui.PROFILE_TARGETS.items():
            row = window.conn.execute(
                "SELECT value FROM settings WHERE key=?",
                (f"qa_comments_{profile}",),
            ).fetchone()
            assert row is not None and row[0] == channel_id
    finally:
        worker = getattr(window, "_comment_scan_worker", None)
        if worker is not None:
            worker.wait(10000)
        window.close()
