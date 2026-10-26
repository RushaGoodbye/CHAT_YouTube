"""Manual backup to a slow/disconnected NAS never runs on the Qt thread."""
import ast
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_manual_backup_never_shares_gui_sqlite_connection():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    method = next(n for n in main.body
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "create_recovery_backup_now")
    task = next(n for n in method.body
                if isinstance(n, ast.FunctionDef) and n.name == "task")
    assert not any(
        isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
        for n in ast.walk(task)
    )
    segment = ast.get_source_segment(source, method)
    assert "sqlite3.connect(str(db_path), timeout=15)" in segment
    assert "worker_conn.close()" in segment
    assert "LocalToolWorker(task, self)" in segment
    assert 'getattr(self, "_daily_backup_worker", None)' in segment


def test_manual_backup_remains_responsive_and_deduplicates(
    tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    notices = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *args: notices.append(str(args[-1])),
    )
    seen = []
    main_thread = threading.get_ident()

    def slow_backup(*, conn, data_dir, backup_root, version):
        seen.append(threading.get_ident())
        assert data_dir == tmp_path
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        time.sleep(0.3)
        return tmp_path / "test-recovery.zip"

    monkeypatch.setattr(ui, "create_recovery_backup", slow_backup)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        started = time.monotonic()
        window.create_recovery_backup_now()
        assert time.monotonic() - started < 0.15
        worker = window._manual_backup_worker
        window.create_recovery_backup_now()
        assert window._manual_backup_worker is worker
        deadline = time.monotonic() + 8
        while getattr(window, "_manual_backup_worker", None) is not None:
            if time.monotonic() > deadline:
                raise AssertionError("Manual backup worker timed out")
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert seen == [seen[0]]
        assert seen[0] != main_thread
        assert notices and "test-recovery.zip" in notices[0]
    finally:
        worker = getattr(window, "_manual_backup_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()
