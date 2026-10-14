from pathlib import Path
from types import SimpleNamespace

import pytest

from rg_youtube_control.local_media_sources import find_exact_local_media
from rg_youtube_control.offline_transcription import generate_srt_offline


def test_discover_exact_id_media_only(tmp_path):
    (tmp_path / "AbCdEfGhI12.mp4").write_bytes(b"media")
    (tmp_path / "AbCdEfGhI13.mp4").write_bytes(b"other")
    assert find_exact_local_media("AbCdEfGhI12", [tmp_path]).name == "AbCdEfGhI12.mp4"
    assert find_exact_local_media("886_2", [tmp_path]) is None


def test_offline_caption_success_without_real_model(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    media = root / "AbCdEfGhI12.mp4"
    media.write_bytes(b"demo")
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"fake")
    calls = []
    class FakeModel:
        def transcribe(self, source, **kwargs):
            calls.append((source, kwargs))
            return iter([SimpleNamespace(start=1, end=3, text=" Тестовий транскрипт ")]), {}
    output = generate_srt_offline(
        video_id="AbCdEfGhI12", media=media, destination=tmp_path / "captions",
        model_dir=model, whisper_factory=lambda *a, **kw: FakeModel(),
    )
    assert output.name == "AbCdEfGhI12.srt"
    assert "00:00:01,000 --> 00:00:03,000" in output.read_text(encoding="utf-8")
    assert len(calls) == 1
    with pytest.raises(FileExistsError):
        generate_srt_offline(
            video_id="AbCdEfGhI12", media=media, destination=output.parent,
            model_dir=model, whisper_factory=lambda *a, **kw: FakeModel(),
        )


def test_missing_local_model_never_tries_network(tmp_path):
    media = tmp_path / "AbCdEfGhI12.mp4"
    media.write_bytes(b"data")
    with pytest.raises(FileNotFoundError):
        generate_srt_offline(
            video_id="AbCdEfGhI12", media=media, destination=tmp_path,
            model_dir=tmp_path / "missing",
            whisper_factory=lambda *a, **kw: pytest.fail("must not initialize model"),
        )
