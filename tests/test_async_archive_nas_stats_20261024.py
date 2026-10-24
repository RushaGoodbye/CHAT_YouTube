"""Slow NAS transcript probes must never execute on the GUI thread."""
import ast
from pathlib import Path


def test_archive_summary_uses_worker_owned_sqlite():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _archive_campaign_stats_cached(")
    end = source.index("    def _archive_campaign_budget(", start)
    block = source[start:end]
    assert "self._refresh_archive_stats_async()" in block
    assert "LocalToolWorker(task, self)" in block
    assert 'sqlite3.connect(str(db_path), timeout=15)' in block
    assert "worker_conn.close()" in block
    assert "transcript_dir=transcript_dir" in block
    assert "self._archive_campaign_stats()" not in block
    tree = ast.parse("class T:\n" + block)
    task = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "task"
    )
    assert not any(
        isinstance(node, ast.Attribute)
        and node.attr == "conn"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        for node in ast.walk(task)
    )


def test_archive_summary_does_not_synchronously_rescan_nas():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _refresh_archive_campaign_summary(")
    end = source.index("    def _advance_archive_campaign(", start)
    block = source[start:end]
    assert "stats = self._archive_campaign_stats_cached()" in block
    assert "stats = self._archive_campaign_stats()" not in block


def test_archive_summary_does_not_claim_completion_without_stats():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _refresh_archive_campaign_summary(")
    end = source.index("    def _advance_archive_campaign(", start)
    block = source[start:end]
    assert '_archive_stats_unavailable' in block
    assert 'статистика NAS недоступна' in block
    assert 'оновлення статистики…' in block
    assert 'if getattr(self, "_dashboard_archive_stats_cache", None) is None:' in block
