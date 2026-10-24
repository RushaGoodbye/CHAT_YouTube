"""NAS backup must not hold the main Qt event loop on slow UNC writes."""
import ast
from pathlib import Path


def test_daily_backup_uses_separate_sqlite_and_background_worker():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def ensure_daily_recovery_backup(")
    end = source.index("    def _prechange_backup_or_warn(", start)
    block = source[start:end]
    assert "LocalToolWorker(task, self)" in block
    assert "worker.succeeded.connect(self._on_daily_backup_success)" in block
    assert "worker.failed.connect(self._on_daily_backup_failed)" in block
    assert "worker_conn = sqlite3.connect(" in block
    assert "worker_conn.close()" in block
    assert "conn=worker_conn" in block
    assert 'set_setting(self.conn, "automatic_recovery_backup_day", day)' in block
    tree = ast.parse("class T:\n" + block)
    task = next(
        x for x in tree.body[0].body[0].body
        if isinstance(x, ast.FunctionDef) and x.name == "task"
    )
    assert not any(
        isinstance(x, ast.Attribute) and x.attr == "conn"
        and isinstance(x.value, ast.Name) and x.value.id == "self"
        for x in ast.walk(task)
    )
