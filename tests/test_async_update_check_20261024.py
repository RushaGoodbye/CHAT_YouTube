"""No remote updater HTTP request on the GUI event loop."""
from pathlib import Path


def test_silent_update_check_uses_worker():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def check_for_updates_silent(")
    end = source.index("    def install_update_from_zip(", start)
    block = source[start:end]
    assert "LocalToolWorker(check_for_update, self)" in block
    assert "worker.succeeded.connect(self._on_silent_update_result)" in block
    assert "worker.finished.connect(self._on_silent_update_finished)" in block
    assert "info = check_for_update()" not in block
    assert "self._offer_update(info, manual=False)" in block
