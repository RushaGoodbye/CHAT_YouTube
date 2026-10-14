"""Configured offline media/model locations for RG YouTube Control.

Paths may be supplied by an administrator via environment variables, without
broad recursive disk scans, silent downloads or mutable application settings.
"""
from __future__ import annotations

import os
from pathlib import Path


def local_seo_media_roots(data_dir: Path, transcript_dir: Path) -> list[Path]:
    roots = [Path(data_dir) / "seo_media", Path(transcript_dir) / "media"]
    if os.name == "nt":
        roots.append(Path(r"D:\\YOUTUBE\\RUSHA GOODBYE\\Раша GOODBYE\\ГОТОВО\\YouTube"))
    configured = os.environ.get("RG_SEO_MEDIA_DIR", "").strip()
    if configured:
        roots.insert(0, Path(configured).expanduser())
    return list(dict.fromkeys(roots))


def local_whisper_model_dir(data_dir: Path) -> Path:
    configured = os.environ.get("RG_SEO_WHISPER_MODEL_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path(data_dir) / "models" / "faster-whisper-large-v3"
