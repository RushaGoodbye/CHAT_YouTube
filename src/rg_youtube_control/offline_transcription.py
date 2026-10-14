"""Conservative offline transcription from verified local video media.

Requires the optional faster-whisper package and an EXISTING model directory.
No model downloading is permitted; output is saved atomically as VideoID.srt.
Call only in a background worker, never the Qt event thread.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .local_media_sources import valid_video_id


def _media_duration_seconds(media: Path) -> float | None:
    """Best-effort container duration; never fabricate a completion percentage."""
    try:
        import av
        with av.open(str(media)) as container:
            if container.duration is not None and container.duration > 0:
                return float(container.duration) / 1_000_000
            durations = [
                float(stream.duration * stream.time_base)
                for stream in container.streams
                if stream.duration is not None and stream.time_base is not None
                and stream.duration > 0
            ]
            return max(durations) if durations else None
    except Exception:
        return None


def _clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    minutes, seconds = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def generate_srt_offline(
    *,
    video_id: str,
    media: Path,
    destination: Path,
    model_dir: Path,
    whisper_factory: Any = None,
    on_progress: Any = None,
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
    # Unique temp file prevents stale crash leftovers and concurrent workers
    # from corrupting each other's transcript data.
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{video_id}.", suffix=".srt.tmp", dir=str(destination),
    )
    os.close(temp_fd)
    temp = Path(temp_name)

    # Whisper segments are lazy. A heartbeat also reports model loading and
    # long silent stretches without pretending audio was already processed.
    media_duration = _media_duration_seconds(media) if on_progress else None
    started = time.monotonic()
    state_lock = threading.Lock()
    stop_heartbeat = threading.Event()
    state = {
        "phase": "Завантаження моделі",
        "mode": "AUTO (GPU/CPU)",
        "processed": 0.0,
        "segments": 0,
        "last_emit": 0.0,
        "fallback": False,
    }

    def report(force: bool = False) -> None:
        if on_progress is None:
            return
        now = time.monotonic()
        with state_lock:
            if not force and now - state["last_emit"] < 4:
                return
            state["last_emit"] = now
            snapshot = dict(state)
        elapsed = now - started
        processed = snapshot["processed"]
        percent = (
            min(99, max(0, int(100 * processed / media_duration)))
            if media_duration and processed > 0 else None
        )
        position = _clock(processed)
        total = _clock(media_duration) if media_duration else "невідома тривалість"
        stage = (
            f"Whisper · {snapshot['mode']} · {snapshot['phase']} · "
            f"{position} / {total}"
        )
        eta = "Час роботи " + _clock(elapsed)
        if media_duration and processed >= 15 and elapsed >= 8:
            estimate = elapsed * (media_duration - processed) / processed
            eta += " · ETA " + _clock(max(0, estimate))
        if snapshot["fallback"]:
            eta += " · GPU недоступна: перезапуск на CPU"
        try:
            on_progress({
                "stage": stage, "percent": percent, "eta": eta,
                "mode": snapshot["mode"],
                "processed_seconds": processed, "duration_seconds": media_duration,
                "elapsed_seconds": elapsed, "fallback": snapshot["fallback"],
            })
        except Exception:
            # Progress presentation must not break a valid SRT.
            pass

    def heartbeat() -> None:
        while not stop_heartbeat.wait(8):
            report(force=True)

    heartbeat_thread = None
    if on_progress is not None:
        report(force=True)
        heartbeat_thread = threading.Thread(
            target=heartbeat, name="rg-whisper-progress", daemon=True,
        )
        heartbeat_thread.start()

    def stamp(t: float) -> str:
        millis = max(0, round(float(t) * 1000))
        hh, rem = divmod(millis, 3600000)
        mm, rem = divmod(rem, 60000)
        ss, ms = divmod(rem, 1000)
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

    def write_transcription(*, device: str, compute_type: str) -> int:
        # Whisper segments are lazy; GPU DLL failures may occur during the
        # iteration, not only at model construction or transcribe().
        with state_lock:
            state["phase"] = "Завантаження моделі"
            state["mode"] = "CPU (int8)" if device == "cpu" else "AUTO (GPU/CPU)"
        report(force=True)
        model = whisper_factory(str(model_dir), device=device, compute_type=compute_type)
        actual_device = str(getattr(getattr(model, "model", None), "device", "")).lower()
        if actual_device in ("cuda", "gpu", "cpu"):
            with state_lock:
                state["mode"] = "GPU (CUDA)" if actual_device != "cpu" else "CPU"
        with state_lock:
            state["phase"] = "Декодування / розпізнавання"
        report(force=True)
        segments, _ = model.transcribe(str(media), beam_size=5, vad_filter=True)
        count = 0
        with temp.open("w", encoding="utf-8") as out:
            for segment in segments:
                words = " ".join(str(segment.text).split())
                if not words or segment.end <= segment.start:
                    continue
                count += 1
                with state_lock:
                    state["processed"] = max(state["processed"], float(segment.end))
                    state["segments"] = count
                report()
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
            with state_lock:
                state["processed"] = 0.0
                state["segments"] = 0
                state["phase"] = "Повторна спроба після помилки CUDA"
                state["mode"] = "CPU (int8)"
                state["fallback"] = True
            report(force=True)
            count = write_transcription(device="cpu", compute_type="int8")
        if not count:
            raise RuntimeError("Recognition produced no caption segments")
        if target.exists():
            raise FileExistsError("Target was created concurrently")
        os.replace(temp, target)
        with state_lock:
            state["phase"] = f"SRT готовий · {count} фрагментів"
        report(force=True)
        return target
    finally:
        stop_heartbeat.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
        temp.unlink(missing_ok=True)
