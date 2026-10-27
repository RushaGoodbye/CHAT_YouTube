"""Self-contained runtime smoke test for the INSTALLED Windows executable.

No YouTube calls, no model download and no access to the user's source files.
A synthetic one-segment recognizer exercises the installed binary end-to-end.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from . import __version__


def run_packaged_selftest(report_file: Path) -> int:
    report = {"version": __version__, "status": "FAIL", "checks": []}
    try:
        # Import compiled transcription dependencies from the installed EXE.
        import ctranslate2
        import faster_whisper
        report["checks"].append("packaged-faster-whisper-ctranslate2-import")

        # Regression for RG 0.7.30 installed EXE: imports passed while the
        # Silero VAD ONNX DATA asset was absent, breaking real vad_filter=True.
        from faster_whisper.vad import get_speech_timestamps, get_vad_model
        from faster_whisper.utils import get_assets_path
        import numpy as np
        vad_path = Path(get_assets_path()) / "silero_vad_v6.onnx"
        if not vad_path.is_file() or vad_path.stat().st_size < 100_000:
            raise FileNotFoundError(f"Missing packaged Silero VAD ONNX: {vad_path}")
        vad = get_vad_model()  # Instantiates real ONNX Runtime session.
        if vad is None:
            raise RuntimeError("Silero VAD ONNX model could not be loaded")
        # PyAV/FFmpeg decoding runs before Whisper and can fail if shared
        # libraries are omitted from the installed Windows application.
        import wave
        from faster_whisper.audio import decode_audio
        with tempfile.TemporaryDirectory(prefix="rg-wav-decode-") as decode_dir:
            sample = Path(decode_dir) / "silence.wav"
            with wave.open(str(sample), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(16_000)
                writer.writeframes(np.zeros(16_000, dtype=np.int16).tobytes())
            decoded = decode_audio(str(sample), sampling_rate=16_000)
            if len(decoded) != 16_000 or not np.isfinite(decoded).all():
                raise AssertionError("Packaged audio decoder produced invalid waveform")
        report["checks"].append("packaged-pyav-audio-decoding")

        timestamps = get_speech_timestamps(
            decoded,
        )  # Real VAD inference on actual decoded audio.
        if timestamps:
            raise AssertionError("Silence incorrectly classified as speech")
        report["checks"].append("silero-vad-onnx-real-inference")

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(["rg-packaged-selftest"])
        if app is None:
            raise RuntimeError("Qt application could not be initialized")
        report["checks"].append("qt-runtime")

        from .local_media_sources import find_exact_local_media
        from .verified_media_registry import save_verified_media, get_verified_media
        from .local_transcript_sources import find_local_transcript
        from .offline_transcription import generate_srt_offline

        video_id = "MEitKm687xo"
        with tempfile.TemporaryDirectory(prefix="rg-seo-bundle-") as root:
            folder = Path(root)
            media = folder / (video_id + ".mp4")
            media.write_bytes(b"synthetic-media-for-runtime-smoke")
            assert find_exact_local_media(video_id, [folder]) == media
            report["checks"].append("exact-video-id-media-discovery")

            registry = folder / "verified_media.json"
            save_verified_media(registry, video_id, media)
            assert get_verified_media(registry, video_id) == media
            report["checks"].append("verified-media-registry-roundtrip")

            model_dir = folder / "model"
            model_dir.mkdir()
            (model_dir / "model.bin").write_bytes(b"synthetic-model-placeholder")

            class SyntheticModel:
                def transcribe(self, source, **kwargs):
                    if Path(source) != media:
                        raise AssertionError("Wrong media selected")
                    return iter([
                        SimpleNamespace(
                            start=1.25, end=3.75,
                            text="Фактичний тестовий транскрипт",
                        )
                    ]), {}

            transcript_dir = folder / "transcripts"
            output = generate_srt_offline(
                video_id=video_id,
                media=media,
                destination=transcript_dir,
                model_dir=model_dir,
                whisper_factory=lambda *args, **kwargs: SyntheticModel(),
            )
            assert output.is_file()
            rows, source = find_local_transcript(transcript_dir, video_id)
            assert source == "nas-srt", source
            assert rows and "транскрипт" in rows[0]["text"]
            report["checks"].append("synthetic-whisper-to-srt-to-seo-input")

        report["status"] = "PASS"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    try:
        report_path = Path(report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        return 2
    return 0 if report["status"] == "PASS" else 1
