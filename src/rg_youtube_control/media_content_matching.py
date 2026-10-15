"""Offline, read-only search for likely originals of renamed YouTube videos.

Candidate discovery NEVER establishes source identity. It uses local container
durations, historic titles and, where present, original-file sidecar captions.
The UI must obtain explicit approval after reviewing the actual media.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
from typing import Callable, Iterable

from .local_media_sources import MEDIA_EXTENSIONS
from .seo_source_alignment import check_title_against_transcript

SCHEMA = "RG_SEO_MEDIA_CANDIDATES_V1"
SCAN_LIMIT = 6000
CANDIDATE_LIMIT = 12


@dataclass(frozen=True)
class MediaCandidate:
    path: Path
    duration: float
    duration_delta: float
    title_score: float
    sidecar_excerpt: str
    sidecar_subject: bool
    speech_excerpt: str = ""
    speech_subject: bool = False

    def label(self) -> str:
        h, rem = divmod(round(self.duration), 3600)
        m, sec = divmod(rem, 60)
        runtime = f"{h:02d}:{m:02d}:{sec:02d}"
        if self.speech_subject:
            evidence = "ТЕМА В МОВЛЕННІ"
        elif self.sidecar_subject:
            evidence = "ТЕМА В СУБТИТРАХ ФАЙЛУ"
        elif self.speech_excerpt:
            evidence = "МОВЛЕННЯ БЕЗ ЗБІГУ"
        else:
            evidence = "МОВЛЕННЯ ЩЕ НЕ ПЕРЕВІРЕНО"
        return (f"{runtime} · Δ{self.duration_delta:.0f}с · "
                f"{evidence} · {self.path.name}")


def _normal(value: str) -> str:
    return " ".join(re.findall(r"\w+", str(value or "").casefold()))


def _duration(path: Path) -> float | None:
    """Read only container metadata, never decode whole media into RAM."""
    try:
        import av
        with av.open(str(path)) as container:
            if container.duration is not None and container.duration > 0:
                return float(container.duration) / 1_000_000
            valid = [
                float(stream.duration * stream.time_base)
                for stream in container.streams
                if stream.duration and stream.time_base
            ]
            return max(valid) if valid else None
    except (OSError, ValueError, RuntimeError, EOFError, ImportError, OverflowError):
        return None


def _read_sidecar(path: Path, max_bytes: int = 512_000) -> str:
    """Sidecar hints are from original file, never from a mislabeled NAS ID."""
    for ext in (".srt", ".vtt", ".txt"):
        sidecar = path.with_suffix(ext)
        try:
            if not sidecar.is_file() or sidecar.stat().st_size > max_bytes:
                continue
            text = sidecar.read_text(encoding="utf-8-sig", errors="replace")
            # A local transcript is only evidence of speech, not video identity.
            if text:
                return " ".join(text.split())[:3000]
        except OSError:
            continue
    return ""


def _local_roots(roots: Iterable[Path]) -> list[Path]:
    unique = []
    for raw in roots:
        path = Path(raw)
        # Avoid stalled SMB folders or recursive arbitrary disk traversal.
        if str(path).startswith("\\\\") or str(path) in (".", ""):
            continue
        if path not in unique:
            unique.append(path)
    return unique


def _load_cache(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj["items"] if obj.get("schema") == SCHEMA and isinstance(obj.get("items"), dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_cache(path: Path | None, cache: dict) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"schema": SCHEMA, "items": cache}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        # No cache must never break read-only source discovery.
        pass


def shortlist_local_media(
    *,
    roots: Iterable[Path],
    expected_seconds: int,
    title: str,
    older_titles: Iterable[str] = (),
    cache_path: Path | None = None,
    progress: Callable[[str], None] | None = None,
    limit: int = CANDIDATE_LIMIT,
    duration_reader: Callable[[Path], float | None] = _duration,
) -> list[MediaCandidate]:
    """Bounded read-only metadata search, stable across vidIQ renames.

    Reject missing published duration: filenames alone cannot verify an
    association. Duration is a FILTER, not proof of the same video.
    """
    if expected_seconds < 30:
        return []
    cache = _load_cache(cache_path)
    tolerance = max(6.0, min(60.0, expected_seconds * 0.035))
    titles = [_normal(t) for t in (title, *older_titles) if _normal(t)]
    examined = 0
    candidates: list[MediaCandidate] = []
    for root in _local_roots(roots):
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if examined >= SCAN_LIMIT:
                        break
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    media = Path(entry.path)
                    if media.suffix.lower() not in MEDIA_EXTENSIONS:
                        continue
                    examined += 1
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if st.st_size <= 0:
                        continue
                    key = str(media)
                    cached = cache.get(key) or {}
                    if (cached.get("size") == st.st_size
                            and cached.get("mtime_ns") == st.st_mtime_ns):
                        duration = cached.get("duration")
                    else:
                        duration = duration_reader(media)
                        cache[key] = {
                            "duration": duration,
                            "size": st.st_size,
                            "mtime_ns": st.st_mtime_ns,
                        }
                    if examined % 80 == 0 and progress:
                        progress(f"Пошук оригіналів: перевірено {examined} файлів")
                    if not isinstance(duration, (int, float)) or duration <= 0:
                        continue
                    delta = abs(duration - expected_seconds)
                    if delta > tolerance:
                        continue
                    file_name = _normal(media.stem)
                    similarity = max(
                        (SequenceMatcher(None, file_name, t).ratio() for t in titles),
                        default=0.0,
                    )
                    sidecar = _read_sidecar(media)
                    sidecar_subject = bool(
                        sidecar
                        and check_title_against_transcript(title, sidecar).anchors
                        and check_title_against_transcript(title, sidecar).passed
                    )
                    candidates.append(MediaCandidate(
                        path=media,
                        duration=float(duration),
                        duration_delta=delta,
                        title_score=similarity,
                        sidecar_excerpt=sidecar[:180],
                        sidecar_subject=sidecar_subject,
                    ))
        except OSError:
            continue
        if examined >= SCAN_LIMIT:
            break
    _save_cache(cache_path, cache)
    # Never reward filename similarity over measured duration / speech evidence.
    return sorted(
        candidates,
        key=lambda c: (
            not c.sidecar_subject,
            c.duration_delta,
            -c.title_score,
            str(c.path),
        ),
    )[:max(1, limit)]
