"""Background scheduled-video sync owns SQLite, never blocks Qt on YouTube."""
import ast
from pathlib import Path


def test_upcoming_sync_creates_worker_owned_sqlite_connection():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def sync_upcoming_streams_startup(")
    end = source.index("    def sync_video_list(", start)
    code = source[start:end]
    assert "LocalToolWorker(task, self)" in code
    assert "worker.succeeded.connect(self._on_upcoming_sync_done)" in code
    assert "worker.failed.connect(self._on_upcoming_sync_failed)" in code
    assert 'sqlite3.connect(str(db_path), timeout=15)' in code
    assert "worker_conn.close()" in code
    assert "sync_upcoming_live_broadcasts(client, worker_conn)" in code
    tree = ast.parse("class Temp:\n" + code)
    method = tree.body[0].body[0]
    task = next(n for n in method.body if isinstance(n, ast.FunctionDef) and n.name == "task")
    unsafe = [
        node for node in ast.walk(task)
        if isinstance(node, ast.Attribute) and node.attr == "conn"
        and isinstance(node.value, ast.Name) and node.value.id == "self"
    ]
    assert not unsafe
