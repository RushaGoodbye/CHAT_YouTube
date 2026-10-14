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
        roots.append(Path(r"D:\YOUTUBE\RUSHA GOODBYE\Раша GOODBYE\ГОТОВО\YouTube"))
    configured = os.environ.get("RG_SEO_MEDIA_DIR", "").strip()
    if configured:
        roots.insert(0, Path(configured).expanduser())
    return list(dict.fromkeys(roots))


def local_whisper_model_dir(data_dir: Path) -> Path:
    """Resolve previously chosen or cached faster-whisper model, offline."""
    configured = os.environ.get("RG_SEO_WHISPER_MODEL_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()

    saved = Path(data_dir) / "whisper_model_dir.txt"
    try:
        if saved.is_file():
            choice = Path(saved.read_text(encoding="utf-8").strip()).expanduser()
            if (choice / "model.bin").is_file():
                return choice
    except (OSError, ValueError):
        pass

    default = Path(data_dir) / "models" / "faster-whisper-large-v3"
    if (default / "model.bin").is_file():
        return default

    # Fast bounded lookup in Hugging Face caches: only one model repository
    # and snapshot directory, never traverse the user's disk.
    caches = []
    if os.environ.get("HF_HUB_CACHE"):
        caches.append(Path(os.environ["HF_HUB_CACHE"]).expanduser())
    if os.environ.get("HF_HOME"):
        caches.append(Path(os.environ["HF_HOME"]).expanduser() / "hub")
    caches.append(Path.home() / ".cache" / "huggingface" / "hub")
    for cache in caches:
        snapshots = cache / "models--Systran--faster-whisper-large-v3" / "snapshots"
        try:
            for snapshot in snapshots.iterdir():
                if (snapshot / "model.bin").is_file():
                    return snapshot
        except (OSError, ValueError):
            continue
    return default


def remember_whisper_model_dir(data_dir: Path, selected_dir: Path) -> Path:
    """Store a user-approved local model directory (no download)."""
    selected = Path(selected_dir).expanduser()
    if not (selected / "model.bin").is_file():
        raise FileNotFoundError("Missing model.bin in selected Whisper folder")
    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    tmp = data / "whisper_model_dir.txt.tmp"
    tmp.write_text(str(selected), encoding="utf-8")
    tmp.replace(data / "whisper_model_dir.txt")
    return selected
