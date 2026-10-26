"""Full-file acceptance CLI never changes installed data or YouTube."""
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def qa_script():
    path = Path("rg_remote_control/seo_readonly_acceptance_10.py")
    spec = importlib.util.spec_from_file_location("rg_seo_qa_readonly", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_db(tmp_path, video_id="MEitKm687xo"):
    from rg_youtube_control.db import connect
    db = tmp_path / "rg_youtube_control.db"
    con = connect(db)
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir(exist_ok=True)
    con.execute(
        "INSERT INTO videos(video_id,profile,title,duration,"
        "privacy_status,last_synced_at) VALUES(?,?,?,?,?,?)",
        (video_id, "main", "Шойгу: что с коррупцией?", 50,
         "public", "2026-10-24"),
    )
    con.execute(
        "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
        ("nas_transcripts_path", str(transcripts)),
    )
    con.commit()
    con.close()
    return db, transcripts


def test_acceptance_rejects_missing_srt_without_network(tmp_path, qa_script, monkeypatch):
    db, folder = _source_db(tmp_path)
    monkeypatch.setattr(
        qa_script, "ollama_chat",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("No model calls with absent SRT")
        ),
    )
    outcome = qa_script.run_one(
        "MEitKm687xo", database=db, qa_cache=tmp_path / "cache"
    )
    assert outcome["status"] == "BLOCKED"
    assert "SRT missing" in outcome["error"]
    assert outcome["youtube_api_calls"] == 0
    assert outcome["production_db_writes"] == 0


def test_acceptance_with_mocked_full_srt_is_readonly(tmp_path, qa_script, monkeypatch):
    import hashlib
    db, folder = _source_db(tmp_path)
    (folder / "MEitKm687xo.srt").write_text(
        "1\n00:00:00,000 --> 00:00:05,000\nText\n", encoding="utf-8"
    )
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    monkeypatch.setattr(
        qa_script, "load_srt_transcript",
        lambda path: [
            {"start": i * 5.0, "duration": 5.0,
             "text": "Вопросы про Шойгу и коррупцию в России"}
            for i in range(10)
        ],
    )
    monkeypatch.setattr(
        qa_script, "analyze_all_timeline_blocks",
        lambda *a, **k: {
            "blocks_total": 2, "blocks_with_evidence": 2,
            "blocks": [
                {"verified": True, "topics": [
                    {"topic": "Кадрові зміни та корупція",
                     "evidence": "Шойгу и коррупцию"}
                ]}
            ],
        },
    )
    monkeypatch.setattr(qa_script, "evidence_outline_text", lambda report: (
        "Шойгу и коррупцию в России обсуждают в разговоре"
    ))
    monkeypatch.setattr(
        qa_script, "generate_seo_package_local",
        lambda **k: {
            "title": "Шойгу: что с коррупцией?",
            "title_variants": [
                "Шойгу и коррупция: вопросы", "Кадровые решения в РФ",
                "Причины увольнения Шойгу",
            ],
            "description": "У цьому випуску обговорюють Шойгу та корупцію. " * 15,
            "tags": ["тег" + str(i) for i in range(8)],
        },
    )
    monkeypatch.setattr(qa_script, "ab_title_issues", lambda *a, **k: [])
    monkeypatch.setattr(qa_script, "_description_quality_error", lambda *a, **k: "")
    monkeypatch.setattr(qa_script, "_incidental_ab_quote", lambda *a: False)
    monkeypatch.setattr(
        qa_script, "safe_description_fix",
        lambda *a: SimpleNamespace(after=(
            "https://links.rginfoua.pp.ua "
            "https://donate.rginfoua.pp.ua"
        )),
    )
    result = qa_script.run_one(
        "MEitKm687xo", database=db, qa_cache=tmp_path / "qa-cache"
    )
    assert result["status"] == "DRAFT_READY_FOR_HUMAN_REVIEW", result
    assert all(result["checks"].values())
    assert result["review_required"]
    assert result["youtube_writes"] == 0
    assert before == hashlib.sha256(db.read_bytes()).hexdigest()
    assert not list(tmp_path.glob("*.json"))


def test_qa_cli_rejects_unknown_video_id(tmp_path, qa_script):
    db, _ = _source_db(tmp_path)
    response = qa_script.run_one(
        "../secrets", database=db, qa_cache=tmp_path / "cache"
    )
    assert response["status"] == "BLOCKED"
    assert response["error_type"] == "ValueError"


def test_real_qa_uses_ten_distinct_main_videos(qa_script):
    assert len(qa_script.MAIN_IDS) == 10
    assert len(set(qa_script.MAIN_IDS)) == 10
    assert all(qa_script.VALID_ID.fullmatch(i) for i in qa_script.MAIN_IDS)


def test_acceptance_summary_never_leaks_internal_nas_path_or_model_text(
    tmp_path, qa_script, monkeypatch,
):
    db, folder = _source_db(tmp_path)
    (folder / "MEitKm687xo.srt").write_text(
        "1\n00:00:00,000 --> 00:00:05,000\nText\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        qa_script, "load_srt_transcript", lambda path: [
            {"start": i * 5.0, "duration": 5.0, "text": "sample"}
            for i in range(10)
        ]
    )
    private_text = "PRIVATE_SUBTITLE: private quoted conversation"
    private_path = "C:\\Users\\PrivateUser\\Secrets\\transcript.srt"
    def fake_analyze(*a, **kw):
        raise RuntimeError(private_text + " " + private_path)
    monkeypatch.setattr(
        qa_script, "analyze_all_timeline_blocks", fake_analyze
    )
    result = qa_script.run_one(
        "MEitKm687xo", database=db, qa_cache=tmp_path / "cache"
    )
    assert result["status"] == "BLOCKED"
    assert private_text not in str(result)
    assert private_path not in str(result)
    assert "Local content-validation" in result["error"]
