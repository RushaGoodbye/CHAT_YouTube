"""Short sampled local speech checks for media candidates, never automatic binds.

Whisper runs ONLY on shortlisted media, with audio decoded from bounded
12-second windows rather than loading long videos into memory.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, Sequence

from .media_content_matching import MediaCandidate
from .seo_source_alignment import check_title_against_transcript


def sample_audio_window(
    path: Path, *,
    start_seconds: float, max_seconds: float = 12.0,
):
    """Seek by audio stream timestamp and decode at most a short mono window."""
    import av
    import numpy as np

    if max_seconds <= 0 or max_seconds > 20:
        raise ValueError("sample window outside safe bounds")
    with av.open(str(path)) as container:
        streams = [s for s in container.streams if s.type == "audio"]
        if not streams:
            return None
        stream = streams[0]
        start_seconds = max(0.0, float(start_seconds))
        if start_seconds and stream.time_base:
            container.seek(
                max(0, int(start_seconds / float(stream.time_base))),
                stream=stream, backward=True,
            )
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        pieces = []
        collected = 0
        needed = int(16000 * max_seconds)
        for frame in container.decode(stream):
            frame_seconds = (
                float(frame.time) if frame.time is not None else None
            )
            if frame_seconds is not None and (
                frame_seconds + frame.samples / frame.sample_rate < start_seconds
            ):
                continue
            if frame_seconds is not None and frame_seconds > start_seconds + max_seconds:
                break
            for converted in resampler.resample(frame):
                pcm = np.frombuffer(converted.to_ndarray().tobytes(), dtype=np.int16)
                if frame_seconds is not None and frame_seconds < start_seconds:
                    trim = max(0, min(len(pcm), int(
                        (start_seconds - frame_seconds) * 16000
                    )))
                    pcm = pcm[trim:]
                if len(pcm):
                    take = min(needed - collected, len(pcm))
                    pieces.append(pcm[:take].astype(np.float32) / 32768.0)
                    collected += take
                if collected >= needed:
                    break
            if collected >= needed:
                break
        if not pieces or collected < 16000:
            return None
        return np.concatenate(pieces)


def annotate_sampled_speech(
    candidates: Sequence[MediaCandidate],
    *,
    model_dir: Path,
    title: str,
    progress: Callable[[str], None] | None = None,
    max_candidates: int = 5,
    model_factory=None,
    audio_reader=sample_audio_window,
) -> list[MediaCandidate]:
    """Recognize speech for top duration-matched candidates, without writes.

    Returns a candidate shortlist for user review. A matching mention of a
    named subject is a hint, NEVER authoritative video-to-file verification.
    """
    output = list(candidates)
    if not output or not (Path(model_dir) / "model.bin").is_file():
        return output
    if model_factory is None:
        from faster_whisper import WhisperModel
        model_factory = WhisperModel
    if progress:
        progress("Підготовка Whisper для коротких уривків кандидатів")
    try:
        model = model_factory(str(model_dir), device="auto", compute_type="auto")
    except (OSError, RuntimeError, ValueError, ImportError):
        return output

    for index in range(min(len(output), max_candidates)):
        candidate = output[index]
        if progress:
            progress(
                f"Перевірка мовлення {index + 1}/{min(len(output), max_candidates)}: "
                f"{candidate.path.name[:75]}"
            )
        excerpts: list[str] = []
        for fraction in (0.18, 0.62):
            start = max(0.0, candidate.duration * fraction - 6.0)
            try:
                audio = audio_reader(candidate.path, start_seconds=start)
                if audio is None:
                    continue
                segments, _ = model.transcribe(
                    audio, beam_size=1, vad_filter=True,
                    condition_on_previous_text=False,
                    temperature=0.0,
                )
                excerpt = " ".join(
                    str(seg.text).strip() for seg in segments
                    if str(seg.text).strip()
                )
                if excerpt:
                    excerpts.append(excerpt[:300])
            except (OSError, RuntimeError, ValueError, EOFError):
                continue
        joined = " ".join(excerpts)
        match = check_title_against_transcript(title, joined)
        output[index] = replace(
            candidate,
            speech_excerpt=joined[:300],
            speech_subject=bool(match.anchors and match.passed),
        )
    return sorted(
        output,
        key=lambda c: (
            not c.speech_subject,
            not c.sidecar_subject,
            c.duration_delta,
            -c.title_score,
            str(c.path),
        ),
    )
