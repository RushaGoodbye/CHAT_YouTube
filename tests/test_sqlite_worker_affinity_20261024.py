"""Verify local SEO's worker never borrows the GUI's SQLite connection."""
from pathlib import Path
import sqlite3
import threading


def test_sqlite_connection_is_thread_affine(tmp_path):
    conn = sqlite3.connect(tmp_path / "test.db")
    errors = []
    try:
        thread = threading.Thread(target=lambda: _probe_foreign_thread(conn, errors))
        thread.start()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert errors and isinstance(errors[0], sqlite3.ProgrammingError)
    finally:
        conn.close()


def _probe_foreign_thread(conn, errors):
    try:
        conn.execute("SELECT 1")
    except Exception as exc:
        errors.append(exc)


def test_local_seo_worker_uses_own_sqlite_connection():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _generate_local_seo_result(")
    end = source.index("    def _normalize_local_seo_package(", start)
    block = source[start:end]
    assert "sqlite3.connect(" in block
    assert "state_conn.close()" in block
    assert "self.conn" not in block
