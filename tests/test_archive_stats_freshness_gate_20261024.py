"""Campaign actions must fail closed on stale, absent or failed NAS cache."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_archive_campaign_actions_require_fresh_stats(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    old = {
        "main": {"safe_remaining": 8, "deep_remaining": 5},
        "live": {"safe_remaining": 3, "deep_remaining": 4},
    }
    monkeypatch.setattr(window, "_refresh_archive_stats_async", lambda: None)
    monkeypatch.setattr(
        window, "_activate_profile",
        lambda profile: (_ for _ in ()).throw(
            AssertionError("Must not progress a stale phase")
        )
    )
    try:
        window._dashboard_archive_stats_cache = old
        window._dashboard_archive_stats_cache_at = time.monotonic() - 301
        assert window._archive_stats_fresh_for_actions() is False
        assert window.run_archive_campaign_step() is False

        window._dashboard_archive_stats_cache_at = time.monotonic()
        window._archive_stats_unavailable = True
        assert window._archive_stats_fresh_for_actions() is False
        assert window.run_archive_campaign_step() is False

        window._archive_stats_unavailable = False
        assert window._archive_stats_fresh_for_actions() is True
        window._dashboard_archive_stats_cache = None
        assert window._archive_stats_fresh_for_actions() is False
    finally:
        window.close()


def test_archive_actions_not_using_stale_unc_state():
    from pathlib import Path

    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    for method_name in (
        "run_archive_campaign_step",
        "export_deep_review_queue_to_nas",
        "show_archive_campaign_center",
    ):
        block = source.split(f"    def {method_name}(", 1)[1].split(
            "\n    def ", 1
        )[0]
        assert "self._archive_stats_fresh_for_actions()" in block
