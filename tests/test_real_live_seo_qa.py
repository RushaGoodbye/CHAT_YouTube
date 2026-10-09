"""Offline contract for a full, private LIVE semantic QA trial."""
from __future__ import annotations

from pathlib import Path
import sqlite3


def _pilot(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_real_live_seo_qa as module
    return module


def _db(folder: Path, video_id="ABCDEFGHIJK"):
    db = folder / "rg_youtube_control.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE videos (video_id TEXT, title TEXT, profile TEXT, "
        "scheduled_publish_at TEXT, privacy_status TEXT)"
    )
    conn.execute(
        "INSERT INTO videos VALUES (?, ?, 'live', NULL, 'public')",
        (video_id, "PRIVATE VIDEO TITLE"),
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
