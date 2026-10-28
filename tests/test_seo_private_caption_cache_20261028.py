"""Private public-caption QA cache: exact ID, bounded and opt-in.

No production DB writes, YouTube metadata actions, or network in tests.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

QA_SCRIPT = Path(__file__).resolve().parents[1] / "rg_remote_control" / "seo_readonly_acceptance_10.py"


def _qa():
    spec = importlib.util.spec_from_file_location("rg_private_caption_cache_test", QA_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cues():
    return [
        {"text": "Підтверджена дослівна розмова", "start": float(i * 55), "duration": 25.0}
        for i in range(12)
    ]


def test_public_caption_cache_opt_in_roundtrip_no_cross_video(tmp_path, monkeypatch):
    qa = _qa()
    cache = tmp_path / "private"
    vid = "MEitKm687xo"
    monkeypatch.setattr(qa._wall_clock, "time", lambda: 1234567890.0)
    assert qa._read_private_caption_cache(cache, vid, 600) == []
    assert not cache.exists()
    qa._write_private_caption_cache(cache, vid, _cues())
    assert qa._read_private_caption_cache(cache, vid, 600) == _cues()
    assert qa._read_private_caption_cache(cache, "u9y_f4HtEbQ", 600) == []
    assert (cache / f"{vid}.json").is_file()
    assert not (tmp_path / f"{vid}.srt").exists()


def test_cache_expires_and_fails_closed_on_corruption(tmp_path, monkeypatch):
    qa = _qa()
    cache = tmp_path / "private"
    vid = "12345678901"
    monkeypatch.setattr(qa._wall_clock, "time", lambda: 1234567890.0)
    qa._write_private_caption_cache(cache, vid, _cues())
    monkeypatch.setattr(qa._wall_clock, "time", lambda: 1234567890.0 + 15 * 86400)
    assert qa._read_private_caption_cache(cache, vid, 600) == []
    monkeypatch.setattr(qa._wall_clock, "time", lambda: 1234567890.0)
    file = cache / f"{vid}.json"
    file.write_text("{garbled", encoding="utf-8")
    assert qa._read_private_caption_cache(cache, vid, 600) == []
    data = {"video_id": "12345678902", "source": "public_captions",
            "created": 1234567890.0, "rows": _cues()}
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert qa._read_private_caption_cache(cache, vid, 600) == []
    data["video_id"] = vid
    data["source"] = "private_srt"
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert qa._read_private_caption_cache(cache, vid, 600) == []


def test_cached_source_reused_by_selection_without_network(tmp_path, monkeypatch):
    import sqlite3
    qa = _qa()
    cache = tmp_path / "private"
    root = tmp_path / "local_transcripts"
    root.mkdir()
    db = tmp_path / "readonly.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        con.execute("INSERT INTO settings VALUES('nas_transcripts_path',?)", (str(root),))
        con.execute(
            "CREATE TABLE videos(video_id TEXT,profile TEXT,duration TEXT,"
            "scheduled_publish_at TEXT,privacy_status TEXT,views INTEGER)"
        )
        con.execute(
            "INSERT INTO videos VALUES('12345678901','live','PT10M',NULL,'public',1)"
        )
    qa._write_private_caption_cache(cache, "12345678901", _cues())
    monkeypatch.setattr(qa, "fetch_transcript",
                        lambda *_: (_ for _ in ()).throw(AssertionError("Network must not be called")))
    original_db = db.read_bytes()
    result = qa.select_existing_srt_videos(
        db, "live", 1, allow_public_captions=True,
        preflight_captions=True, private_caption_cache=cache,
    )
    assert result == ["12345678901"]
    assert qa._PREFLIGHT_PUBLIC_CAPTIONS["12345678901"] == _cues()
    assert db.read_bytes() == original_db
