"""Diagnostic and NAS availability checks must not hang the Qt event loop."""
import ast
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _await_worker(window, name, app, timeout=8):
    deadline = time.monotonic() + timeout
    while getattr(window, name, None) is not None:
        if time.monotonic() > deadline:
            raise AssertionError(f"{name} did not finish")
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_diagnostics_and_nas_workers_hold_no_qt_widgets_or_main_db():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    for name in ("refresh_diagnostics_panel", "test_nas_transcript_path"):
        method = next(n for n in main.body
                      if isinstance(n, ast.FunctionDef) and n.name == name)
        task = next(n for n in method.body
                    if isinstance(n, ast.FunctionDef) and n.name == "task")
        for node in ast.walk(task):
            assert not (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
            ), f"Qt instance touched in {name} worker"
        segment = ast.get_source_segment(source, method)
        assert "LocalToolWorker(task, self)" in segment
        assert "running.isRunning()" in segment
        assert "worker.finished.connect(finished)" in segment


def test_diagnostics_real_qthread_does_not_block_gui(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(ui, "powershell_status",
                        lambda: {"available": True, "version": "7"})
    main_thread = threading.get_ident()
    observed_threads = []
    def slow_tools():
        observed_threads.append(threading.get_ident())
        time.sleep(0.25)
        return {"ollama": {"available": False},
                "ollama_model": {"available": False}}
    monkeypatch.setattr(ui, "probe_free_tools", slow_tools)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        began = time.monotonic()
        window.refresh_diagnostics_panel()
        assert time.monotonic() - began < 0.15
        worker = window._diagnostics_worker
        window.refresh_diagnostics_panel()
        assert window._diagnostics_worker is worker
        app.processEvents()
        assert "фоні" in window.diagnostics_text.text()
        _await_worker(window, "_diagnostics_worker", app)
        assert observed_threads and observed_threads[0] != main_thread
        assert "Ollama: —" in window.diagnostics_text.text()
    finally:
        worker = getattr(window, "_diagnostics_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()


def test_nas_probe_real_qthread_does_not_block_gui(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    target = tmp_path / "nas" / "SRT"
    monkeypatch.setattr(ui.MainWindow, "_nas_path",
                        lambda self, *a: target)
    main_thread = threading.get_ident()
    observed_threads = []
    def slow_bridge(_url):
        observed_threads.append(threading.get_ident())
        time.sleep(0.25)
        return {"ok": False}
    monkeypatch.setattr(ui, "bridge_health", slow_bridge)
    dialogs = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a: dialogs.append(("info", a[-1])))
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a: dialogs.append(("critical", a[-1])))
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        began = time.monotonic()
        window.test_nas_transcript_path()
        assert time.monotonic() - began < 0.15
        worker = window._nas_test_worker
        window.test_nas_transcript_path()
        assert window._nas_test_worker is worker
        _await_worker(window, "_nas_test_worker", app)
        assert observed_threads and observed_threads[0] != main_thread
        assert dialogs and dialogs[0][0] == "info"
        assert "NAS: OK" in dialogs[0][1]
        assert list(target.glob("_rg_youtube_control_write_test_*")) == []
    finally:
        worker = getattr(window, "_nas_test_worker", None)
        if worker is not None:
            worker.wait(8000)
        window.close()
