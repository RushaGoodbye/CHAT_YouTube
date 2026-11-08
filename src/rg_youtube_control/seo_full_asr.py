"""Offline complete-audio SRT acquisition and reproducible ASR comparison.

This subsystem never writes the YouTube database, creates an approval or posts
content. Every audio chunk is accounted for, including speechless windows.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Any

from .seo_caption_manifest import audit_caption_file, make_source_manifest

MAX_DURATION_S = 48 * 3600
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class CaptionSegment:
    start: float
    end: float
    text: str

    def __post_init__(self) -> None:
        if not (0 <= self.start < self.end <= MAX_DURATION_S):
            raise ValueError("INVALID_SEGMENT_TIMING")
        if not self.text.strip():
            raise ValueError("EMPTY_SEGMENT")


def stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def segments_to_srt(items: Iterable[CaptionSegment]) -> bytes:
    data = list(items)
    if not data:
        raise ValueError("EMPTY_TRANSCRIPT")
    last = -1.0
    rows: list[str] = []
    for i, part in enumerate(data, 1):
        if part.start < last:
            raise ValueError("UNSORTED_SEGMENTS")
        last = part.start
        clean = " ".join(part.text.split())
        rows.append(f"{i}\n{stamp(part.start)} --> {stamp(part.end)}\n{clean}")
    return ("\n\n".join(rows) + "\n").encode("utf-8")


def window_bounds(duration_s: float, chunk_s: float = 300) -> list[tuple[float, float]]:
    if not (0 < duration_s <= MAX_DURATION_S):
        raise ValueError("INVALID_AUDIO_DURATION")
    if not 10 <= chunk_s <= 1200:
        raise ValueError("INVALID_CHUNK_LENGTH")
    bounds = []
    pos = 0.0
    while pos < duration_s:
        end = min(duration_s, pos + chunk_s)
        if end < duration_s and duration_s - end < min(5.0, chunk_s / 4):
            end = duration_s  # avoid an almost-empty terminal audio chunk
        bounds.append((pos, end))
        pos = end
    return bounds


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout)


def probe_audio(path: Path, *, ffprobe: str = "ffprobe") -> float:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    result = _run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=45)
    duration = float(result.stdout.strip())
    if not (0 < duration <= MAX_DURATION_S):
        raise ValueError("INVALID_AUDIO_DURATION")
    return duration


def extract_wav(source: Path, output: Path, *, start: float, end: float,
                ffmpeg: str = "ffmpeg") -> None:
    # Always process short monotonic windows. No full-stream PCM copies.
    _run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
          "-ss", f"{start:.3f}", "-t", f"{end-start:.3f}", "-i", str(source),
          "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(output)],
         timeout=max(90, 3 * (end - start)))


_WINDOWS_CUDA_DLL_HANDLES: list[Any] = []


def _prepare_windows_cuda_dlls() -> list[str]:
    """Add CUDA dependencies from installed Python libraries, process-locally.

    Do not alter system PATH, copy NVIDIA DLLs or interfere with other apps.
    """
    if os.name != "nt":
        return []
    paths: list[Path] = []
    for module_name, suffix in (("torch", "lib"), ("ctranslate2", "")):
        spec = importlib.util.find_spec(module_name)
        if spec is None or spec.origin is None:
            continue
        base = Path(spec.origin).parent
        candidate = base / suffix if suffix else base
        if candidate.is_dir():
            paths.append(candidate)
    # NVIDIA Python wheels may bundle DLLs separately from torch.
    spec = importlib.util.find_spec("nvidia")
    if spec is not None and spec.submodule_search_locations:
        for base in spec.submodule_search_locations:
            root = Path(base)
            for name in ("cublas", "cudnn", "cuda_runtime"):
                candidate = root / name / "bin"
                if candidate.is_dir():
                    paths.append(candidate)
    # Frozen RG YouTube Control cannot import the host Python's torch.
    # Discover pre-existing per-user CUDA DLLs by bounded known layouts,
    # without modifying the host environment or copying other app files.
    user_python = Path.home() / "AppData" / "Local" / "Python"
    if user_python.is_dir():
        for candidate in user_python.glob("pythoncore-*/Lib/site-packages/torch/lib"):
            if candidate.is_dir():
                paths.append(candidate)
        for candidate in user_python.glob("pythoncore-*/Lib/site-packages/ctranslate2"):
            if candidate.is_dir():
                paths.append(candidate)
    added: list[str] = []
    for path in dict.fromkeys(paths):
        try:
            _WINDOWS_CUDA_DLL_HANDLES.append(os.add_dll_directory(str(path)))
            added.append(str(path))
        except OSError:
            continue
    if added:
        os.environ["PATH"] = os.pathsep.join(added) + os.pathsep + os.environ.get("PATH", "")
    return added


def _whisper_recognizer(model_name: str, device: str, compute_type: str,
                        *, language: str | None) -> Callable[[Path], list[CaptionSegment]]:
    if device == "cuda":
        _prepare_windows_cuda_dlls()
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    def recognize(chunk: Path) -> list[CaptionSegment]:
        segments, _info = model.transcribe(
            str(chunk), language=language, beam_size=5, vad_filter=True,
            condition_on_previous_text=False,
        )
        return [CaptionSegment(float(s.start), float(s.end), str(s.text).strip())
                for s in segments if str(s.text).strip() and s.end > s.start]
    return recognize


def parakeet_tokens_to_segments(
    tokens: Iterable[str], timestamps: Iterable[float], *,
    max_segment_s: float = 6.0,
) -> list[CaptionSegment]:
    """Format actual Parakeet token timestamps into readable SRT segments."""
    pairs = list(zip(tokens, timestamps))
    if not pairs:
        return []
    output: list[CaptionSegment] = []
    pending: list[str] = []
    start = float(pairs[0][1])
    previous = start

    def flush(end: float) -> None:
        nonlocal pending
        content = " ".join("".join(pending).split())
        if content:
            output.append(CaptionSegment(start, max(start + .08, end), content))
        pending = []

    for i, (token, value) in enumerate(pairs):
        instant = float(value)
        if instant < previous - .01:
            raise ValueError("PARAKEET_NONMONOTONIC_TOKEN_TIMES")
        # Parakeet emits subword tokens. Never split inside a word merely
        # because a time-window limit was reached.
        at_word_boundary = bool(str(token)[:1].isspace())
        if pending and (instant - start >= max_segment_s and at_word_boundary
                        or instant - start >= max_segment_s * 1.6):
            flush(previous + .08)
            start = instant
        pending.append(str(token))
        previous = instant
        if (instant - start >= 1.5 and str(token).rstrip().endswith((".", "!", "?"))
                and (i + 1 == len(pairs) or float(pairs[i + 1][1]) > instant)):
            flush(instant + .08)
            if i + 1 < len(pairs):
                start = float(pairs[i + 1][1])
    if pending:
        flush(previous + .12)
    return output


def _parakeet_recognizer(model_name: str = "nemo-parakeet-tdt-0.6b-v3"
                        ) -> Callable[[Path], list[CaptionSegment]]:
    # Lightweight cross-platform ONNX backend, not heavyweight NeMo.
    try:
        import onnx_asr
    except ImportError as exc:
        raise RuntimeError("PARAKEET_ONNX_ASR_NOT_INSTALLED") from exc
    model = onnx_asr.load_model(
        model_name, quantization="int8", providers=["CPUExecutionProvider"]
    ).with_timestamps()
    def recognize(chunk: Path) -> list[CaptionSegment]:
        hypothesis = model.recognize(str(chunk))
        words = getattr(hypothesis, "tokens", [])
        times = getattr(hypothesis, "timestamps", [])
        if len(words) != len(times):
            raise ValueError("PARAKEET_TOKEN_TIMESTAMPS_MISMATCH")
        result = parakeet_tokens_to_segments(words, times)
        if not result and str(getattr(hypothesis, "text", "")).strip():
            raise ValueError("PARAKEET_NO_SEGMENT_TIMESTAMPS")
        return result
    return recognize


def recognize_complete_audio(
    *, source: Path, output_dir: Path, video_id: str,
    engine: str = "whisper", duration_s: float | None = None,
    chunk_s: float = 300, model_name: str | None = None,
    device: str = "cuda", compute_type: str = "float16",
    language: str | None = None, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
    recognizer: Callable[[Path], list[CaptionSegment]] | None = None,
    extract: Callable[[Path, Path, float, float], None] | None = None,
) -> dict[str, Any]:
    """Transcribe 100% of an audio timeline, and persist errors before raising.

    This function uses a separate engine suffix so candidates never overwrite
    a verified YouTube caption, user transcript or another model's output.
    """
    source = Path(source)
    output_dir = Path(output_dir)
    if not _VIDEO_ID.fullmatch(video_id):
        raise ValueError("INVALID_VIDEO_ID")
    if engine not in {"whisper", "parakeet"}:
        raise ValueError("INVALID_ENGINE")
    duration = probe_audio(source, ffprobe=ffprobe) if duration_s is None else float(duration_s)
    bounds = window_bounds(duration, chunk_s)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{video_id}.{engine}"
    target = output_dir / f"{prefix}.srt"
    manifest_path = output_dir / f"{prefix}.asr.json"
    if recognizer is None:
        if engine == "whisper":
            recognizer = _whisper_recognizer(
                model_name or "large-v3", device, compute_type, language=language
            )
        else:
            recognizer = _parakeet_recognizer(model_name or "nemo-parakeet-tdt-0.6b-v3")
    windows: list[dict[str, Any]] = []
    combined: list[CaptionSegment] = []
    try:
        with tempfile.TemporaryDirectory(prefix="rg_asr_") as td:
            scratch = Path(td)
            for i, (start, end) in enumerate(bounds):
                wav = scratch / f"chunk_{i:05d}.wav"
                if extract is not None:
                    extract(source, wav, start, end)
                else:
                    extract_wav(source, wav, start=start, end=end, ffmpeg=ffmpeg)
                relative = list(recognizer(wav))
                for item in relative:
                    if item.end > (end - start) + 1.0:
                        raise ValueError("ASR_SEGMENT_EXCEEDS_CHUNK")
                    combined.append(CaptionSegment(
                        start + max(0, item.start),
                        min(duration, start + item.end), item.text,
                    ))
                windows.append({
                    "start_s": start, "end_s": end,
                    "segment_count": len(relative),
                    "audio_processed": True,
                    "has_speech": bool(relative),
                })
        raw = segments_to_srt(combined)
        manifest = {
            "schema": "RG_FULL_ASR_V1",
            "video_id": video_id, "engine": engine,
            "model": model_name or ("large-v3" if engine == "whisper" else "nemo-parakeet-tdt-0.6b-v3"),
            "duration_s": duration,
            "windows": windows, "windows_processed": len(windows),
            "windows_expected": len(bounds),
            "all_audio_windows_processed": len(windows) == len(bounds),
            "srt_sha256": hashlib.sha256(raw).hexdigest(),
            "transcription_verified": False,
            "editorial_approved": False, "publication_allowed": False,
        }
        # Never write a partial SRT to a destination name after a chunk failure.
        stage = output_dir / f"{prefix}.stage.srt"
        stage.write_bytes(raw)
        try:
            stage.replace(target)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            stage.unlink(missing_ok=True)
        return {"status": "TRANSCRIBED_UNREVIEWED", "srt_path": str(target),
                "manifest_path": str(manifest_path), **manifest}
    except Exception as exc:
        failure = {
            "status": "BLOCKED_INCOMPLETE_TRANSCRIPT",
            "video_id": video_id, "engine": engine,
            "error": type(exc).__name__ + ": " + str(exc)[:300],
            "windows_processed": len(windows), "windows_expected": len(bounds),
            "editorial_approved": False, "publication_allowed": False,
        }
        manifest_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        raise


def compare_asr_transcripts(a: list[CaptionSegment], b: list[CaptionSegment]) -> dict[str, Any]:
    """Unsupervised disagreement proxy; not an accuracy or WER benchmark."""
    def tokens(parts: list[CaptionSegment]) -> set[str]:
        return {word for part in parts for word in re.findall(r"\w+", part.text.casefold())}
    left, right = tokens(a), tokens(b)
    overlap = len(left & right) / len(left | right) if left or right else 1.0
    return {"lexical_jaccard": round(overlap, 4),
            "candidate_1_segments": len(a), "candidate_2_segments": len(b),
            "human_reference_required_for_accuracy": True,
            "winner": None}