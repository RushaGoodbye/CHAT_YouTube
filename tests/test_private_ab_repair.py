"""Offline acceptance for source-grounded private title-only recovery."""
import json
import sqlite3
from pathlib import Path


VIDEO = "ABCDEFGHIJK"
GOOD = [
    "Собеседник о ценах на бензин в России",
    "Спор на АЗС: почему выросли цены на топливо",
    "Бензин и зарплаты: ответы жителей России",
]


def _setup(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_private_ab_repair as qa

    root = tmp_path / "private"
    (root / "private_drafts").mkdir(parents=True)
    (root / "private_source").mkdir(parents=True)
    (root / "private_source" / (VIDEO + ".srt")).write_text(
        "PRIVATE CAPTION", encoding="utf-8"
    )
    p = root / "private_drafts" / (VIDEO + ".json")
    p.write_text(json.dumps({
        "schema": "RG_PRIVATE_LONG_LIVE_DRAFT_V1",
        "video_id": VIDEO, "review_required": True,
        "source_title": "Бензин в России",
        "source_description": "PRIVATE ORIGINAL DESCRIPTION",
        "source_tags": ["чат рулетка"],
        "package": {
            "title": "Бензин в России - обсуждение цен",
            "description": "PRIVATE DESCRIPTION",
            "title_variants": ["Россияне о бензине", "Цены на бензин"],
            "tags": ["бензин"],
        },
    }, ensure_ascii=False), encoding="utf-8")
    db = tmp_path / "test.db"
    sqlite3.connect(db).close()
    monkeypatch.setattr(qa, "cached_public_metadata", lambda *_a: {
        "duration": 10800,
        "scheduled_publish_at": "",
        "privacy_status": "public",
    })
    monkeypatch.setattr(qa, "load_srt_transcript", lambda _p: [
        {"text": "PRIVATE CAPTION", "start": 0},
    ])
    monkeypatch.setattr(qa, "_captions_span_full_long_live", lambda *_a: True)
    monkeypatch.setattr(qa, "analyze_all_timeline_blocks", lambda *_a, **_kw: {
        "source_integrity_verified": True,
        "blocks_total": 2, "blocks_with_evidence": 2,
        "cache_hits": 2, "unverified_blocks": [],
        "blocks": [{
            "topics": [{
                "topic": "ціни на бензин",
                "evidence": "PRIVATE CAPTION",
                "summary_uk": "PRIVATE SUMMARY",
            }],
            "start_stamp": "00:00:00",
        }],
    })
    monkeypatch.setattr(qa, "ab_title_issues", lambda values, *_a: (
        [] if list(values) == GOOD else ["Not three grounded titles"]
    ))
    monkeypatch.setattr(qa, "review_seo_package", lambda **kw: (
        ["Other source review warning"] if kw["variants"] == GOOD
        else ["Old A/B warning", "Other source review warning"]
    ))
    return qa, root, db, p


def test_title_only_improves_private_draft_without_source_export(tmp_path, monkeypatch):
    qa, root, db, p = _setup(tmp_path, monkeypatch)
    result = qa.run(
        private_root=root, db_path=db,
        recover=lambda **_kw: GOOD,
    )
    assert result["status"] == "IMPROVED_REVIEW_DRAFT"
    assert result["previous_ab_titles_count"] == 2
    assert result["candidate_ab_titles_count"] == 3
    assert result["previous_gate_warnings"] == 2
    assert result["candidate_gate_warnings"] == 1
    assert result["ollama_title_calls"] == 1
    assert result["private_draft_updated"] is True
    assert json.loads(p.read_text(encoding="utf-8"))["package"]["title_variants"] == GOOD
    assert "PRIVATE ORIGINAL DESCRIPTION" not in str(result)
    assert "PRIVATE CAPTION" not in str(result)
    assert "PRIVATE SUMMARY" not in str(result)
    assert VIDEO not in str(result)
    assert result["youtube_data_api_calls"] == 0
    assert result["youtube_modified"] is False


def test_bad_title_recovery_does_not_overwrite_private_draft(tmp_path, monkeypatch):
    qa, root, db, p = _setup(tmp_path, monkeypatch)
    before = p.read_bytes()
    result = qa.run(
        private_root=root, db_path=db,
        recover=lambda **_kw: ["Not grounded", "Still not grounded"],
    )
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["private_draft_updated"] is False
    assert p.read_bytes() == before
    assert result["youtube_modified"] is False


def test_missing_cached_blocks_prevents_title_model_call(tmp_path, monkeypatch):
    qa, root, db, p = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(qa, "analyze_all_timeline_blocks", lambda *_a, **_kw: {
        "source_integrity_verified": True,
        "blocks_total": 2, "blocks_with_evidence": 1,
        "cache_hits": 1, "unverified_blocks": [2],
    })
    called = []
    result = qa.run(
        private_root=root, db_path=db,
        recover=lambda **_kw: called.append(1) or GOOD,
    )
    assert result["status"] == "NOT_READY"
    assert result["private_draft_updated"] is False
    assert called == []


def test_invalid_model_titles_fallback_to_verified_timeline_topic(tmp_path, monkeypatch):
    qa, root, db, draft_path = _setup(tmp_path, monkeypatch)
    verified = {
        "source_integrity_verified": True,
        "blocks_total": 1, "blocks_with_evidence": 1,
        "cache_hits": 1, "unverified_blocks": [],
        "blocks": [{
            "verified": True, "start_stamp": "00:00:00",
            "topics": [{
                "topic": "Ціни на бензин у Росії",
                "evidence": "PRIVATE CAPTION",
                "summary_uk": "Розмова про вартість пального",
            }],
        }],
    }
    monkeypatch.setattr(qa, "analyze_all_timeline_blocks", lambda *_a, **_k: verified)
    monkeypatch.setattr(
        qa, "ab_title_issues",
        lambda titles, *_a: [] if len(titles) == 3 else ["Three titles required"],
    )
    monkeypatch.setattr(
        qa, "review_seo_package",
        lambda **kw: ["Manual quote review"] if len(kw["variants"]) == 3
        else ["Incomplete A/B", "Manual quote review"],
    )
    result = qa.run(
        private_root=root, db_path=db,
        recover=lambda **_k: ["Not enough", "Still not enough"],
    )
    assert result["status"] == "IMPROVED_REVIEW_DRAFT"
    assert result["candidate_ab_titles_count"] == 3
    assert result["private_draft_updated"] is True
    package = json.loads(draft_path.read_text(encoding="utf-8"))["package"]
    assert "Ціни на бензин у Росії" in package["title_variants"][2]
    assert result["youtube_data_api_calls"] == 0
    assert "PRIVATE CAPTION" not in str(result)
