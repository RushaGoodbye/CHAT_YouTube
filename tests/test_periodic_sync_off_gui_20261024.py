"""Scheduled polling of both YouTube channels never borrows UI SQLite."""
import ast
from pathlib import Path


def test_periodic_sync_runs_in_worker_owned_connection():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def background_metadata_sync(")
    end = source.index("\n    def ", start + 6)
    method = source[start:end]
    assert "LocalToolWorker(task, self)" in method
    assert "worker_conn = sqlite3.connect(str(db_path), timeout=15)" in method
    assert "sync_videos(client, worker_conn, limit=50)" in method
    assert "sync_upcoming_live_broadcasts(client, worker_conn)" in method
    assert "worker_conn.close()" in method
    tree = ast.parse("class T:\n" + method)
    task = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "task"
    )
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "conn"
        and isinstance(node.value, ast.Name) and node.value.id == "self"
        for node in ast.walk(task)
    )


def test_periodic_sync_reports_results_on_main_thread():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _on_background_metadata_synced(")
    end = source.index("\n    def ", start + 6)
    callback = source[start:end]
    assert "self.reload_videos()" in callback
    assert "self.reload_optimization_queue()" in callback
    assert "self.update_dashboard()" in callback
