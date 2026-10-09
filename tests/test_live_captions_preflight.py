"""Offline LIVE caption discovery checks; no web or NAS changes."""
from __future__ import annotations

from pathlib import Path
import sqlite3


def _module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_live_captions_preflight as subject
    return subject


def _fixture(tmp_path, *, public=True, live=True):
    db = tmp_path / "rg_youtube_control.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE videos (video_id TEXT, profile TEXT, privacy_status TEXT, scheduled_publish_at TEXT)"
    )
    conn.execute("CREATE TABLE settings (key TEXT, value TEXT)")
    if live:
        conn.execute(
            "INSERT INTO videos VALUES (?, ?, ?, NULL)",
            ("ABCDEFGHIJK", "live", "public" if public else "private"),
        )
    conn.commit()
    conn.close()
    nas = tmp_path / "nas"
    nas.mkdir()
    return db, nas


def test_no_live_archives_never_calls_external_sources(tmp_path, monkeypatch):
    subject = _module(monkeypatch)
    db, nas = _fixture(tmp_path, live=False)
    def never(*_args):
        raise AssertionError("No public lookup permitted")
    result = subject.inspect(
        db_path=db, transcript_dir=nas,
        public_transcript=never, metadata=never,
    )
    assert result["status"] == "NO_PUBLIC_ARCHIVES"
    assert result["public_checked"] == 0
    assert result["youtube_data_api_calls"] == 0


def test_live_available_via_public_transcript_without_nas_srt(tmp_path, monkeypatch):
    subject = _module(monkeypatch)
    db, nas = _fixture(tmp_path)
    calls = []
    def api(video):
        calls.append(video)
        return [{"text": "PRIVATE SPEECH", "start": 0, "duration": 5}]
    result = subject.inspect(
        db_path=db, transcript_dir=nas, public_transcript=api,
        metadata=lambda _: (_ for _ in ()).throw(AssertionError("Unneeded")),
    )
    assert result["status"] == "PUBLIC_CAPTIONS_AVAILABLE"
    assert result["public_transcript_available"] == 1
    assert result["public_checked"] == 1
    assert calls == ["ABCDEFGHIJK"]
    assert "ABCDEFGHIJK" not in str(result)
    assert "PRIVATE SPEECH" not in str(result)
    assert result["source_text_exported"] is False


def test_live_alt_caption_track_can_succeed(tmp_path, monkeypatch):
    subject = _module(monkeypatch)
    db, nas = _fixture(tmp_path)
    result = subject.inspect(
        db_path=db, transcript_dir=nas,
        public_transcript=lambda _: [],
        metadata=lambda _: {"_caption_tracks": {"automatic": {"ru": [{"url": "PRIVATE"}]}}},
        metadata_captions=lambda _: [{"text": "PRIVATE SPEECH"}],
    )
    assert result["status"] == "PUBLIC_CAPTIONS_AVAILABLE"
    assert result["yt_dlp_captions_available"] == 1
    assert "PRIVATE" not in str(result)


def test_private_or_future_live_videos_never_sampled(tmp_path, monkeypatch):
    subject = _module(monkeypatch)
    db, nas = _fixture(tmp_path, public=False)
    result = subject.inspect(
        db_path=db, transcript_dir=nas,
        public_transcript=lambda *_: (_ for _ in ()).throw(AssertionError("No lookup")),
    )
    assert result["status"] == "NO_PUBLIC_ARCHIVES"
    assert result["public_checked"] == 0


def test_live_missing_all_sources_reports_real_blocker(tmp_path, monkeypatch):
    subject = _module(monkeypatch)
    db, nas = _fixture(tmp_path)
    result = subject.inspect(
        db_path=db, transcript_dir=nas,
        public_transcript=lambda *_: [],
        metadata=lambda *_: {},
    )
    assert result["status"] == "NO_CAPTIONS_IN_SAMPLE"
    assert result["no_caption_source_found"] == 1
    assert result["youtube_modified"] is False
    assert result["nas_modified"] is False
