"""Explicitly invoked faster-whisper transcription adapter.

No model downloads are initiated by this module. The caller supplies a local
model directory and an existing recording path; app startup never imports CUDA.
"""
from __future__ import annotations
from pathlib import Path


def transcribe_local_recording(
    recording: str | Path,
    *,
    model_directory: str | Path,
    device: str = "cuda",
    compute_type: str = "float16",
    language: str | None = None,
) -> list[dict]:
    recording = Path(recording)
    model_directory = Path(model_directory)
    if not recording.is_file():
        raise FileNotFoundError(f"recording_not_found: {recording}")
    if not model_directory.is_dir():
        raise FileNotFoundError(f"local_model_not_found: {model_directory}")
    from faster_whisper import WhisperModel

    model = WhisperModel(str(model_directory), device=device,
                         compute_type=compute_type, local_files_only=True)
    segments, _ = model.transcribe(str(recording), language=language,
                                   vad_filter=True, beam_size=5)
    return [{"start": float(segment.start), "duration": max(0.0, float(segment.end-segment.start)),
             "text": str(segment.text).strip()}
            for segment in segments if str(segment.text).strip()]
