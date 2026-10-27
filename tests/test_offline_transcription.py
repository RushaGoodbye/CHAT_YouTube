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


def test_cuda_runtime_failure_falls_back_to_cpu_once(tmp_path):
    media = tmp_path / "AbCdEfGhI12.wav"
    media.write_bytes(b"sample")
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"model")
    seen = []

    def factory(path, device, compute_type):
        seen.append((device, compute_type))
        if device == "auto":
            raise RuntimeError("Could not load cublas64_12.dll")
        class CPU:
            def transcribe(self, source, **kwargs):
                assert kwargs["vad_filter"] is True
                return iter([SimpleNamespace(start=0.0, end=1.0, text="CPU fallback")]), {}
        return CPU()

    output = generate_srt_offline(
        video_id="AbCdEfGhI12", media=media, destination=tmp_path / "subs",
        model_dir=model, whisper_factory=factory,
    )
    assert seen == [("auto", "auto"), ("cpu", "int8")]
    assert "CPU fallback" in output.read_text(encoding="utf-8")
    assert "\n" in output.read_text(encoding="utf-8")
    assert not list(output.parent.glob("*.tmp"))


def test_lazy_gpu_failure_cleans_partial_srt_before_retry(tmp_path):
    media = tmp_path / "AbCdEfGhI12.wav"
    media.write_bytes(b"sample")
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"model")
    seen = []

    def factory(path, device, compute_type):
        seen.append(device)
        class FakeWhisper:
            def transcribe(self, source, **kwargs):
                def iterator():
                    yield SimpleNamespace(start=0.0, end=1.0, text="partial")
                    if device == "auto":
                        raise RuntimeError("CUDA error: cudnn_ops_infer64_8.dll missing")
                    yield SimpleNamespace(start=1.0, end=2.0, text="completed")
                return iterator(), {}
        return FakeWhisper()

    output = generate_srt_offline(
        video_id="AbCdEfGhI12", media=media, destination=tmp_path / "subs",
        model_dir=model, whisper_factory=factory,
    )
    content = output.read_text(encoding="utf-8")
    assert seen == ["auto", "cpu"]
    assert content.count("partial") == 1
    assert "completed" in content
    assert not list(output.parent.glob("*.tmp"))


def test_non_gpu_failure_does_not_retry_cpu(tmp_path):
    media = tmp_path / "AbCdEfGhI12.wav"
    media.write_bytes(b"sample")
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"model")
    calls = []

    def factory(path, device, compute_type):
        calls.append(device)
        raise RuntimeError("Damaged media file")

    with pytest.raises(RuntimeError, match="Damaged media"):
        generate_srt_offline(
            video_id="AbCdEfGhI12", media=media, destination=tmp_path / "subs",
            model_dir=model, whisper_factory=factory,
        )
    assert calls == ["auto"]
    assert not list((tmp_path / "subs").glob("*.srt"))



def test_stale_srt_temp_file_does_not_block_retry(tmp_path):
    media = tmp_path / "AbCdEfGhI12.wav"
    media.write_bytes(b"media")
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"model")
    destination = tmp_path / "captions"
    destination.mkdir()
    stale = destination / "AbCdEfGhI12.srt.tmp"
    stale.write_text("left behind by crashed process", encoding="utf-8")

    class FakeWhisper:
        def transcribe(self, source, **kwargs):
            return iter([
                SimpleNamespace(start=0.0, end=1.0, text="Відновлений текст")
            ]), {}

    output = generate_srt_offline(
        video_id="AbCdEfGhI12", media=media, destination=destination,
        model_dir=model, whisper_factory=lambda *a, **kw: FakeWhisper(),
    )
    assert "Відновлений текст" in output.read_text(encoding="utf-8")
    assert stale.read_text(encoding="utf-8") == "left behind by crashed process"
    assert not list(destination.glob(".AbCdEfGhI12.*.srt.tmp"))
