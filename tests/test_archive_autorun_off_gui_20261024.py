"""Archive autorun must not block the Qt event loop on UNC transcript stat."""
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_archive_autorun_never_synchronously_scans_nas():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _run_archive_campaign_autorun(")
    end = source.index("\n    def ", start + 6)
    body = source[start:end]
    assert "stats = cached_stats" in body
    assert "stats = self._archive_campaign_stats()" not in body
    assert "self._refresh_archive_stats_async()" in body
    assert '_archive_stats_unavailable' in body


def test_archive_autorun_defers_with_missing_stats_without_network(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    window = ui.MainWindow()
    triggered = []
    try:
        monkeypatch.setattr(ui, "archive_priority_enabled", lambda conn: True)
        monkeypatch.setattr(
            window, "_refresh_archive_stats_async", lambda: triggered.append(True)
        )
        monkeypatch.setattr(
            window, "_apply_scheduled_before_archive_for_quota_day",
            lambda *_: (_ for _ in ()).throw(
                AssertionError("Must not call YouTube while NAS stats are pending")
            ),
        )
        window._dashboard_archive_stats_cache = None
        window._run_archive_campaign_autorun()
        assert triggered == [True]
        assert not getattr(window, "_archive_campaign_autorun_running", False)

        window._dashboard_archive_stats_cache = {
            profile: {"safe_remaining": 1} for profile in ui.PROFILE_TARGETS
        }
        window._dashboard_archive_stats_cache_at = time.monotonic() - 3600
        window._run_archive_campaign_autorun()
        assert triggered == [True, True]
    finally:
        window.close()
