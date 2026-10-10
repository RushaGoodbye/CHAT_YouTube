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


def test_nas_first_long_live_preflight_never_contacts_public_or_ollama(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path, duration="PT3H0M0S")
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    nas = tmp_path / "nas"
    nas.mkdir()
    (nas / "ABCDEFGHIJK.srt").write_text("PRIVATE SRT PLACEHOLDER", encoding="utf-8")
    monkeypatch.setattr(p, "normalize_nas_unc_path", lambda _raw, _default: str(nas))
    monkeypatch.setattr(p, "load_srt_transcript", lambda _path: [
        {"text": "PRIVATE NAS CAPTION " + str(n), "start": n * 60, "duration": 15}
        for n in range(180)
    ])
    def forbidden(*_a, **_k):
        raise AssertionError("Preflight must not contact public captions or Ollama")
    monkeypatch.setattr(p, "fetch_transcript", forbidden)
    monkeypatch.setattr(p, "analyze_all_timeline_blocks", forbidden)
    monkeypatch.setattr(p, "generate_seo_package_local", forbidden)
    result = p.run(require_long_live=True, preflight_only=True, max_caption_lookups=0)
    assert result["status"] == "SOURCE_READY"
    assert result["nas_srt_sources_available"] == 1
    assert result["selected_source_type"] == "nas-srt"
    assert result["selected_timeline_blocks"] >= 15
    assert result["caption_lookups"] == 0
    assert result["semantic_quality_verified"] is False
    assert result["youtube_data_api_calls"] == 0
    assert result["youtube_modified"] is False
    assert "PRIVATE NAS CAPTION" not in str(result)
    assert "ABCDEFGHIJK" not in str(result)


def test_preflight_without_nas_and_zero_probes_never_uses_network(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path, duration="PT3H0M0S")
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "normalize_nas_unc_path",
                        lambda _raw, _default: str(tmp_path / "missing-nas"))
    monkeypatch.setattr(p, "fetch_transcript", lambda _id: (
        _ for _ in ()
    ).throw(AssertionError("Zero caption budget must prohibit network")))
    result = p.run(require_long_live=True, preflight_only=True, max_caption_lookups=0)
    assert result["status"] == "NOT_READY"
    assert result["caption_lookups"] == 0
    assert result["source_ready"] is False
    assert result["youtube_modified"] is False


def test_public_captions_fallback_works_when_nas_source_missing(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    _db(tmp_path, duration="PT3H0M0S")
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(p, "normalize_nas_unc_path",
                        lambda _raw, _default: str(tmp_path / "missing-nas"))
    monkeypatch.setattr(p, "fetch_transcript", lambda _id: [
        {"text": "PRIVATE PUBLIC CAPTION " + str(n), "start": n * 60}
        for n in range(180)
    ])
    monkeypatch.setattr(p, "analyze_all_timeline_blocks", lambda *_a, **_k:
                        (_ for _ in ()).throw(AssertionError("No AI in preflight")))
    result = p.run(require_long_live=True, preflight_only=True, max_caption_lookups=1)
    assert result["status"] == "SOURCE_READY"
    assert result["selected_source_type"] == "public-captions"
    assert result["caption_lookups"] == 1
    assert result["youtube_data_api_calls"] == 0


def test_long_live_filters_duration_before_bounded_source_probe(tmp_path, monkeypatch):
    p = _pilot(monkeypatch)
    db = _db(tmp_path, duration="PT3H0M0S")
    conn = sqlite3.connect(db)
    for i in range(45):
        short_id = "Z" + str(i).zfill(10)
        conn.execute(
            "INSERT INTO videos VALUES (?, ?, 'live', NULL, 'public', "
            "'PT20M0S', 1, 'PRIVATE', '2026-01-02')",
            (short_id, "PRIVATE SHORT TITLE"),
        )
        conn.execute(
            "INSERT INTO optimization_drafts VALUES (?, ?, ?)",
            (short_id, "PRIVATE ORIGINAL SHORT DESCRIPTION", "[]"),
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(p, "app_data_dir", lambda: tmp_path)
    nas = tmp_path / "nas"
    nas.mkdir()
    (nas / "ABCDEFGHIJK.srt").write_text("PRIVATE SOURCE", encoding="utf-8")
    monkeypatch.setattr(p, "normalize_nas_unc_path", lambda _raw, _default: str(nas))
    monkeypatch.setattr(p, "load_srt_transcript", lambda _path: [
        {"text": "PRIVATE FULL CAPTION " + str(n), "start": n * 60}
        for n in range(180)
    ])
    monkeypatch.setattr(p, "fetch_transcript", lambda _id: (_ for _ in ()).throw(
        AssertionError("The long NAS source must take priority")
    ))
    result = p.run(
        require_long_live=True, preflight_only=True,
        max_caption_lookups=0, max_nas_candidates=2,
    )
    assert result["available_public_archives"] == 46
    assert result["duration_qualified_source_archives"] == 1
    assert result["nas_srt_candidates_checked"] == 1
    assert result["status"] == "SOURCE_READY"
    assert "PRIVATE" not in str(result)


def test_public_long_source_preflight_detects_real_source_without_export(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_long_live_public_source_preflight as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    result = subject.run(
        db_path=db,
        metadata_fetch=lambda _id: {
            "video_id": "ABCDEFGHIJK",
            "description": "PRIVATE REAL DESCRIPTION",
            "tags": ["PRIVATE REAL TAG"],
            "duration": 10800,
        },
        transcript_fetch=lambda _id: [
            {"text": "PRIVATE REAL TRANSCRIPT " + str(n), "start": n * 60, "duration": 20}
            for n in range(180)
        ],
        track_fetch=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Alternative captions not needed")
        ),
    )
    assert result["public_long_candidates"] == 1
    assert result["original_description_retrieved"] == 1
    assert result["captions_retrieved"] == 1
    assert result["full_span_caption_sources"] == 1
    assert result["ready_source_candidates"] == 1
    assert result["status"] == "SOURCE_READY"
    assert result["youtube_data_api_calls"] == 0
    assert result["youtube_modified"] is False
    assert result["ollama_called"] is False
    assert "PRIVATE" not in str(result)
    assert "ABCDEFGHIJK" not in str(result)


def test_public_long_source_preflight_rejects_wrong_video_metadata(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_long_live_public_source_preflight as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    result = subject.run(
        db_path=db,
        metadata_fetch=lambda _id: {
            "video_id": "ZZZZZZZZZZZ",
            "description": "PRIVATE WRONG VIDEO",
            "duration": 10800,
        },
        transcript_fetch=lambda _id: (_ for _ in ()).throw(
            AssertionError("Mismatched source must not fetch transcript")
        ),
    )
    assert result["status"] == "NOT_READY"
    assert result["metadata_identifier_mismatches"] == 1
    assert result["captions_retrieved"] == 0


def test_public_long_source_preflight_missing_full_captions_stays_not_ready(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_long_live_public_source_preflight as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    result = subject.run(
        db_path=db,
        metadata_fetch=lambda _id: {
            "video_id": "ABCDEFGHIJK",
            "description": "PRIVATE PUBLIC DESCRIPTION",
            "tags": [],
            "duration": 10800,
        },
        transcript_fetch=lambda _id: [
            {"text": "PRIVATE SHORT CAPTION", "start": n * 30}
            for n in range(30)
        ],
    )
    assert result["original_description_retrieved"] == 1
    assert result["captions_retrieved"] == 1
    assert result["full_span_caption_sources"] == 0
    assert result["status"] == "NOT_READY"


def test_public_probe_still_checks_captions_when_metadata_bot_blocked(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_long_live_public_source_preflight as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    def blocked(_video):
        raise RuntimeError("Sign in to confirm you're not a bot")
    result = subject.run(
        db_path=db,
        metadata_fetch=blocked,
        transcript_fetch=lambda _id: [
            {"text": "PRIVATE LONG CAPTION " + str(n), "start": n * 60}
            for n in range(180)
        ],
        track_fetch=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("No yt-dlp caption track without metadata")
        ),
    )
    assert result["public_metadata_access_denied"] == 1
    assert result["captions_retrieved"] == 1
    assert result["full_span_caption_sources"] == 1
    assert result["original_description_retrieved"] == 0
    assert result["ready_source_candidates"] == 0
    assert result["status"] == "NOT_READY"
    assert result["youtube_data_api_calls"] == 0
    assert "PRIVATE" not in str(result)
