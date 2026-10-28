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
        lambda db, profile, limit, preferred=(): (
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
