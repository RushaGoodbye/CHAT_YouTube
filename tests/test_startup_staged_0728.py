"""Responsiveness regression: heavy startup tables are loaded on demand."""
from pathlib import Path


def test_large_table_refreshes_not_in_window_constructor():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    init = source.split("class MainWindow(QMainWindow):", 1)[1].split(
        "    def _startup_load_videos(", 1
    )[0]
    assert 'QTimer.singleShot(100, self._startup_load_videos)' not in init
    assert 'QTimer.singleShot(300, self._startup_load_optimization)' not in init
    assert 'self._startup_views_ready = True' in init
    assert 'self._load_requested_tab(target)' in init
    assert 'self._startup_traced("_build_optimization_tab"' in init
    assert "        self.reload_videos()" not in init
    assert "        self.reload_optimization_queue()" not in init
    assert "        self.reload_comments()" not in init
    assert "        self.reload_action_log()" not in init
