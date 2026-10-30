"""Real long-form livestream preflight must not silently test minute-long clips."""
import sqlite3
from rg_remote_control.seo_readonly_acceptance_10 import select_existing_srt_videos


def _db(tmp_path):
    path = tmp_path / "qa.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE settings(key TEXT, value TEXT)")
        db.execute("INSERT INTO settings VALUES (?, ?)",
                   ("nas_transcripts_path", str(tmp_path / "captions")))
        db.execute(
            "CREATE TABLE videos(video_id TEXT, profile TEXT, duration TEXT,"
            " scheduled_publish_at TEXT, privacy_status TEXT, views INTEGER)"
        )
        data = [
            ("abcde123456", "live", "PT1M34S", None, "public", 90000),
            ("abcde123457", "live", "PT1M50S", None, "public", 80000),
            ("abcde123458", "live", "PT2H30M", None, "public", 500),
            ("abcde123459", "live", "PT1H15M", None, "public", 400),
            ("abcde123460", "live", "PT29M59S", None, "public", 70000),
            ("abcde123461", "main", "PT10M", None, "public", 300),
        ]
        db.executemany("INSERT INTO videos VALUES (?,?,?,?,?,?)", data)
    return path


def test_full_stream_qa_selects_two_real_long_recordings_not_high_view_clips(tmp_path):
    db = _db(tmp_path)
    selected = select_existing_srt_videos(
        db, "live", 2, allow_public_captions=True,
        preflight_captions=False,
    )
    assert selected == ["abcde123458", "abcde123459"], selected


def test_long_stream_selection_reports_shortfall_instead_of_padding(tmp_path):
    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM videos WHERE video_id='abcde123459'")
    selected = select_existing_srt_videos(
        db, "live", 2, allow_public_captions=True,
        preflight_captions=False,
    )
    assert selected == ["abcde123458"], selected


def test_main_video_minimum_is_independent_of_full_live_floor(tmp_path):
    db = _db(tmp_path)
    selected = select_existing_srt_videos(
        db, "main", 1, allow_public_captions=True,
        preflight_captions=False,
    )
    assert selected == ["abcde123461"]
