"""Startup timing must be recorded independently of the shared SQLite connection."""
from pathlib import Path


def test_startup_timing_is_file_backed_and_stage_scoped():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _record_startup_duration(")
    end = source.index("    def _startup_finish(", start)
    block = source[start:end]
    assert 'self.data_dir / "startup_timing.jsonl"' in block
    assert "self.conn" not in block
    for stage in ("videos", "optimization", "comments", "actions"):
        assert f'self._record_startup_duration("{stage}", started)' in block
    assert block.count("finally:") == 4
