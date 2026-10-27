"""Regression tests for the real 0.7.33 Whisper progress/CPU fallback contract."""
from pathlib import Path
from types import SimpleNamespace

import rg_youtube_control.offline_transcription as transcription


VIDEO = "AbCdEfGhI12"


def _inputs(tmp_path):
    media = tmp_path / f"{VIDEO}.wav"
    media.write_bytes(b"synthetic-media")
    model_dir = tmp_path / "whisper-model"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"model")
    return media, model_dir


def test_known_duration_reports_actual_position_percent_and_time(tmp_path, monkeypatch):
    media, model_dir = _inputs(tmp_path)
    monkeypatch.setattr(transcription, "_media_duration_seconds", lambda _: 120.0)
    updates = []

    class FakeWhisper:
        model = SimpleNamespace(device="cuda")

        def transcribe(self, source, **kwargs):
            assert str(media) == source
            assert kwargs["vad_filter"] is True
            return iter([
                SimpleNamespace(start=0.0, end=30.0, text="Перша репліка"),
                SimpleNamespace(start=30.0, end=60.0, text="Друга репліка"),
            ]), {}

    output = transcription.generate_srt_offline(
        video_id=VIDEO, media=media, model_dir=model_dir,
        destination=tmp_path / "transcripts",
        whisper_factory=lambda *args, **kwargs: FakeWhisper(),
        on_progress=updates.append,
    )

    assert output.exists()
    assert "Друга репліка" in output.read_text(encoding="utf-8")
    assert any(item["mode"] == "GPU (CUDA)" for item in updates)
    assert any(item["processed_seconds"] == 60.0 for item in updates)
    assert any(item["percent"] == 50 for item in updates)
    assert any("00:01:00 / 00:02:00" in item["stage"] for item in updates)
    assert all(item["percent"] is None or 0 <= item["percent"] < 100 for item in updates)


def test_unknown_media_duration_does_not_invent_percent_or_eta(tmp_path, monkeypatch):
    media, model_dir = _inputs(tmp_path)
    monkeypatch.setattr(transcription, "_media_duration_seconds", lambda _: None)
    updates = []

    class FakeWhisper:
        def transcribe(self, source, **kwargs):
            return iter([
                SimpleNamespace(start=0.0, end=14.0, text="Чистий звук"),
            ]), {}

    transcription.generate_srt_offline(
        video_id=VIDEO, media=media, model_dir=model_dir,
        destination=tmp_path / "transcripts",
        whisper_factory=lambda *args, **kwargs: FakeWhisper(),
        on_progress=updates.append,
    )
    assert updates
    assert all(item["percent"] is None for item in updates)
    assert all("ETA" not in item["eta"] for item in updates)
    assert "невідома тривалість" in updates[-1]["stage"]


def test_cuda_fallback_is_visible_and_cleans_partial_srt(tmp_path, monkeypatch):
    media, model_dir = _inputs(tmp_path)
    monkeypatch.setattr(transcription, "_media_duration_seconds", lambda _: 90.0)
    updates = []
    devices = []

    class FakeWhisper:
        def __init__(self, device):
            self.model = SimpleNamespace(device="cpu" if device == "cpu" else "cuda")
            self.device = device

        def transcribe(self, source, **kwargs):
            def segments():
                yield SimpleNamespace(start=0.0, end=20.0, text="Одна репліка")
                if self.device == "auto":
                    raise RuntimeError("CUDA error: cublas DLL missing")
                yield SimpleNamespace(start=20.0, end=45.0, text="Друга репліка")
            return segments(), {}

    def factory(path, device, compute_type):
        devices.append(device)
        return FakeWhisper(device)

    output = transcription.generate_srt_offline(
        video_id=VIDEO, media=media, model_dir=model_dir,
        destination=tmp_path / "transcripts",
        whisper_factory=factory,
        on_progress=updates.append,
    )
    assert devices == ["auto", "cpu"]
    assert output.read_text(encoding="utf-8").count("Одна репліка") == 1
    assert any(item["fallback"] and "CPU" in item["mode"] for item in updates)
    assert any("GPU недоступна" in item["eta"] for item in updates)
    assert updates[-1]["processed_seconds"] == 45.0


def test_optimization_worker_supports_structured_progress():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    assert "progress = Signal(object)" in source
    assert "on_progress=whisper_progress" in source
    assert 'message.get("percent")' in source
    assert 'message.get("eta")' in source
