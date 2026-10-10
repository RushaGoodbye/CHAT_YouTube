"""Offline contract for a full, private LIVE semantic QA trial."""
from __future__ import annotations

from pathlib import Path
import sqlite3


def _pilot(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_real_live_seo_qa as module
    return module


def _db(folder: Path, video_id="ABCDEFGHIJK", *, source_description="PRIVATE ORIGINAL DESCRIPTION", source_tags=None, duration="PT3H0M0S"):
    db = folder / "rg_youtube_control.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE videos (video_id TEXT, title TEXT, profile TEXT, "
        "scheduled_publish_at TEXT, privacy_status TEXT, duration TEXT, "
        "views INTEGER, channel_id TEXT, published_at TEXT)"
    )
    conn.execute(
        "INSERT INTO videos VALUES (?, ?, 'live', NULL, 'public', "
        "?, 1, 'PRIVATE', '2026-01-01')",
        (video_id, "PRIVATE VIDEO TITLE", duration),
    )
    conn.execute(
        "CREATE TABLE optimization_drafts "
        "(video_id TEXT, source_description TEXT, source_tags_json TEXT)"
    )
    conn.execute(
        "INSERT INTO optimization_drafts VALUES (?, ?, ?)",
        (video_id, source_description,
         '["PRIVATE ORIGINAL TAG"]' if source_tags is None else source_tags),
    )
    conn.execute(
        "CREATE TABLE metadata_history "
        "(video_id TEXT, description TEXT, tags_json TEXT, "
        "created_at TEXT, history_id INTEGER)"
    )
    conn.commit()
    conn.close()
    return db


def test_missing_db_does_not_contact_youtube_or_ollama(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "fetch_transcript", lambda _: (_ for _ in ()).throw(AssertionError("No web")))
    result = p.run()
    assert result["status"] == "NOT_READY"
    assert result["source_text_exported"] is False
    assert result["youtube_data_api_calls"] == 0


def test_live_anonymous_success_does_not_export_source_text(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path)
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "fetch_transcript", lambda _: [
        {"text": "PRIVATE CAPTION " + str(n), "start": n * 30, "duration": 5}
        for n in range(30)
    ])
    report = {
        "source_integrity_verified": True,
        "blocks_total": 3,
        "blocks_with_evidence": 3,
        "source_rows_with_text": 30,
        "blocks": [],
    }
    monkeypatch.setattr(p, "analyze_all_timeline_blocks", lambda *_a, **_k: report)
    monkeypatch.setattr(p, "generate_seo_package_local", lambda **_k: {
        "title": "PRIVATE VIDEO TITLE",
        "description": "PRIVATE SEO DESCRIPTION",
        "title_variants": ["PRIVATE A", "PRIVATE B", "PRIVATE C"],
        "tags": ["PRIVATE TAG"],
    })
    monkeypatch.setattr(p, "review_seo_package", lambda **_k: [])
    result = p.run()
    assert result["status"] == "STRUCTURE_PASS"
    assert result["grounded_blocks"] == 3
    assert result["ab_titles_count"] == 3
    assert result["semantic_gate_warnings_count"] == 0
    assert result["youtube_modified"] is False
    assert "PRIVATE" not in str(result)
    assert "ABCDEFGHIJK" not in str(result)


def test_review_warnings_only_report_categories(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path)
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "fetch_transcript", lambda _: [
        {"text": "PRIVATE CAPTION " + str(n), "start": n * 30}
        for n in range(30)
    ])
    monkeypatch.setattr(p, "analyze_all_timeline_blocks", lambda *_a, **_k: {
        "source_integrity_verified": True, "blocks_total": 3,
        "blocks_with_evidence": 3, "source_rows_with_text": 30, "blocks": [],
    })
    monkeypatch.setattr(p, "generate_seo_package_local", lambda **_k: {
        "title": "PRIVATE VIDEO TITLE", "description": "PRIVATE",
        "title_variants": ["AA", "BB", "CC"], "tags": [],
    })
    monkeypatch.setattr(p, "review_seo_package", lambda **_k: [
        "В описі немає жодної дослівної цитати PRIVATE_PERSON"
    ])
    result = p.run()
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["semantic_gate_warning_categories"] == ["EVIDENCE_QUOTES"]
    assert "PRIVATE_PERSON" not in str(result)


def test_long_live_mode_rejects_short_sample(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path)
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "fetch_transcript", lambda _: [
        {"text": "PRIVATE CAPTION " + str(n), "start": n * 30, "duration": 5}
        for n in range(30)
    ])
    monkeypatch.setattr(p, "analyze_all_timeline_blocks", lambda *_a, **_k:
                        (_ for _ in ()).throw(AssertionError("Do not analyze short LIVE")))
    result = p.run(require_long_live=True)
    assert result["status"] == "NOT_READY"
    assert result["length_profile"] == "long"
    assert result["caption_lookups"] == 1
    assert "long LIVE" in result["reason"]
    assert result["youtube_modified"] is False


def test_long_live_mode_accepts_at_least_15_blocks(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path)
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "fetch_transcript", lambda _: [
        {"text": "PRIVATE CAPTION " + str(n), "start": n * 60, "duration": 5}
        for n in range(180)
    ])
    monkeypatch.setattr(p, "analyze_all_timeline_blocks", lambda *_a, **_k: {
        "source_integrity_verified": True, "blocks_total": 180,
        "blocks_with_evidence": 180, "source_rows_with_text": 180, "blocks": [],
    })
    monkeypatch.setattr(p, "generate_seo_package_local", lambda **_k: {
        "title": "PRIVATE VIDEO TITLE", "description": "PRIVATE SEO",
        "title_variants": ["A", "B", "C"], "tags": [],
    })
    monkeypatch.setattr(p, "review_seo_package", lambda **_k: [])
    result = p.run(require_long_live=True)
    assert result["length_profile"] == "long"
    assert result["status"] == "STRUCTURE_PASS"
    assert result["youtube_modified"] is False
    assert "PRIVATE" not in str(result)


def test_live_qa_passes_original_metadata_to_generator_and_quality_gate(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    original = "PRIVATE NOTE https://donate.rginfoua.pp.ua"
    _db(tmp_path, source_description=original)
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "fetch_transcript", lambda _: [
        {"text": "PRIVATE CAPTION " + str(n), "start": n * 30, "duration": 5}
        for n in range(30)
    ])
    monkeypatch.setattr(p, "analyze_all_timeline_blocks", lambda *_a, **_k: {
        "source_integrity_verified": True, "blocks_total": 3,
        "blocks_with_evidence": 3, "source_rows_with_text": 30, "blocks": [],
    })
    seen = {}
    def generate(**kwargs):
        seen["generation"] = kwargs
        return {
            "title": "PRIVATE VIDEO TITLE", "description": "PRIVATE SHORT DESCRIPTION",
            "title_variants": ["PRIVATE A", "PRIVATE B", "PRIVATE C"], "tags": ["NEW TAG"],
        }
    def review(**kwargs):
        seen["review"] = kwargs
        return ["Новий опис втратив посилання з оригіналу."]
    monkeypatch.setattr(p, "generate_seo_package_local", generate)
    monkeypatch.setattr(p, "review_seo_package", review)
    result = p.run()
    assert seen["generation"]["current_description"] == original
    assert seen["generation"]["current_tags"] == ["PRIVATE ORIGINAL TAG"]
    assert seen["review"]["original_description"] == original
    assert seen["review"]["original_tags"] == ["PRIVATE ORIGINAL TAG"]
    assert seen["review"]["tags"] == ["NEW TAG"]
    assert result["status"] == "REVIEW_REQUIRED"
    assert "PRIVATE NOTE" not in str(result)
    assert "PRIVATE ORIGINAL TAG" not in str(result)
    assert result["youtube_data_api_calls"] == 0


def test_live_qa_missing_original_description_fails_closed(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path, source_description="")
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "fetch_transcript", lambda _: (_ for _ in ()).throw(
        AssertionError("No network without cached source metadata")
    ))
    result = p.run()
    assert result["status"] == "NOT_READY"
    assert result["archives_with_cached_original_description"] == 0
    assert result["caption_lookups"] == 0
    assert result["youtube_modified"] is False


def test_long_live_rejects_short_metadata_without_caption_fetch(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path, duration="PT1H30M0S")
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "fetch_transcript", lambda _: (_ for _ in ()).throw(
        AssertionError("Short archives must not be fetched for long LIVE QA")
    ))
    result = p.run(require_long_live=True)
    assert result["status"] == "NOT_READY"
    assert result["caption_lookups"] == 0
    assert result["youtube_modified"] is False


def test_long_live_rejects_sparse_three_hour_caption_excerpt(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path, duration="PT3H0M0S")
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    # Thirty captions scattered across three hours are not full coverage.
    monkeypatch.setattr(p, "fetch_transcript", lambda _: [
        {"text": "PRIVATE EXCERPT " + str(n), "start": n * 360}
        for n in range(30)
    ])
    monkeypatch.setattr(p, "analyze_all_timeline_blocks", lambda *_a, **_k:
                        (_ for _ in ()).throw(AssertionError("Incomplete captions")))
    result = p.run(require_long_live=True)
    assert result["status"] == "NOT_READY"
    assert result["caption_lookups"] == 1


def test_temporal_preflight_requires_first_and_last_caption(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    complete = [
        {"text": "PRIVATE REAL CAPTION", "start": n * 60, "duration": 15}
        for n in range(180)
    ]
    assert p._captions_span_full_long_live(complete, 10800)
    missing_end = complete[:-22]
    assert not p._captions_span_full_long_live(missing_end, 10800)
    missing_start = complete[20:]
    assert not p._captions_span_full_long_live(missing_start, 10800)
