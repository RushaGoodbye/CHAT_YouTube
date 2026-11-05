"""Zero-vidIQ-credit audio fallback for missing YouTube captions.

Downloads only the requested public video audio using yt-dlp, converts to SRT
with offline ASR, and caches an explicitly UNREVIEWED transcript. No publishing.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
from typing import Any

from .seo_full_asr import recognize_complete_audio

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def cached_unreviewed_audio_srt(
    *, video_id: str, cache_dir: Path, duration_s: float
) -> Path | None:
    cache = Path(cache_dir)
    srt = cache / f"{video_id}.whisper.srt"
    audit_path = cache / f"{video_id}.whisper.asr.json"
    provenance_path = cache / f"{video_id}.whisper.audio_source.json"
    if not all(p.is_file() for p in (srt, audit_path, provenance_path)):
        return None
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if not (audit.get("video_id") == video_id
                and provenance.get("video_id") == video_id
                and provenance.get("yt_dlp_video_id") == video_id
                and provenance.get("method") == "youtube_audio_download"
                and audit.get("all_audio_windows_processed") is True
                and audit.get("windows_processed") == audit.get("windows_expected")
                and abs(float(audit["duration_s"]) - duration_s) <= max(3, duration_s * .05)
                and audit.get("srt_sha256") == sha256(srt.read_bytes()).hexdigest()
                and audit.get("publication_allowed") is False):
            return None
        return srt
    except (ValueError, OSError, KeyError, TypeError):
        return None


def acquire_full_srt_from_public_youtube_audio(
    *, video_id: str, cache_dir: Path, duration_s: float,
    chunk_s: float = 300,
    device: str = "cuda", compute_type: str = "float16",
    model_name: str = "large-v3",
) -> dict[str, Any]:
    """Complete unattended ASR acquisition only when YouTube captions absent.

    Runs in the foreground of RG YouTube Control, never a scheduler or service.
    Existing incomplete ASR is not reused or approved.
    """
    if not _VIDEO_ID.fullmatch(video_id or "") or duration_s <= 0:
        raise ValueError("INVALID_VIDEO_REQUEST")
    cache_dir = Path(cache_dir)
    previous = cached_unreviewed_audio_srt(
        video_id=video_id, cache_dir=cache_dir, duration_s=duration_s
    )
    if previous is not None:
        return {"status": "ASR_CACHED_UNREVIEWED", "srt_path": str(previous),
                "video_id": video_id, "publication_allowed": False}
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("YT_DLP_NOT_INSTALLED") from exc

    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rg_seo_audio_", dir=cache_dir) as tmp:
        folder = Path(tmp)
        url = f"https://www.youtube.com/watch?v={video_id}"
        options = {
            "format": "bestaudio/best",
            "outtmpl": str(folder / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "overwrites": True,
            "retries": 2,
            "fragment_retries": 2,
        }
        with yt_dlp.YoutubeDL(options) as client:
            info = client.extract_info(url, download=True)
        if not isinstance(info, dict) or str(info.get("id")) != video_id:
            raise ValueError("DOWNLOADED_VIDEO_ID_MISMATCH")
        remote_duration = float(info.get("duration") or 0)
        if remote_duration > 0 and abs(remote_duration - duration_s) > max(4, duration_s * .05):
            raise ValueError("DOWNLOADED_VIDEO_DURATION_MISMATCH")
        audio_files = [f for f in folder.glob(video_id + ".*")
                       if f.is_file() and f.suffix.lower() not in {".part", ".ytdl", ".json"}]
        if len(audio_files) != 1:
            raise ValueError("DOWNLOADED_AUDIO_NOT_UNIQUE")
        audio = audio_files[0]
        asr = recognize_complete_audio(
            source=audio, output_dir=cache_dir, video_id=video_id,
            engine="whisper", model_name=model_name,
            chunk_s=chunk_s, device=device, compute_type=compute_type,
        )
        provenance = {
            "schema": "RG_SEO_YOUTUBE_AUDIO_PROVENANCE_V1",
            "video_id": video_id, "yt_dlp_video_id": str(info["id"]),
            "source_url": url,
            "downloaded_audio_sha256": sha256(audio.read_bytes()).hexdigest(),
            "method": "youtube_audio_download",
            "asr_model": model_name,
            "asr_status": asr["status"],
            "semantic_verified": False,
            "publication_allowed": False,
        }
        record = cache_dir / f"{video_id}.whisper.audio_source.json"
        staged = record.with_suffix(".tmp")
        staged.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
        staged.replace(record)
        return {**asr, "source_method": "youtube_audio_download",
                "publication_allowed": False}