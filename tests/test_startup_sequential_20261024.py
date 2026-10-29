"""Ensure startup loads run in a predictable sequence, not concurrently."""
from pathlib import Path


def test_startup_tables_are_chained():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    init = source.split("class MainWindow(QMainWindow):", 1)[1].split(
        "    def _record_startup_duration(", 1
    )[0]
    assert "QTimer.singleShot(100, self._startup_load_videos)" in init
    assert "QTimer.singleShot(300, self._startup_load_optimization)" not in init
    chain = (
        ('videos', '_startup_load_optimization'),
        ('optimization', '_startup_load_comments'),
        ('comments', '_startup_load_actions'),
        ('actions', '_startup_finish'),
    )
    for stage, next_stage in chain:
        marker = f'self._record_startup_duration("{stage}", started)'
        assert marker + f"\n            QTimer.singleShot(0, self.{next_stage})" in source
