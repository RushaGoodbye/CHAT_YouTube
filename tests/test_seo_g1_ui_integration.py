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
