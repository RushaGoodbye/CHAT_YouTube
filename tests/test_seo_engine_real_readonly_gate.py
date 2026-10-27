"""The real-AlexPC verification entrypoint must exercise the new engine."""
from pathlib import Path
from types import SimpleNamespace

from rg_remote_control import seo_engine_real_readonly_gate as gate
from rg_youtube_control.seo_engine_v1 import SeoDraft


def inputs(tmp_path, monkeypatch):
    (tmp_path / "UC-zGLdheCE.srt").write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(gate, "get_video_inputs", lambda db, vid: {
        "title": "Могут ли ОСУЖДЕННЫЕ преподавать в ШКОЛАХ РФ?",
        "transcript_root": str(tmp_path),
        "duration": 0,
    })
    monkeypatch.setattr(gate, "load_srt_transcript", lambda _: [
        {"text": "В школах России обсуждают судимость учителей и безопасность детей.",
         "start": i * 4, "duration": 4} for i in range(12)
    ])
    monkeypatch.setattr(gate, "check_title_against_transcript",
                        lambda title, text: SimpleNamespace(missing=[]))


def draft():
    return SeoDraft(
        video_id="UC-zGLdheCE",
        title="СУДИМЫЕ ПРЕПОДАВАТЕЛИ В ШКОЛАХ РФ? РОССИЯНЕ ОБСУЖДАЮТ",
        ab_titles=("Осужденные учителя: мнение родителей",
                   "Школы и судимость: разговор с россиянами",
                   "Преподавание после тяжкого преступления?"),
        description=("У цьому випуску росіяни обговорюють, чи можуть люди із судимістю "
                     "викладати в школах, що думають батьки та як захистити дітей. " * 4),
        tags=("раша гудбай", "чат рулетка", "школы россии", "осужденные",
              "учителя", "судимость", "педагоги", "россияне"),
        chapters="",
    )


def test_actual_gate_uses_new_engine_and_production_validator(monkeypatch, tmp_path):
    inputs(tmp_path, monkeypatch)
    called = []
    def model(**kwargs):
        called.append(kwargs)
        return draft()
    monkeypatch.setattr(gate, "generate_with_ollama", model)
    result = gate.run_one("UC-zGLdheCE", database=Path("unused"), model="qwen3:8b")
    assert result["status"] == "DRAFT_REVIEW_REQUIRED", result
    assert called and called[0]["model"] == "qwen3:8b"
    assert result["production_db_writes"] == 0 and result["youtube_writes"] == 0
    assert result["tags_count"] == 8 and result["ui_error_count"] == 0


def test_actual_gate_rejects_bad_model_output_before_persistence(monkeypatch, tmp_path):
    inputs(tmp_path, monkeypatch)
    def model(**kwargs):
        raise ValueError("Tags invalid")
    monkeypatch.setattr(gate, "generate_with_ollama", model)
    result = gate.run_one("UC-zGLdheCE", database=Path("unused"), model="qwen3:8b")
    assert result["status"] == "BLOCKED"
    assert result["error_code"] == "OLLAMA_RESPONSE_FAILED_CONTRACT"
    assert result["production_draft_writes"] == 0


def test_no_source_never_starts_model(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "get_video_inputs", lambda db, vid: {
        "title": "Школы", "transcript_root": str(tmp_path), "duration": 0,
    })
    monkeypatch.setattr(gate, "fetch_transcript", lambda vid: [])
    def model(**kwargs):
        raise AssertionError("Model must not run")
    monkeypatch.setattr(gate, "generate_with_ollama", model)
    result = gate.run_one("UC-zGLdheCE", database=Path("unused"), model="qwen3:8b")
    assert result["status"] == "BLOCKED"
    assert result["error_code"] == "INSUFFICIENT_CAPTION_ROWS"
