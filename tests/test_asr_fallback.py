from __future__ import annotations

import sqlite3

from rg_youtube_control import asr_fallback


def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE videos(
            video_id TEXT,title TEXT,duration TEXT,views INTEGER,profile TEXT
        );
        CREATE TABLE optimization_drafts(
            video_id TEXT,status TEXT,generation TEXT,quality_state TEXT,
            title_variants_json TEXT,new_title TEXT,description TEXT,tags_json TEXT
        );
        INSERT INTO videos VALUES ('Oh6mcqc_YZo','Long interview','PT16M39S',100,'main');
        INSERT INTO optimization_drafts
        VALUES ('Oh6mcqc_YZo','ready','legacy','','[]','Long interview','','[]');
    """)
    conn.commit()
    conn.close()


def test_asr_dry_run_has_no_gpu_or_download(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    srt = tmp_path / "srt"
    srt.mkdir()
    _db(db)
    monkeypatch.setattr(
        asr_fallback, "_whisper_model",
        lambda: (_ for _ in ()).throw(AssertionError("model must not start"))
    )
    monkeypatch.setattr(
        asr_fallback, "download_audio",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no download"))
    )
    out = asr_fallback.run_asr(
        db_path=db, srt_dir=srt, temp_dir=tmp_path / "temp",
        profile="main", limit=1, execute=False,
    )
    assert out["status_counts"] == {"dry_run": 1}
    assert out["youtube_data_api_units_used"] == 0
    assert out["youtube_metadata_modified"] is False
    assert not (srt / "Oh6mcqc_YZo.srt").exists()


def test_busy_gpu_skips_without_starting_model(tmp_path, monkeypatch):
    db = tmp_path / "videos.db"
    srt = tmp_path / "srt"
    srt.mkdir()
    _db(db)
    monkeypatch.setattr(asr_fallback, "gpu_capacity", lambda: (False, "busy"))
    monkeypatch.setattr(
        asr_fallback, "_whisper_model",
        lambda: (_ for _ in ()).throw(AssertionError("must not start"))
    )
    out = asr_fallback.run_asr(
        db_path=db, srt_dir=srt, temp_dir=tmp_path / "temp",
        profile="main", limit=1, execute=True,
    )
    assert out["status_counts"] == {"skipped_gpu_busy": 1}


def test_exact_video_id_is_required_for_audio(tmp_path):
    try:
        asr_fallback.download_audio("../evil", tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("An invalid video ID was accepted")
