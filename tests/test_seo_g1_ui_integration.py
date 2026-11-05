"""G1 UI-path integration: no YouTube uploads, network or real user DB."""
from types import SimpleNamespace
from pathlib import Path
import pytest

from rg_youtube_control import ui
from rg_youtube_control.db import connect

VIDEO = "AbCdEfGh123"


def captions(subject):
    return [
        {"text": f"The interview discusses {subject} with several detailed arguments number {i}",
         "start": i * 4.0, "duration": 3.5}
        for i in range(160)
    ]


@pytest.fixture
def ui_runner(tmp_path, monkeypatch):
    conn = connect(tmp_path / "rg_youtube_control.db")
    conn.close()
    worker = SimpleNamespace(data_dir=tmp_path, current_profile="main")
    monkeypatch.setattr(ui, "cached_public_metadata", lambda *args: {})
    monkeypatch.setattr(ui, "fetch_public_metadata",
        lambda video_id: {"video_id": video_id, "title": "Public transport discussion",
                          "description": "A discussion of transport decisions.",
                          "tags": [], "duration": 642, "_caption_tracks": {"automatic": {"ru": []}}})
    monkeypatch.setattr(ui, "fetch_transcript", lambda *args: captions("bus fares and rail tickets"))
    monkeypatch.setattr(ui, "fetch_transcript_from_public_metadata",
                        lambda *args, **kwargs: captions("bus fares and rail tickets"))
    calls = []
    def fake_generate(**kwargs):
        calls.append(kwargs)
        return {"title": "Draft", "title_variants": ["A", "B", "C"],
                "description": "Draft only", "tags": []}
    monkeypatch.setattr(ui, "generate_seo_package_local", fake_generate)
    # This file tests caption acquisition, not the LLM. Supply strictly
    # source-grounded G2 analysis of EVERY real input block. The production
    # G2 source-record verifier remains active and checks literal quotations.
    from rg_youtube_control.dialogue_seo import split_timeline
    def deterministic_source_analysis(rows, **_kwargs):
        blocks = split_timeline(rows)
        for block in blocks:
            quote = next(
                (str(row["text"]).strip()[:120]
                 for row in rows
                 if block["start"] <= float(row["start"]) <= block["end"]
                 and len(str(row["text"]).strip()) >= 15),
                "",
            )
            block["topics"] = [{
                "topic": "Тема розмови про транспорт",
                "summary_uk": "У розмові учасники обговорюють різні питання про транспорт.",
                "evidence": quote,
            }] if quote else []
            block["verified"] = bool(quote)
            block["excerpt"] = ""
        return {
            "schema": "RG_DIALOGUE_EVIDENCE_V1",
            "blocks_total": len(blocks),
            "blocks_analyzed": len(blocks),
            "blocks_with_evidence": sum(bool(b["verified"]) for b in blocks),
            "unverified_blocks": [b["index"] for b in blocks if not b["verified"]],
            "cache_hits": 0,
            "rows_covered": sum(b["pieces"] for b in blocks),
            "blocks": blocks,
            "needs_review": any(not b["verified"] for b in blocks),
        }
    monkeypatch.setattr(ui, "analyze_all_timeline_blocks", deterministic_source_analysis)
    return worker, calls


def test_ui_accepts_corrobated_captions_as_draft(ui_runner):
    worker, calls = ui_runner
    result = ui.MainWindow._generate_local_seo_result(worker, VIDEO, fast_mode=True)
    assert len(calls) == 1
    assert result["context"]["caption_corroboration"] == "CAPTION_TRANSPORTS_CORROBORATE"
    assert (worker.data_dir / "verified_seo_captions" / (VIDEO + ".source.json")).exists()


def test_ui_blocks_different_content_before_generator(ui_runner, monkeypatch):
    worker, calls = ui_runner
    monkeypatch.setattr(ui, "fetch_transcript_from_public_metadata",
                        lambda *args, **kwargs: captions("asteroid discovery and spacecraft orbit"))
    with pytest.raises(RuntimeError, match="суперечать"):
        ui.MainWindow._generate_local_seo_result(worker, VIDEO, fast_mode=True)
    assert calls == []


def test_ui_missing_second_source_does_not_claim_corroboration(ui_runner, monkeypatch):
    worker, calls = ui_runner
    monkeypatch.setattr(ui, "fetch_transcript_from_public_metadata",
                        lambda *args, **kwargs: [])
    result = ui.MainWindow._generate_local_seo_result(worker, VIDEO, fast_mode=True)
    assert result["context"]["caption_corroboration"] == "INDEPENDENT_CAPTIONS_UNAVAILABLE"


def test_ui_malformed_direct_captions_block_generation(ui_runner, monkeypatch):
    worker, calls = ui_runner
    monkeypatch.setattr(ui, "fetch_transcript", lambda *args: captions("bus fares")[:2])
    with pytest.raises(RuntimeError, match="G1"):
        ui.MainWindow._generate_local_seo_result(worker, VIDEO, fast_mode=True)
    assert calls == []


def test_ui_ignores_unverified_nas_file_then_refetches(ui_runner, monkeypatch, tmp_path):
    worker, calls = ui_runner
    from rg_youtube_control.db import set_setting
    connection = connect(worker.data_dir / "rg_youtube_control.db")
    set_setting(connection, "nas_transcripts_path", str(tmp_path / "nas"))
    connection.close()
    nas = tmp_path / "nas"
    nas.mkdir()
    (nas / (VIDEO + ".srt")).write_text(
        "1\\n00:00:00,000 --> 00:00:05,000\\nCompletely wrong captions",
        encoding="utf-8",
    )
    result = ui.MainWindow._generate_local_seo_result(worker, VIDEO, fast_mode=True)
    assert len(calls) == 1
    assert result["context"]["transcript_source"] == "youtube-transcript-api"
    assert result["context"]["caption_corroboration"] == "CAPTION_TRANSPORTS_CORROBORATE"


def test_ui_blocks_wrong_alternative_timestamps(ui_runner, monkeypatch):
    worker, calls = ui_runner
    shifted = [dict(row, start=row["start"] + 320.0)
               for row in captions("bus fares and rail tickets")]
    monkeypatch.setattr(ui, "fetch_transcript_from_public_metadata",
                        lambda *args, **kwargs: shifted)
    with pytest.raises(RuntimeError, match="суперечать"):
        ui.MainWindow._generate_local_seo_result(worker, VIDEO, fast_mode=True)
    assert not calls