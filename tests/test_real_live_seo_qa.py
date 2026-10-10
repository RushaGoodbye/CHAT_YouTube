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


def test_owner_live_readonly_metadata_one_request_without_export(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_long_live_owner_source_preflight as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    seen = {}
    class FakeClient:
        def __init__(self, *, profile):
            assert profile == "live"
        def credentials(self):
            return object()
        def video_details_with_request_count(self, video_ids):
            seen["ids"] = video_ids
            return ([{
                "id": "ABCDEFGHIJK",
                "snippet": {
                    "channelId": "PRIVATE",
                    "description": "PRIVATE ORIGINAL https://donate.rginfoua.pp.ua",
                    "tags": ["PRIVATE SOURCE TAG"],
                },
            }], 1)
    result = subject.run(db_path=db, client_factory=FakeClient)
    assert seen["ids"] == ["ABCDEFGHIJK"]
    assert result["status"] == "SOURCE_READY"
    assert result["owner_profile_authorized"] is True
    assert result["youtube_data_api_calls"] == 1
    assert result["source_descriptions_available"] == 1
    assert result["source_tags_available"] == 1
    assert result["youtube_modified"] is False
    assert result["db_modified"] is False
    assert "PRIVATE" not in str(result)
    assert "ABCDEFGHIJK" not in str(result)


def test_owner_live_unavailable_auth_never_calls_owner_api(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_long_live_owner_source_preflight as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    class NoToken:
        def __init__(self, *, profile):
            assert profile == "live"
        def credentials(self):
            raise RuntimeError("PRIVATE TOKEN MISSING")
        def video_details_with_request_count(self, ids):
            raise AssertionError("Do not send request without stored credentials")
    result = subject.run(db_path=db, client_factory=NoToken)
    assert result["status"] == "NOT_READY"
    assert result["youtube_data_api_calls"] == 0
    assert result["owner_profile_authorized"] is False
    assert "PRIVATE TOKEN MISSING" not in str(result)


def test_owner_live_wrong_channel_does_not_accept_description(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_long_live_owner_source_preflight as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    class OtherChannel:
        def __init__(self, *, profile):
            pass
        def credentials(self):
            return object()
        def video_details_with_request_count(self, ids):
            return ([{
                "id": "ABCDEFGHIJK",
                "snippet": {
                    "channelId": "WRONG_CHANNEL",
                    "description": "PRIVATE CROSS-CHANNEL SOURCE",
                },
            }], 1)
    result = subject.run(db_path=db, client_factory=OtherChannel)
    assert result["channel_id_mismatch"] == 1
    assert result["source_descriptions_available"] == 0
    assert result["status"] == "NOT_READY"


def test_single_owner_caption_inventory_counts_tracks_and_accounts_quota(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_owner_caption_inventory_once as subject
    from rg_youtube_control.service import today_quota_units
    db = _db(tmp_path, duration="PT3H0M0S")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    monkeypatch.setattr(subject, "quota_budget_status", lambda conn: {
        "exhausted": False, "spendable": 100
    })
    class Fake:
        def __init__(self, *, profile):
            assert profile == "live"
        def credentials(self):
            return object()
        def caption_tracks(self, video_id):
            assert video_id == "ABCDEFGHIJK"
            return [
                {"snippet": {"trackKind": "ASR", "language": "ru"}},
                {"snippet": {"trackKind": "standard", "language": "uk"}},
            ]
    result = subject.run(db_path=db, client_factory=Fake)
    assert result["status"] == "TRACKS_FOUND"
    assert result["available_tracks"] == 2
    assert result["asr_tracks"] == 1
    assert result["caption_downloads"] == 0
    assert result["quota_units_accounted"] == 50
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        assert today_quota_units(conn) == 50
    assert "ABCDEFGHIJK" not in str(result)


def test_single_owner_caption_inventory_respects_quota_reserve(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_owner_caption_inventory_once as subject
    db = _db(tmp_path, duration="PT3H0M0S")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    monkeypatch.setattr(subject, "quota_budget_status", lambda conn: {
        "exhausted": False, "spendable": 49
    })
    def never(**_kw):
        raise AssertionError("No credentials or API calls below reserve")
    result = subject.run(db_path=db, client_factory=never)
    assert result["status"] == "SKIPPED_BUDGET"
    assert result["caption_lists_requested"] == 0
    assert result["quota_units_accounted"] == 0


def test_owner_long_srt_oneshot_privately_stages_full_source(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_owner_caption_download_once as subject
    from rg_youtube_control.service import today_quota_units
    db = _db(tmp_path, duration="PT3H0M0S")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    monkeypatch.setattr(subject, "quota_budget_status", lambda conn: {
        "exhausted": False, "spendable": 300
    })
    def stamp(n):
        return f"{n // 3600:02}:{(n // 60) % 60:02}:{n % 60:02},000"
    sample = "\n\n".join(
        f"{i+1}\n{stamp(i*60)} --> {stamp(i*60+20)}\nPRIVATE CAPTION {i}"
        for i in range(180)
    )
    class Fake:
        def __init__(self, *, profile):
            assert profile == "live"
        def credentials(self):
            return object()
        def caption_tracks(self, _video_id):
            return [{"id": "PRIVATE TRACK", "snippet": {
                "trackKind": "ASR", "language": "ru"
            }}]
        def download_caption_srt(self, caption_id):
            assert caption_id == "PRIVATE TRACK"
            return sample
    private_root = tmp_path / "private"
    result = subject.run(
        db_path=db, private_root=private_root, client_factory=Fake
    )
    assert result["status"] == "SOURCE_STAGED"
    assert result["local_private_source_staged"] is True
    assert result["full_span_coverage"] is True
    assert result["caption_rows"] == 180
    assert result["quota_units_accounted"] == 250
    assert result["api_requests_sent"] == 2
    assert (private_root / "ABCDEFGHIJK.srt").read_text() == sample
    assert "PRIVATE CAPTION" not in str(result)
    assert "ABCDEFGHIJK" not in str(result)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        assert today_quota_units(conn) == 250


def test_owner_long_srt_oneshot_never_calls_api_below_quota_reserve(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_owner_caption_download_once as subject
    db = _db(tmp_path, duration="PT3H0M0S")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    monkeypatch.setattr(subject, "quota_budget_status", lambda _conn: {
        "exhausted": False, "spendable": 249
    })
    result = subject.run(
        db_path=db, private_root=tmp_path / "private",
        client_factory=lambda **_kw: (_ for _ in ()).throw(
            AssertionError("No API authorization when reserve prohibits")
        ),
    )
    assert result["status"] == "SKIPPED_BUDGET"
    assert result["api_requests_sent"] == 0
    assert result["quota_units_accounted"] == 0


def test_owner_long_srt_oneshot_handles_unavailable_download_no_export(
    tmp_path, monkeypatch,
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_owner_caption_download_once as subject
    db = _db(tmp_path, duration="PT3H0M0S")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    monkeypatch.setattr(subject, "quota_budget_status", lambda _conn: {
        "exhausted": False, "spendable": 300
    })
    class Fake:
        def __init__(self, *, profile):
            pass
        def credentials(self):
            return object()
        def caption_tracks(self, _video_id):
            return [{"id": "PRIVATE TRACK", "snippet": {"trackKind": "ASR"}}]
        def download_caption_srt(self, _caption_id):
            raise PermissionError("PRIVATE FORBIDDEN")
    private_root = tmp_path / "private"
    result = subject.run(
        db_path=db, private_root=private_root, client_factory=Fake
    )
    assert result["status"] == "DOWNLOAD_UNAVAILABLE"
    assert result["quota_units_accounted"] == 250
    assert result["local_private_source_staged"] is False
    assert not private_root.exists()
    assert "PRIVATE FORBIDDEN" not in str(result)


def test_private_long_live_semantic_qa_saves_review_draft_without_export(
    tmp_path, monkeypatch,
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_staged_long_live_semantic_qa as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    root = tmp_path / "private_qa"
    source_dir = root / "private_source"
    source_dir.mkdir(parents=True)
    def stamp(n):
        return f"{n//3600:02}:{(n//60)%60:02}:{n%60:02},000"
    sample = "\n\n".join(
        f"{i+1}\n{stamp(i*60)} --> {stamp(i*60+15)}\nPRIVATE SAYING {i}"
        for i in range(180)
    )
    (source_dir / "ABCDEFGHIJK.srt").write_text(sample, encoding="utf-8")
    monkeypatch.setattr(subject, "quota_budget_status", lambda _conn: {
        "exhausted": False, "spendable": 100
    })
    class FakeClient:
        def __init__(self, *, profile):
            assert profile == "live"
        def credentials(self):
            return object()
        def video_details_with_request_count(self, ids):
            assert ids == ["ABCDEFGHIJK"]
            return [{
                "id": "ABCDEFGHIJK",
                "snippet": {
                    "channelId": "PRIVATE",
                    "title": "PRIVATE LONG LIVE TITLE",
                    "description": "PRIVATE https://donate.rginfoua.pp.ua",
                    "tags": ["PRIVATE TAG"],
                },
            }], 1
    called = {"analyze": 0}
    def analyze(rows, **kwargs):
        called["analyze"] += 1
        assert kwargs["cache_dir"] == root / "private_semantic_cache" / "ABCDEFGHIJK"
        total = len(subject.split_timeline(
            rows, max_chars=5000, max_span_seconds=300
        ))
        kwargs["progress"](f"Аналіз фрагментів: 1/{total} · PRIVATE")
        kwargs["progress"](f"Аналіз фрагментів: 5/{total} · PRIVATE")
        return {
            "source_integrity_verified": True, "blocks_total": total,
            "blocks_analyzed": total, "blocks_with_evidence": total,
            "source_rows_with_text": len(rows), "blocks": [],
        }
    monkeypatch.setattr(subject, "analyze_all_timeline_blocks", analyze)
    monkeypatch.setattr(subject, "evidence_outline_text", lambda _e: "PRIVATE OUTLINE")
    monkeypatch.setattr(subject, "generate_seo_package_local", lambda **kw: {
        "title": "PRIVATE TITLE",
        "description": "PRIVATE https://donate.rginfoua.pp.ua",
        "title_variants": ["A", "B", "C"], "tags": ["PRIVATE"],
    })
    monkeypatch.setattr(subject, "review_seo_package", lambda **_k: [])
    checks = {"first": 0}
    def aggregate_gpu_check():
        checks["first"] += 1
        return checks["first"] == 1

    result = subject.run(
        db_path=db, private_root=root, client_factory=FakeClient,
        chat=lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("Ollama is mocked during unit tests")
        ),
        gpu_check=aggregate_gpu_check,
        foreign_gpu_check=lambda: False,
    )
    assert called["analyze"] == 1
    assert checks["first"] == 1  # Own Ollama activity cannot cancel QA
    assert result["status"] == "STRUCTURE_PASS"
    assert result["private_draft_saved"] is True
    assert result["ab_titles_count"] == 3
    assert result["source_caption_rows"] == 180
    assert result["youtube_data_api_calls"] == 1
    assert result["youtube_modified"] is False
    assert result["source_text_exported"] is False
    assert "PRIVATE SAYING" not in str(result)
    assert "PRIVATE https://donate.rginfoua.pp.ua" not in str(result)
    assert "ABCDEFGHIJK" not in str(result)
    draft = root / "private_drafts" / "ABCDEFGHIJK.json"
    assert draft.is_file()
    content = draft.read_text(encoding="utf-8")
    assert "PRIVATE https://donate.rginfoua.pp.ua" in content
    assert '"review_required": true' in content


def test_staged_long_live_qa_does_not_call_owner_api_when_gpu_busy(
    tmp_path, monkeypatch,
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_staged_long_live_semantic_qa as subject
    db = _db(tmp_path, duration="PT3H0M0S", source_description="")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    root = tmp_path / "private"
    source = root / "private_source"
    source.mkdir(parents=True)
    (source / "ABCDEFGHIJK.srt").write_text("PRIVATE SRT", encoding="utf-8")
    monkeypatch.setattr(subject, "load_srt_transcript", lambda _p: [
        {"text": "PRIVATE SEGMENT " + str(n), "start": n * 60, "duration": 20}
        for n in range(180)
    ])
    result = subject.run(
        db_path=db, private_root=root, gpu_check=lambda: False,
        client_factory=lambda **_kw: (_ for _ in ()).throw(
            AssertionError("No owner requests when GPU is busy")
        ),
    )
    assert result["status"] == "GPU_BUSY"
    assert result["youtube_data_api_calls"] == 0
    assert result["private_draft_saved"] is False


def test_foreign_cuda_check_ignores_ollama_but_blocks_other_heavy_process(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_staged_long_live_semantic_qa as subject
    monkeypatch.setattr(subject.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(
        stdout="C:/Users/test/AppData/Local/Programs/Ollama/ollama.exe, 8122\n"
    ))
    assert subject._foreign_gpu_compute_active() is False
    monkeypatch.setattr(subject.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(
        stdout="C:/Users/test/AppData/Local/Programs/Ollama/ollama.exe, 8122\n"
               "D:/Video/RenderEngine.exe, 3500\n"
    ))
    assert subject._foreign_gpu_compute_active() is True
