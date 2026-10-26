"""Launch responsiveness regression: first paint precedes expensive table loads."""
from pathlib import Path


def test_large_table_refreshes_not_in_window_constructor():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    init = source.split("class MainWindow(QMainWindow):", 1)[1].split(
        "    def _startup_load_videos(", 1
    )[0]
    assert 'QTimer.singleShot(100, self._startup_load_videos)' in init
    assert 'QTimer.singleShot(300, self._startup_load_optimization)' not in init
    assert 'QTimer.singleShot(0, self._startup_load_optimization)' in source
    assert "        self.reload_videos()" not in init
    assert "        self.reload_optimization_queue()" not in init
    assert "        self.reload_comments()" not in init
    assert "        self.reload_action_log()" not in init
