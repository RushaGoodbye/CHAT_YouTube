"""NAS package imports must not freeze Qt or overwrite newer channel drafts."""
import ast
import json
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

def drain(window, key, app, timeout=8):
    deadline = time.monotonic() + timeout
    while getattr(window, key, None) is not None:
        if time.monotonic() > deadline:
            raise AssertionError(f"{key} worker never completed")
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_package_imports_use_background_tasks_without_gui_state():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    main = next(
        item for item in ast.parse(source).body
        if isinstance(item, ast.ClassDef) and item.name == "MainWindow"
    )
    for name in ("import_selected_package_from_nas", "fetch_scheduled_packages"):
        method = next(
            item for item in main.body
            if isinstance(item, ast.FunctionDef) and item.name == name
        )
        task = next(
            item for item in method.body
            if isinstance(item, ast.FunctionDef) and item.name == "task"
        )
        assert not any(
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "self"
            for n in ast.walk(task)
        ), name
        segment = ast.get_source_segment(source, method)
        assert "LocalToolWorker(task, self)" in segment
        assert "running.isRunning()" in segment
        assert "worker.finished.connect(finished)" in segment


def test_selected_package_slow_nas_does_not_block_gui(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(ui.MainWindow, "_nas_path",
                        lambda self, *a: tmp_path / "missing_share")
    notices = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a: notices.append(str(a[-1])))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    calls = []
    main_thread = threading.get_ident()

    def remote(_url, _id):
        calls.append(threading.get_ident())
        time.sleep(0.25)
        return {"video_id": "MEitKm687xo", "new_title": "SEO"}

    monkeypatch.setattr(ui, "fetch_package", remote)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "last_synced_at) VALUES (?,?,?,?,?)",
            ("MEitKm687xo", "main", "old", "public", "2026-10-25"),
        )
        window.conn.commit()
        monkeypatch.setattr(
            window, "_selected_optimization_video_ids",
            lambda: ["MEitKm687xo"],
        )
        saved = []
        monkeypatch.setattr(
            window, "_save_package_payload",
            lambda video_id, payload: (saved.append((video_id, payload))
                                       or ("draft", (), ())),
        )
        monkeypatch.setattr(
            window, "reload_optimization_queue", lambda: None,
        )
        begun = time.monotonic()
        window.import_selected_package_from_nas()
        assert time.monotonic() - begun < 0.15
        worker = window._import_package_worker
        window.import_selected_package_from_nas()
        assert window._import_package_worker is worker
        drain(window, "_import_package_worker", app)
        assert calls == [calls[0]] and calls[0] != main_thread
        assert len(saved) == 1
        assert "Пакет імпортовано" in "\n".join(notices)
    finally:
        worker = getattr(window, "_import_package_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()


def test_scheduled_import_refuses_stale_local_drafts_after_slow_nas(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ui.MainWindow, "_nas_path",
        lambda self, *a: tmp_path / "missing_share",
    )
    notices = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a: notices.append(str(a[-1])))
    calls = []
    main_thread = threading.get_ident()

    def remote(_url, video_id):
        calls.append(threading.get_ident())
        time.sleep(0.25)
        return {"video_id": video_id, "title": "new"}

    monkeypatch.setattr(ui, "fetch_package", remote)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        id1 = "MEitKm687xo"
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "scheduled_publish_at,last_synced_at) VALUES (?,?,?,?,?,?)",
            (id1, "main", "old", "private", "2026-10-26T19:00:00",
             "2026-10-25"),
        )
        window.conn.commit()
        saved = []
        monkeypatch.setattr(
            window, "_save_package_payload",
            lambda video_id, payload: (saved.append(video_id)
                                       or ("draft", (), ())),
        )
        monkeypatch.setattr(window, "reload_optimization_queue", lambda: None)
        begun = time.monotonic()
        window.fetch_scheduled_packages()
        assert time.monotonic() - begun < 0.15
        worker = window._scheduled_packages_worker
        window.fetch_scheduled_packages()
        assert window._scheduled_packages_worker is worker
        # An edit committed after the import began must win.
        ui.save_optimization_draft(
            window.conn, id1, "Operator edit", "description",
            "", [], "draft",
        )
        drain(window, "_scheduled_packages_worker", app)
        assert calls == [calls[0]] and calls[0] != main_thread
        assert saved == []
        assert "Без змін: 1" in "\n".join(notices)
    finally:
        worker = getattr(window, "_scheduled_packages_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()


def test_selected_import_preserves_operator_changes_during_slow_nas(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ui.MainWindow, "_nas_path", lambda self, *a: tmp_path / "offline",
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args: None,
    )
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args: None,
    )
    def slow_fetch(_url, video_id):
        time.sleep(0.25)
        return {"video_id": video_id, "new_title": "NAS version"}
    monkeypatch.setattr(ui, "fetch_package", slow_fetch)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        video_id = "MEitKm687xo"
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "last_synced_at) VALUES (?,?,?,?,?)",
            (video_id, "main", "Published", "public", "2026-10-25"),
        )
        window.conn.commit()
        monkeypatch.setattr(
            window, "_selected_optimization_video_ids",
            lambda: [video_id],
        )
        saved = []
        monkeypatch.setattr(
            window, "_save_package_payload",
            lambda *args: saved.append(args),
        )
        window.import_selected_package_from_nas()
        ui.save_optimization_draft(
            window.conn, video_id, "Operator version", "Manual description",
            "", [], "draft",
        )
        drain(window, "_import_package_worker", app)
        assert saved == []
        row = window.conn.execute(
            "SELECT new_title FROM optimization_drafts WHERE video_id=?",
            (video_id,),
        ).fetchone()
        assert row["new_title"] == "Operator version"
    finally:
        worker = getattr(window, "_import_package_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()
