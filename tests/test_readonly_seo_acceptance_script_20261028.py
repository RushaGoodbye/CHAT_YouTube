"""Guard the real-video acceptance entrypoint used on AlexPC."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "rg_remote_control" / "seo_readonly_acceptance_10.py"


def test_real_video_acceptance_script_present_and_compiles():
    source = SCRIPT.read_text(encoding="utf-8")
    compile(source, str(SCRIPT), "exec")
    assert "mode=ro" in source
    assert "PRAGMA query_only=ON" in source
    assert "production_db_writes" in source
    assert "youtube_writes" in source


def test_real_video_acceptance_duration_formats():
    spec = importlib.util.spec_from_file_location("rg_seo_readonly_acceptance_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._duration_seconds("PT9M53S") == 593
    assert module._duration_seconds("00:09:53") == 593
    assert module._duration_seconds("593") == 593
    assert module._duration_seconds("PT1H1M1S") == 3661


def test_safe_error_codes_never_export_private_model_text():
    spec = importlib.util.spec_from_file_location("rg_seo_readonly_acceptance_codes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._safe_error_code(ValueError(
        "Локальна SEO-генерація не пройшла валідацію після повторів: need at least 8 grounded tags"
    )) == "TAGS_INSUFFICIENT"
    assert module._safe_error_code(ValueError(
        "Untrusted transcript private quoted sentence"
    )) == "LOCAL_SEO_OTHER_ERROR"


def test_batch_accepts_video_ids_that_start_with_dash(tmp_path, monkeypatch):
    import json
    spec = importlib.util.spec_from_file_location("rg_seo_readonly_batch_ids", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = []
    def fake_run_one(video_id, **kwargs):
        seen.append(video_id)
        return {"video_id": video_id, "status": "DRAFT_READY_FOR_HUMAN_REVIEW"}
    monkeypatch.setattr(module, "run_one", fake_run_one)
    out = tmp_path / "summary.json"
    exit_code = module.main([
        "--video-ids", "MEitKm687xo,-Bu_aDIvEs4,fdHXrCyw3Lw",
        "--output", str(out),
    ])
    assert exit_code == 0
    assert seen == ["MEitKm687xo", "-Bu_aDIvEs4", "fdHXrCyw3Lw"]
    assert json.loads(out.read_text(encoding="utf-8"))["video_count"] == 3


def test_auto_source_selection_uses_real_srt_files_and_skips_shorts(tmp_path):
    import sqlite3
    spec = importlib.util.spec_from_file_location("rg_real_seo_selector", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captions = tmp_path / "captions"
    captions.mkdir()
    db_file = tmp_path / "test.db"
    with sqlite3.connect(db_file) as db:
        db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        db.execute(
            "INSERT INTO settings VALUES('nas_transcripts_path', ?)",
            (str(captions),),
        )
        db.execute(
            "CREATE TABLE videos(video_id TEXT,profile TEXT,duration TEXT,"
            " scheduled_publish_at TEXT,privacy_status TEXT,views INTEGER)"
        )
        rows = [
            ("12345678901", "main", "PT9M", None, "public", 100),
            ("12345678902", "main", "00:09:00", None, "public", 90),
            ("12345678903", "main", "00:59", None, "public", 80),
            ("12345678904", "main", "PT5M", None, "private", 70),
            ("12345678905", "live", "PT3H", None, "public", 200),
            ("12345678906", "live", "PT4H", None, "public", 190),
        ]
        db.executemany("INSERT INTO videos VALUES(?,?,?,?,?,?)", rows)
    for vid in ("12345678901", "12345678902", "12345678903",
                "12345678904", "12345678905"):
        (captions / (vid + ".srt")).write_text("test", encoding="utf-8")
    assert module.select_existing_srt_videos(
        db_file, "main", 10,
    ) == ["12345678901", "12345678902"]
    assert module.select_existing_srt_videos(
        db_file, "live", 2,
    ) == ["12345678905"]


def test_auto_selection_reports_shortfall_instead_of_claiming_full_pass(
    tmp_path, monkeypatch,
):
    import json
    spec = importlib.util.spec_from_file_location("rg_real_seo_auto_cli", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module, "select_existing_srt_videos",
        lambda db, profile, limit, preferred=(), allow_public_captions=False, preflight_captions=False, private_caption_cache=None: (
            ["12345678901"] if profile == "main" else []
        ),
    )
    monkeypatch.setattr(
        module, "run_one",
        lambda video_id, **kwargs: {
            "video_id": video_id,
            "status": "DRAFT_READY_FOR_HUMAN_REVIEW",
        },
    )
    path = tmp_path / "result.json"
    result = module.main([
        "--auto-main", "2", "--auto-live", "2", "--output", str(path),
    ])
    report = json.loads(path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["video_count"] == 1
    assert report["requested_video_count"] == 4
    assert report["source_shortfall_count"] == 3
    assert report["status"] == "BLOCKED"


def test_auto_source_selection_can_opt_in_to_public_live_captions(tmp_path):
    import sqlite3
    spec = importlib.util.spec_from_file_location("rg_seo_public_live_selector", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "captions"
    root.mkdir()
    db_file = tmp_path / "source.db"
    with sqlite3.connect(db_file) as db:
        db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO settings VALUES('nas_transcripts_path', ?)", (str(root),))
        db.execute(
            "CREATE TABLE videos(video_id TEXT,profile TEXT,duration TEXT,"
            " scheduled_publish_at TEXT,privacy_status TEXT,views INTEGER)"
        )
        db.executemany("INSERT INTO videos VALUES(?,?,?,?,?,?)", [
            ("12345678901", "live", "PT2H", None, "public", 11),
            ("12345678902", "live", "PT2H", None, "public", 10),
            ("12345678903", "live", "PT59S", None, "public", 9),
            ("12345678904", "live", "PT2H", None, "private", 8),
        ])
    (root / "12345678901.srt").write_text("data", encoding="utf-8")
    assert module.select_existing_srt_videos(db_file, "live", 2) == [
        "12345678901",
    ]
    assert module.select_existing_srt_videos(
        db_file, "live", 2, allow_public_captions=True,
    ) == ["12345678901", "12345678902"]


def test_public_captions_read_only_fallback_never_writes_production(
    tmp_path, monkeypatch,
):
    import sqlite3
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location("rg_seo_public_fallback_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "captions"
    root.mkdir()
    db_file = tmp_path / "source.db"
    with sqlite3.connect(db_file) as db:
        db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO settings VALUES('nas_transcripts_path', ?)", (str(root),))
        db.execute("CREATE TABLE videos(video_id TEXT,profile TEXT,title TEXT,duration TEXT)")
        db.execute(
            "INSERT INTO videos VALUES('12345678901','live','Тема розмови','PT10M')"
        )
    before = db_file.read_bytes()
    cues = [
        {"text": "Текст розмови", "start": n * 45.0, "duration": 20.0}
        for n in range(12)
    ]
    monkeypatch.setattr(module, "fetch_transcript", lambda video_id: cues)
    monkeypatch.setattr(module, "analyze_all_timeline_blocks",
        lambda *args, **kwargs: {
            "blocks_total": 1, "blocks_with_evidence": 1,
            "blocks": [{"verified": True, "topics": [
                {"topic": "розмова", "evidence": "Розмова про питання життя"},
            ]}],
        })
    monkeypatch.setattr(module, "generate_seo_package_local",
        lambda **kwargs: {
            "title": "Тема розмови", "title_variants": [],
            "description": "Попередній опис.", "tags": [],
            "chapters": "", "evidence_editorial_review": ["review"],
        })
    monkeypatch.setattr(module, "_description_quality_error", lambda *a, **k: "")
    monkeypatch.setattr(
        module, "safe_description_fix",
        lambda *a: SimpleNamespace(after="links.rginfoua.pp.ua donate.rginfoua.pp.ua"),
    )
    result = module.run_one(
        "12345678901", database=db_file, qa_cache=tmp_path / "cache",
        allow_public_captions=True,
    )
    assert result["status"] == "NEEDS_REVIEW"
    assert result["transcript_source"] == "public_captions"
    assert result["srt_present"] is False
    assert result["public_caption_reads"] == 1
    assert result["production_db_writes"] == 0
    assert result["youtube_writes"] == 0
    assert db_file.read_bytes() == before


def test_preflight_skips_unplayable_and_incomplete_video_sources(
    tmp_path, monkeypatch,
):
    import sqlite3
    spec = importlib.util.spec_from_file_location("rg_seo_preflight", SCRIPT)
    assert spec and spec.loader
    qa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qa)
    root = tmp_path / "captions"
    root.mkdir()
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        conn.execute(
            "INSERT INTO settings VALUES('nas_transcripts_path',?)", (str(root),),
        )
        conn.execute(
            "CREATE TABLE videos(video_id TEXT,profile TEXT,duration TEXT,"
            "scheduled_publish_at TEXT,privacy_status TEXT,views INTEGER)"
        )
        conn.executemany("INSERT INTO videos VALUES(?,?,?,?,?,?)", [
            ("11111111111", "main", "PT10M", None, "public", 100),
            ("22222222222", "main", "PT10M", None, "public", 90),
            ("33333333333", "main", "PT10M", None, "public", 80),
        ])
    def fake_fetch(video_id):
        if video_id == "11111111111":
            raise RuntimeError("unavailable")
        return [
            {"text": "говорили про війну", "start": n * 55, "duration": 30}
            for n in range(12)
        ]
    monkeypatch.setattr(qa, "fetch_transcript", fake_fetch)
    assert qa.select_existing_srt_videos(
        db, "main", 2, allow_public_captions=True,
        preflight_captions=True,
    ) == ["22222222222", "33333333333"]


def test_preflight_rejects_broken_srt_and_uses_same_id_public_fallback(
    tmp_path, monkeypatch,
):
    import sqlite3
    spec = importlib.util.spec_from_file_location("rg_seo_preflight_srt", SCRIPT)
    assert spec and spec.loader
    qa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qa)
    root = tmp_path / "captions"
    root.mkdir()
    (root / "11111111111.srt").write_text("broken", encoding="utf-8")
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        conn.execute("INSERT INTO settings VALUES('nas_transcripts_path',?)", (str(root),))
        conn.execute(
            "CREATE TABLE videos(video_id TEXT,profile TEXT,duration TEXT,"
            "scheduled_publish_at TEXT,privacy_status TEXT,views INTEGER)"
        )
        conn.execute(
            "INSERT INTO videos VALUES('11111111111','main','PT10M',NULL,'public',100)"
        )
    monkeypatch.setattr(qa, "load_srt_transcript", lambda path: [])
    seen = []
    def fake_fetch(vid):
        seen.append(vid)
        return [{"text": "питання ціни", "start": n * 55, "duration": 30}
                for n in range(12)]
    monkeypatch.setattr(qa, "fetch_transcript", fake_fetch)
    result = qa.select_existing_srt_videos(
        db, "main", 1, allow_public_captions=True,
        preflight_captions=True,
    )
    assert result == ["11111111111"]
    assert seen == ["11111111111"]
