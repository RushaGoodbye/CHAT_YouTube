"""Archive campaign dialog must never scan remote NAS subtitles in Qt."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_archive_campaign_modal_reads_async_cache_only():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def show_archive_campaign_center(")
    end = source.index("\n    def ", start + 6)
    method = source[start:end]
    assert "self._archive_campaign_stats()" not in method
    assert method.count("self._archive_campaign_stats_cached()") == 2
    assert "cache_timer.start(1000)" in method
    assert 'run_btn.setEnabled(False)' in method
    assert 'open_btn.setEnabled(False)' in method


def test_archive_campaign_modal_without_nas_never_blocks(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: 0)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    calls = []
    monkeypatch.setattr(
        window, "_archive_campaign_stats",
        lambda: (_ for _ in ()).throw(AssertionError("Synchronous NAS scan")),
    )
    monkeypatch.setattr(
        window, "_refresh_archive_stats_async", lambda: calls.append("async")
    )
    try:
        window.show_archive_campaign_center()
        app.processEvents()
        assert calls == ["async"]
    finally:
        window.close()
