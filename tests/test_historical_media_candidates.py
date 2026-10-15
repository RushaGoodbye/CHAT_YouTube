import sqlite3
from rg_youtube_control.historical_media_candidates import historical_media_candidates


def test_previous_title_finds_local_candidate(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE videos(video_id TEXT, title TEXT)")
    conn.execute("CREATE TABLE metadata_history(video_id TEXT, title TEXT, created_at TEXT)")
    conn.execute("INSERT INTO videos VALUES ('AbCdEfGhI12','Новий заголовок vidIQ')")
    conn.execute("INSERT INTO metadata_history VALUES ('AbCdEfGhI12','СКАЗОЧНЫЕ ЕМЕЛИ','2026-01-01')")
    media = tmp_path / "СКАЗОЧНЫЕ ЕМЕЛИ.mp4"
    media.write_bytes(b"video")
    results = historical_media_candidates(conn, "AbCdEfGhI12", [tmp_path])
    assert results and results[0][1] == media
    assert results[0][2] == "СКАЗОЧНЫЕ ЕМЕЛИ"
