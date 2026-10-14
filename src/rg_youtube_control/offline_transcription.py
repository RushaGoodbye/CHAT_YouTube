"""Conservative offline transcription from verified local video media.

Requires the optional faster-whisper package and an EXISTING model directory.
No model downloading is permitted; output is saved atomically as VideoID.srt.
Call only in a background worker, never the Qt event thread.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .local_media_sources import valid_video_id


def generate_srt_offline(
    *,
    video_id: str,
    media: Path,
    destination: Path,
    model_dir: Path,
    whisper_factory: Any = None,
) -> Path:
    if not valid_video_id(video_id):
        raise ValueError("Invalid YouTube video ID")
    media = Path(media)
    model_dir = Path(model_dir)
    destination = Path(destination)
    if not media.is_file() or media.stat().st_size == 0:
        raise FileNotFoundError("Verified local media file is missing")
    if not model_dir.is_dir() or not (model_dir / "model.bin").is_file():
        raise FileNotFoundError("Local faster-whisper model is unavailable; no download attempted")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / (video_id + ".srt")
    if target.exists():
        raise FileExistsError("Do not overwrite an existing transcript")
    if whisper_factory is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Optional faster-whisper package is not installed") from exc
        whisper_factory = WhisperModel
    # local_files_only prevents model downloads if a factory supports it;
    # a verified absolute model directory is mandatory in any case.
    temp = destination / (video_id + ".srt.tmp")

    def stamp(t: float) -> str:
        millis = max(0, round(float(t) * 1000))
        hh, rem = divmod(millis, 3600000)
        mm, rem = divmod(rem, 60000)
        ss, ms = divmod(rem, 1000)
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

    def write_transcription(*, device: str, compute_type: str) -> int:
        # Whisper segments are lazy; GPU DLL failures may occur during the
        # iteration, not only at model construction or transcribe().
        model = whisper_factory(str(model_dir), device=device, compute_type=compute_type)
        segments, _ = model.transcribe(str(media), beam_size=5, vad_filter=True)
        count = 0
        with temp.open("x", encoding="utf-8") as out:
            for segment in segments:
                words = " ".join(str(segment.text).split())
                if not words or segment.end <= segment.start:
                    continue
                count += 1
                out.write(
                    f"{count}\n{stamp(segment.start)} --> {stamp(segment.end)}\n"
                    f"{words}\n\n"
                )
        return count

    def is_gpu_runtime_failure(exc: Exception) -> bool:
        if not isinstance(exc, (RuntimeError, OSError)):
            return False
        message = str(exc).lower()
        return any(token in message for token in (
            "cuda", "cudnn", "cublas", "cufft", "nvrtc", "cusparse",
            "nvcuda", "gpu device", "device gpu",
        ))

    try:
        try:
            count = write_transcription(device="auto", compute_type="auto")
        except (RuntimeError, OSError) as exc:
            if not is_gpu_runtime_failure(exc):
                raise
            # Retry only GPU/CUDA runtime errors. Do not silently mask
            # decoding errors, missing media, or invalid transcription data.
            temp.unlink(missing_ok=True)
            count = write_transcription(device="cpu", compute_type="int8")
        if not count:
            raise RuntimeError("Recognition produced no caption segments")
        if target.exists():
            raise FileExistsError("Target was created concurrently")
        os.replace(temp, target)
        return target
    finally:
        temp.unlink(missing_ok=True)
