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
        if not (
            (target_dir / f"{row['video_id']}.srt").is_file()
            and (target_dir / f"{row['video_id']}.srt").stat().st_size > 0
        )
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


def run_deep_manifest_transcript_export(
    conn: sqlite3.Connection,
    *,
    profile: str,
    manifest_path: Path,
    target_dir: Path,
    client_factory: Callable[..., Any],
    uploader: Callable[..., Any],
    bridge_url: str,
    max_new: int = 20,
) -> dict[str, Any]:
    """Read an existing deep-review queue and export missing SRTs off Qt.

    Limits new downloads to both the explicit batch cap and the *current*
    protected quota budget. Existing SRTs are left untouched. The manifest
    is updated atomically only if it has not changed since reading.
    """
    if profile not in PROFILE_TARGETS:
        raise ValueError("Невідомий профіль глибокої черги.")
    if max_new < 1 or max_new > 20:
        raise ValueError("Глибока черга допускає максимум 20 нових SRT.")

    # Manifest and every UNC stat happen only in this background worker.
    original = manifest_path.read_bytes()
    payload = json.loads(original.decode("utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("Некоректний маніфест глибокої черги.")
    pending: list[dict[str, str]] = []
    seen: set[str] = set()
    existing = 0
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        video_id = str(item.get("video_id") or "")
        if not _VIDEO_ID.fullmatch(video_id) or video_id in seen:
            continue
        seen.add(video_id)
        video = conn.execute(
            "SELECT profile,title FROM videos WHERE video_id=?", (video_id,),
        ).fetchone()
        if video is None or str(video["profile"]) != profile:
            continue
        path = target_dir / f"{video_id}.srt"
        if path.is_file() and path.stat().st_size > 0:
            existing += 1
            continue
        pending.append({
            "video_id": video_id,
            "title": str(video["title"] or ""),
            "scheduled_publish_at": "",
        })

    if not pending:
        return {
            "pending": 0, "existing": existing, "saved": 0,
            "failed": 0, "errors": [], "manifest_updated": False,
            "quota_blocked": False,
        }

    capacity = min(
        max_new,
        max(0, int(quota_budget_status(conn)["spendable"])
            // CAPTION_TRANSCRIPT_COST),
    )
    if capacity <= 0:
        return {
            "pending": len(pending), "existing": existing, "saved": 0,
            "failed": 0, "errors": [], "manifest_updated": False,
            "quota_blocked": True,
        }

    result = run_transcript_export(
        conn,
        profile=profile,
        rows=pending[:capacity],
        target_dir=target_dir,
        client_factory=client_factory,
        uploader=uploader,
        bridge_url=bridge_url,
        max_new=capacity,
    )
    good = {
        str(item["video_id"]): str(item["path"])
        for item in result.get("items", [])
        if item.get("ok") and item.get("path")
    }
    # Never erase a concurrent operator/agent change to the manifest.
    manifest_updated = False
    if good and manifest_path.read_bytes() == original:
        for item in payload["items"]:
            if not isinstance(item, dict):
                continue
            path = good.get(str(item.get("video_id") or ""))
            if path:
                item["transcript_ready"] = True
                item["transcript_path"] = path
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_text(
            manifest_path, json.dumps(payload, ensure_ascii=False, indent=2),
        )
        manifest_updated = True

    return {
        "pending": len(pending),
        "existing": existing,
        "saved": int(result.get("saved") or 0),
        "failed": int(result.get("failed") or 0),
        "errors": list(result.get("errors") or []),
        "manifest_updated": manifest_updated,
        "quota_blocked": False,
    }
