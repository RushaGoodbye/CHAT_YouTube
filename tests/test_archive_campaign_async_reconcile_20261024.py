"""Archive phase changes must follow new async NAS state, never Qt UNC scans."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_archive_campaign_has_no_sync_nas_stats_callsites():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    assert "self._archive_campaign_stats()" not in source
    advance = source.split("    def _advance_archive_campaign(", 1)[1].split(
        "\n    def ", 1
    )[0]
    assert "self._archive_campaign_reconcile_pending = True" in advance
    assert "self._dashboard_archive_stats_cache = None" in advance
    assert "self._refresh_archive_stats_async()" in advance
    assert "self._archive_campaign_reconcile_needs_second_scan" in advance
    run = source.split("    def run_archive_campaign_step(", 1)[1].split(
        "\n    def ", 1
    )[0]
    assert "self._archive_campaign_stats_cached()" in run
    assert "refreshed = self._archive_campaign_stats()" not in run


def test_archive_advance_does_not_reconcile_with_old_stats(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    # Isolate this test from MainWindow's independent startup stats scan.
    # The separate test below covers the already-running worker race.
    running = getattr(window, "_archive_stats_worker", None)
    if running is not None:
        running.wait(10000)
        app.processEvents()  # drain queued worker finished/result callbacks
    window._archive_stats_worker = None
    refreshed = []
    checkpoint = []
    monkeypatch.setattr(
        window, "_refresh_archive_stats_async", lambda: refreshed.append(True)
    )
    monkeypatch.setattr(
        ui, "save_campaign_checkpoint",
        lambda *a, **kw: checkpoint.append(kw),
    )
    # Do not touch real GUI controls or production YouTube auth.
    monkeypatch.setattr(ui, "archive_priority_enabled", lambda conn: False)
    monkeypatch.setattr(window, "_refresh_archive_campaign_summary", lambda: None)
    monkeypatch.setattr(window, "_activate_profile", lambda profile: None)
    try:
        window._dashboard_archive_stats_cache = {
            "main": {"safe_remaining": 3}, "live": {"safe_remaining": 2}
        }
        window._advance_archive_campaign()
        assert refreshed == [True]
        assert checkpoint == []
        assert window._dashboard_archive_stats_cache is None
        assert window._archive_campaign_reconcile_pending is True

        fresh = {
            "main": {"archive_total": 0, "safe_remaining": 0, "deep_remaining": 1,
                     "transcripts": 0, "ready_packages": 0,
                     "applied_packages": 0, "skipped_deep": 0},
            "live": {"archive_total": 0, "safe_remaining": 0, "deep_remaining": 1,
                     "transcripts": 0, "ready_packages": 0,
                     "applied_packages": 0, "skipped_deep": 0}
        }
        monkeypatch.setattr(window, "_complete_archive_recovery", lambda stats: None)
        window._on_archive_stats_ready(fresh)
        assert checkpoint
        assert window._archive_campaign_reconcile_pending is False
    finally:
        window.close()


def test_existing_scan_requires_post_mutation_rescan(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()

    class FakeWorker:
        def isRunning(self):
            return True

    monkeypatch.setattr(window, "_refresh_archive_stats_async", lambda: None)
    monkeypatch.setattr(ui, "save_campaign_checkpoint",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("stale scan must not commit")))
    monkeypatch.setattr(window, "_complete_archive_recovery", lambda stats: None)
    monkeypatch.setattr(window, "_refresh_archive_campaign_summary", lambda: None)
    try:
        window._archive_stats_worker = FakeWorker()
        window._advance_archive_campaign()
        assert window._archive_campaign_reconcile_needs_second_scan
        window._on_archive_stats_ready({"main": {}, "live": {}})
        assert window._archive_campaign_reconcile_pending
        assert window._archive_campaign_reconcile_needs_second_scan
        window._on_archive_stats_finished()
        assert not window._archive_campaign_reconcile_needs_second_scan
    finally:
        window.close()
