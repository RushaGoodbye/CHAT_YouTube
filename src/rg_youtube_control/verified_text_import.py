"""Opt-in import of untimed, exact-video-ID transcript text.

This is an EDITOR-REVIEW input, never a substitute for proof that a local
media file belongs to an upload and never grounds fabricated timestamps.
Original NAS SRT files are never modified.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_MAX_BYTES = 2 * 1024 * 1024


def _paths(data_dir: Path, video_id: str) -> tuple[Path, Path]:
    if not _ID.fullmatch(str(video_id or "")):
        raise ValueError("Invalid exact YouTube Video ID")
    root = Path(data_dir) / "seo_verified_text"
    return root / f"{video_id}.txt", root / f"{video_id}.json"


def import_verified_text(
    data_dir: Path,
    video_id: str,
    source_path: Path,
    *,
    current_title: str,
) -> Path:
    """Import after separate explicit user confirmation of video identity.

    Stores a checksum and a provenance marker to detect edits after import.
    This is not an independently authenticated YouTube caption track.
    """
    source = Path(source_path)
    raw = source.read_bytes()
    if not 300 <= len(raw) <= _MAX_BYTES:
        raise ValueError("Текстова розшифровка занадто коротка або велика.")
    text = raw.decode("utf-8-sig").strip()
    if "\x00" in text or len(text.split()) < 70:
        raise ValueError("Потрібен повний текст розшифровки, а не коротка нотатка.")
    from .seo_source_alignment import check_title_against_transcript
    alignment = check_title_against_transcript(current_title, text)
    if alignment.missing:
        raise ValueError(
            "Розшифровка не згадує основну тему назви: "
            + ", ".join(alignment.missing)
        )
    transcript_path, manifest_path = _paths(data_dir, video_id)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite a previously confirmed source silently.
    if transcript_path.exists() or manifest_path.exists():
        raise FileExistsError(
            "Підтверджений TXT для цього Video ID вже існує. "
            "Повторний імпорт заблоковано; спочатку перевірте джерело."
        )
    encoded = text.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    manifest = {
        "schema": "RG_SEO_USER_CONFIRMED_TEXT_V1",
        "video_id": video_id,
        "title_at_import": current_title,
        "source_filename": source.name,
        "sha256": digest,
        "no_timestamps": True,
        "review_required": True,
        "source_confirmation": "explicit-user-approval",
    }
    tmp_text = transcript_path.with_suffix(".txt.tmp")
    tmp_manifest = manifest_path.with_suffix(".json.tmp")
    try:
        tmp_text.write_bytes(encoded)
        tmp_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_text, transcript_path)
        os.replace(tmp_manifest, manifest_path)
    finally:
        tmp_text.unlink(missing_ok=True)
        tmp_manifest.unlink(missing_ok=True)
    return transcript_path


def load_verified_text(
    data_dir: Path, video_id: str,
) -> tuple[list[dict[str, Any]], str]:
    try:
        transcript_path, manifest_path = _paths(data_dir, video_id)
        info = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(info, dict) or info.get("schema") != "RG_SEO_USER_CONFIRMED_TEXT_V1":
            return [], ""
        if info.get("video_id") != video_id or info.get("no_timestamps") is not True:
            return [], ""
        if info.get("review_required") is not True:
            return [], ""
        raw = transcript_path.read_bytes()
        if not raw or len(raw) > _MAX_BYTES:
            return [], ""
        if hashlib.sha256(raw).hexdigest() != info.get("sha256"):
            return [], ""
        text = raw.decode("utf-8")
        if len(text.split()) < 70:
            return [], ""
        # One untimed cue; downstream chunks it without claiming false
        # speaker boundaries or inventing minute/second offsets.
        return [{
            "start": 0.0, "duration": 0.0, "text": text,
            "untimed": True,
        }], "manual-confirmed-untimed-text"
    except (OSError, ValueError, UnicodeError, TypeError):
        return [], ""
