"""Worker-thread NAS/YouTube I/O for the deep archive draft queue.

No Qt widgets and no GUI SQLite connection belong here. This module never
modifies public YouTube metadata, publishes videos, or applies SEO packages.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .archive_campaign import export_deep_review_manifest
from .config import PACKAGE_BRIDGE_URL, PROFILE_TARGETS
from .package_bridge import upload_transcript
from .service import (
    CAPTION_TRANSCRIPT_COST,
    quota_budget_status,
    record_quota_units,
)

VideoClientFactory = Callable[[str], Any]
TranscriptUploader = Callable[[str, str, str, dict[str, Any]], None]
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def prepare_deep_review_batch(
    conn: sqlite3.Connection,
    *,
    profile: str,
    transcript_dir: Path,
    package_dir: Path,
    max_downloads: int,
    client_factory: VideoClientFactory,
    uploader: TranscriptUploader = upload_transcript,
    limit: int = 20,
) -> dict[str, Any]:
    """Export an atomic manifest, collect local drafts and optional captions.

    Runs only in a background QThread with its own SQLite connection. Every
    YouTube caption quota debit uses that same connection and respects the
    configured reserve. A download is never a metadata publication.
    """
    if profile not in PROFILE_TARGETS:
        raise ValueError("Невідомий канал глибокої черги")
    manifest_path, exported, total = export_deep_review_manifest(
        conn,
        profile,
        transcript_dir=transcript_dir,
        package_dir=package_dir,
        limit=min(20, max(0, int(limit))),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest.get("items") or []
    if not isinstance(items, list):
        raise ValueError("Невірний формат маніфесту NAS")

    max_downloads = max(0, min(20, int(max_downloads)))
    downloaded = 0
    attempted_downloads = 0
    errors: list[str] = []
    drafts: list[dict[str, Any]] = []
    client = None

    for item in items:
        if not isinstance(item, dict):
            continue
        video_id = str(item.get("video_id") or "")
        if not _VIDEO_ID.fullmatch(video_id):
            errors.append(f"Некоректний ID у deep-черзі: {video_id[:30]}")
            continue

        srt_path = transcript_dir / f"{video_id}.srt"
        if (
            not bool(item.get("transcript_ready"))
            and attempted_downloads < max_downloads
        ):
            available = int(quota_budget_status(conn).get("spendable", 0))
            if available >= CAPTION_TRANSCRIPT_COST:
                attempted_downloads += 1
                try:
                    if client is None:
                        client = client_factory(profile)
                        client.credentials()
                    track, srt = client.download_best_caption_srt(video_id)
                    if not str(srt or "").strip():
                        raise ValueError("Порожній SRT, не збережено")
                    transcript_dir.mkdir(parents=True, exist_ok=True)
                    staged = srt_path.with_suffix(".srt.tmp")
                    staged.write_text(str(srt), encoding="utf-8")
                    staged.replace(srt_path)
                    record_quota_units(
                        conn, CAPTION_TRANSCRIPT_COST, purpose="video"
                    )
                    downloaded += 1
                    meta = {
                        "video_id": video_id,
                        "channel_profile": profile,
                        "channel_id": PROFILE_TARGETS[profile],
                        "title": str(item.get("title") or ""),
                        "language": (track.get("snippet") or {}).get("language"),
                        "srt_path": str(srt_path),
                    }
                    (transcript_dir / f"{video_id}.json").write_text(
                        json.dumps(meta, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    item["transcript_ready"] = True
                    item["transcript_path"] = str(srt_path)
                    try:
                        uploader(PACKAGE_BRIDGE_URL, video_id, str(srt), meta)
                    except Exception:
                        # The local SRT remains usable if the optional
                        # LAN bridge is down; never re-download only for it.
                        pass
                except Exception as exc:
                    if "не знайдено доступних субтитрів" in str(exc):
                        # A missing-caption response still incurs the list read.
                        record_quota_units(conn, 50, purpose="video")
                    errors.append(f"{video_id}: {str(exc)[:200]}")

        # Offline drafts are optional. Missing packages do not block export.
        package_path = package_dir / f"{video_id}.json"
        try:
            if package_path.is_file():
                if package_path.stat().st_size > 2_000_000:
                    raise ValueError("SEO JSON перевищує 2 МБ")
                payload = json.loads(package_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("SEO пакет не є JSON-об'єктом")
                if str(payload.get("video_id") or video_id) != video_id:
                    raise ValueError("Невірний video_id у SEO пакеті")
                drafts.append({"video_id": video_id, "payload": payload})
        except Exception as exc:
            errors.append(f"{video_id}: {str(exc)[:200]}")

    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    staged_manifest = manifest_path.with_suffix(".json.tmp")
    staged_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    staged_manifest.replace(manifest_path)
    return {
        "profile": profile,
        "path": str(manifest_path),
        "exported": exported,
        "total": total,
        "downloaded": downloaded,
        "attempted_downloads": attempted_downloads,
        "drafts": drafts,
        "errors": errors,
    }
