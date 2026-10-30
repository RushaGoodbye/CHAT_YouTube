"""Read-only QA may fetch public captions only once per selected video."""
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "rg_remote_control" / "seo_readonly_acceptance_10.py"


def _module():
    spec = importlib.util.spec_from_file_location("rg_seo_preflight_cache_test", SCRIPT)
    assert spec and spec.loader
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def test_public_preflight_is_reused_not_downloaded_twice(tmp_path, monkeypatch):
    qa = _module()
    captions = tmp_path / "captions"
    captions.mkdir()
    db = tmp_path / "test.db"
    with sqlite3.connect(db) as cx:
        cx.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        cx.execute("INSERT INTO settings VALUES('nas_transcripts_path',?)", (str(captions),))
        cx.execute(
            "CREATE TABLE videos(video_id TEXT,profile TEXT,title TEXT,duration TEXT,"
            " scheduled_publish_at TEXT,privacy_status TEXT,views INTEGER)"
        )
        cx.execute(
            "INSERT INTO videos VALUES('12345678901','main','Тема розмови','PT10M',NULL,'public',4)"
        )
    cues = [
        {"text": "Тема розмови", "start": n * 55.0, "duration": 30.0}
        for n in range(12)
    ]
    fetched = []
    def public_captions(video_id):
        fetched.append(video_id)
        if len(fetched) != 1:
            raise AssertionError("Public captions were fetched more than once")
        return cues
    monkeypatch.setattr(qa, "fetch_transcript", public_captions)
    ids = qa.select_existing_srt_videos(
        db, "main", 1, allow_public_captions=True, preflight_captions=True,
    )
    assert ids == ["12345678901"]
    assert len(fetched) == 1

    monkeypatch.setattr(qa, "analyze_all_timeline_blocks", lambda *a, **k: {
        "blocks_total": 1, "blocks_with_evidence": 1,
        "blocks": [{"verified": True, "topics": [{
            "topic": "Тема", "evidence": "Тема розмови дуже важлива"
        }]}],
    })
    monkeypatch.setattr(qa, "generate_seo_package_local", lambda **kwargs: {
        "title": "Тема розмови", "title_variants": [],
        "description": "Попередній опис.", "tags": [], "chapters": "",
    })
    monkeypatch.setattr(qa, "_description_quality_error", lambda *args, **kwargs: "")
    monkeypatch.setattr(qa, "safe_description_fix",
                        lambda *args: SimpleNamespace(
                            after="links.rginfoua.pp.ua donate.rginfoua.pp.ua"
                        ))
    result = qa.run_one(
        ids[0], database=db, qa_cache=tmp_path / "qa",
        allow_public_captions=True,
    )
    assert result["status"] == "NEEDS_REVIEW"
    assert result["caption_preflight_reused"] is True
    assert result["public_caption_reads"] == 0
    assert result["production_db_writes"] == 0
    assert result["youtube_writes"] == 0
    assert fetched == ["12345678901"]
    assert qa._PREFLIGHT_PUBLIC_CAPTIONS == {}


def test_offline_chapter_recovery_still_emits_review_package(monkeypatch):
    from rg_youtube_control import free_tools as ft
    monkeypatch.setattr(ft, "ollama_chat", lambda *a, **k:
                        (_ for _ in ()).throw(RuntimeError("model offline")))
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "Корупція", "evidence": "Коррупция чиновников обсуждалась"},
        {"topic": "Бензин", "evidence": "Бензин на заправке сильно подорожал"},
        {"topic": "Мобілізація", "evidence": "Мобилизация людей в разных регионах"},
    ]}]}
    result = ft.generate_seo_package_local(
        current_title="Бензин та мобілізація",
        transcript="Коррупция чиновников. Бензин на заправке. Мобилизация людей.",
        evidence_report=report, timeout=1, fast_mode=False,
    )
    assert result["needs_review"]
    assert result["youtube_data_api_quota"] == 0
