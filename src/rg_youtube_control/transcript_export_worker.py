"""Thread-safe NAS subtitle export for RG YouTube Control.

This module contains no Qt widgets and never writes public YouTube metadata.
All NAS I/O, bridge calls, API calls and quota persistence belong to one worker
thread and its private SQLite connection.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .config import PROFILE_TARGETS
from .service import (
    CAPTION_TRANSCRIPT_COST,
    mark_quota_exhausted,
    quota_budget_status,
    record_quota_units,
)

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_MISSING_CAPTIONS_LIST_COST = 50


def _atomic_text(path: Path, text: str) -> None:
    """Never expose partially written SRT/JSON on a slow or unstable NAS."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def run_transcript_export(
    conn: sqlite3.Connection,
    *,
    profile: str,
    rows: list[dict[str, str]],
    target_dir: Path,
    client_factory: Callable[..., Any],
    uploader: Callable[..., Any],
    bridge_url: str,
    max_new: int = 20,
) -> dict[str, Any]:
    """Stage available transcripts and optionally download missing captions.

    This is a manual-only read operation; at most 20 videos without existing
    SRTs are allowed per request. Missing captions are counted conservatively
    as API reads. Never perform YouTube metadata writes.
    """
    if profile not in PROFILE_TARGETS:
        raise ValueError("Невідомий канал для експорту SRT")
    if not rows:
        return {"already": 0, "saved": 0, "failed": 0, "errors": [],
                "report_path": "", "items": [], "total": 0}

    validated = []
    for row in rows:
        video_id = str(row.get("video_id") or "")
        if not _VIDEO_ID.fullmatch(video_id):
            raise ValueError(f"Некоректний ID відео: {video_id[:24]}")
        validated.append({
            "video_id": video_id,
            "title": str(row.get("title") or ""),
            "scheduled_publish_at": str(row.get("scheduled_publish_at") or ""),
        })

    # All path lookups live here, never in the caller's Qt event loop.
    missing = [
        row for row in validated
        if not (target_dir / f"{row['video_id']}.srt").is_file()
    ]
    if len(missing) > max_new:
        raise ValueError(
            f"Потрібно отримати {len(missing)} SRT, ліміт за один пакет: "
            f"{max_new}. Жодного API-запиту не виконано."
        )

    client = None
    saved = 0
    already = 0
    errors: list[str] = []
    report_items: list[dict[str, Any]] = []
    for row in validated:
        video_id = row["video_id"]
        srt_path = target_dir / f"{video_id}.srt"
        meta_path = target_dir / f"{video_id}.json"
        downloaded = False
        try:
            if srt_path.is_file() and srt_path.stat().st_size:
                srt = srt_path.read_text(encoding="utf-8")
                already += 1
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if not isinstance(meta, dict):
                        meta = {}
                except (OSError, ValueError, TypeError):
                    meta = {}
            else:
                # Reserve the project's protected video/comment budget.
                if int(quota_budget_status(conn)["spendable"]) < CAPTION_TRANSCRIPT_COST:
                    raise RuntimeError(
                        "Недостатньо квоти вище захищеного резерву "
                        "для отримання транскрипту."
                    )
                if client is None:
                    client = client_factory(profile=profile)
                try:
                    track, srt = client.download_best_caption_srt(video_id)
                except Exception as exc:
                    if "не знайдено доступних субтитрів" in str(exc):
                        record_quota_units(
                            conn, _MISSING_CAPTIONS_LIST_COST, purpose="video",
                        )
                    elif "quotaexceeded" in str(exc).casefold():
                        mark_quota_exhausted(conn)
                    raise
                if not str(srt or "").strip():
                    raise ValueError("Порожній SRT, не збережено")
                record_quota_units(conn, CAPTION_TRANSCRIPT_COST, purpose="video")
                meta = {
                    "language": (track.get("snippet") or {}).get("language"),
                    "name": (track.get("snippet") or {}).get("name"),
                    "track_kind": (track.get("snippet") or {}).get("trackKind"),
                    "status": (track.get("snippet") or {}).get("status"),
                }
                _atomic_text(srt_path, str(srt))
                downloaded = True
                saved += 1

            meta.update({
                "video_id": video_id,
                "channel_profile": profile,
                "channel_id": PROFILE_TARGETS[profile],
                "title": row["title"],
                "srt_path": str(srt_path),
            })
            _atomic_text(
                meta_path, json.dumps(meta, ensure_ascii=False, indent=2),
            )
            try:
                uploader(bridge_url, video_id, str(srt), meta)
            except Exception:
                # Bridge is optional and must not invalidate a complete SRT.
                pass
            report_items.append({
                **row, "ok": True, "downloaded": downloaded,
                "path": str(srt_path), "error": "",
            })
        except Exception as exc:
            reason = str(exc)[:500]
            errors.append(f"{video_id}: {reason}")
            report_items.append({
                **row, "ok": False, "downloaded": False,
                "path": "", "error": reason,
            })
            # Stop on an authoritative or local quota block; repeated API
            # attempts would only waste time and risk throttling.
            if "quotaexceeded" in reason.casefold() or "захищеного резерву" in reason:
                break

    report_path = target_dir / f"_last_transcript_report_{profile}.json"
    report_error = ""
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "channel_id": PROFILE_TARGETS[profile],
        "total_scheduled": len(validated),
        "already_existing": already,
        "downloaded": saved,
        "failed": len(errors),
        "items": report_items,
    }
    try:
        _atomic_text(
            report_path, json.dumps(payload, ensure_ascii=False, indent=2),
        )
    except Exception as exc:
        report_error = str(exc)[:500]

    return {
        "already": already,
        "saved": saved,
        "failed": len(errors),
        "errors": errors,
        "report_path": str(report_path) if not report_error else "",
        "report_error": report_error,
        "items": report_items,
        "total": len(validated),
    }
