from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .db import (
    deep_review_state_map,
    get_setting,
    set_deep_review_state,
    set_setting,
)
from .optimization import (
    archive_potential_score,
    is_safe_archive_candidate,
    needs_deep_review,
)


def _issues(raw: str | None) -> list[str]:
    try:
        return list(json.loads(raw or "{}").get("issues", []))
    except Exception:
        return []


def load_campaign_checkpoint(conn: sqlite3.Connection) -> dict[str, Any]:
    raw = get_setting(conn, "archive_campaign_checkpoint", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def save_campaign_checkpoint(
    conn: sqlite3.Connection,
    *,
    phase: str,
    target: str,
    status: str = "ready",
    note: str = "",
) -> dict[str, Any]:
    payload = {
        "phase": str(phase or ""),
        "target": str(target or ""),
        "status": str(status or "ready"),
        "note": str(note or ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    set_setting(
        conn,
        "archive_campaign_checkpoint",
        json.dumps(payload, ensure_ascii=False),
    )
    return payload


def reconcile_campaign_checkpoint(
    conn: sqlite3.Connection,
    stats: dict[str, dict[str, int]],
) -> tuple[dict[str, Any], bool]:
    previous = load_campaign_checkpoint(conn)
    phase, target = next_campaign_phase(stats)
    interrupted = previous.get("status") == "running"
    checkpoint = save_campaign_checkpoint(
        conn,
        phase=phase,
        target=target,
        status="complete" if phase == "complete" else "ready",
        note="recovered_after_interruption" if interrupted else "",
    )
    return checkpoint, interrupted


def deep_review_candidates(
    conn: sqlite3.Connection,
    profile: str,
    *,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    rows = conn.execute(
        """SELECT v.video_id,v.title,v.views,v.audit_json,
                  a.analytics_views,a.impressions,a.ctr_percent,
                  d.status AS draft_status
           FROM videos v
           LEFT JOIN video_analytics_cache a
             ON a.video_id=v.video_id AND a.profile=v.profile
           LEFT JOIN optimization_drafts d
             ON d.video_id=v.video_id
           WHERE v.profile=?
             AND v.privacy_status='public'
             AND v.scheduled_publish_at IS NULL""",
        (profile,),
    ).fetchall()

    state = deep_review_state_map(conn, profile)
    ctr_values = [
        float(row["ctr_percent"] or 0)
        for row in rows
        if int(row["impressions"] or 0) >= 1000
        and float(row["ctr_percent"] or 0) > 0
    ]
    channel_median_ctr = median(ctr_values) if ctr_values else 0.0

    ranked: list[tuple[int, int, int, int, dict[str, Any]]] = []
    for row in rows:
        issues = _issues(row["audit_json"])
        if not needs_deep_review(issues):
            continue
        video_id = str(row["video_id"])
        if state.get(video_id) in {"applied", "skipped"}:
            continue

        potential = archive_potential_score(
            lifetime_views=int(row["views"] or 0),
            analytics_views=int(row["analytics_views"] or 0),
            impressions=int(row["impressions"] or 0),
            ctr_percent=float(row["ctr_percent"] or 0),
            median_ctr_percent=float(channel_median_ctr),
            issues=issues,
        )
        item = {
            "video_id": video_id,
            "title": str(row["title"] or ""),
            "views": int(row["views"] or 0),
            "issues": issues,
            "potential": potential,
            "draft_status": str(row["draft_status"] or ""),
        }
        ranked.append(
            (
                potential,
                int(row["impressions"] or 0),
                int(row["analytics_views"] or 0),
                int(row["views"] or 0),
                item,
            )
        )

    ranked.sort(reverse=True, key=lambda item: item[:4])
    items = [item[-1] for item in ranked]
    return items[: max(0, int(limit))], len(items)


def archive_profile_stats(
    conn: sqlite3.Connection,
    profile: str,
    *,
    transcript_dir: Path,
) -> dict[str, int]:
    rows = conn.execute(
        """SELECT v.video_id,v.audit_json,d.status AS draft_status
           FROM videos v
           LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
           WHERE v.profile=?
             AND v.privacy_status='public'
             AND v.scheduled_publish_at IS NULL""",
        (profile,),
    ).fetchall()

    state = deep_review_state_map(conn, profile)
    # Windows UNC drives can take seconds on each remote Path.exists().
    # Enumerate once: a 1,800-video archive should cause one directory read,
    # not 1,800 round trips to Synology NAS.
    transcript_names: set[str] = set()
    try:
        with os.scandir(transcript_dir) as entries:
            transcript_names = {
                entry.name.casefold()
                for entry in entries
                if entry.name.casefold().endswith(".srt")
            }
    except (OSError, ValueError):
        # No network share available: do not block/abort all local statistics.
        transcript_names = set()
    safe_remaining = 0
    deep_remaining = 0
    transcripts = 0
    ready_packages = 0
    applied_packages = 0

    for row in rows:
        video_id = str(row["video_id"])
        issues = _issues(row["audit_json"])
        if is_safe_archive_candidate(issues):
            safe_remaining += 1
        if (
            needs_deep_review(issues)
            and state.get(video_id) not in {"applied", "skipped"}
        ):
            deep_remaining += 1
        if f"{video_id}.srt".casefold() in transcript_names:
            transcripts += 1
        draft_status = str(row["draft_status"] or "")
        deep_status = state.get(video_id)
        if deep_status in {"queued", "review"} and draft_status == "ready":
            ready_packages += 1

    applied_packages = sum(
        1 for value in state.values() if value == "applied"
    )
    skipped_deep = sum(1 for value in state.values() if value == "skipped")
    return {
        "archive_total": len(rows),
        "safe_remaining": safe_remaining,
        "deep_remaining": deep_remaining,
        "transcripts": transcripts,
        "ready_packages": ready_packages,
        "applied_packages": applied_packages,
        "skipped_deep": skipped_deep,
    }


def next_campaign_phase(stats: dict[str, dict[str, int]]) -> tuple[str, str]:
    if stats.get("main", {}).get("safe_remaining", 0) > 0:
        return "safe", "main"
    if stats.get("live", {}).get("safe_remaining", 0) > 0:
        return "safe", "live"
    if stats.get("main", {}).get("deep_remaining", 0) > 0:
        return "deep", "main"
    if stats.get("live", {}).get("deep_remaining", 0) > 0:
        return "deep", "live"
    return "complete", ""


def export_deep_review_manifest(
    conn: sqlite3.Connection,
    profile: str,
    *,
    transcript_dir: Path,
    package_dir: Path,
    limit: int = 20,
) -> tuple[Path, int, int]:
    candidates, total = deep_review_candidates(conn, profile, limit=limit)
    package_dir.mkdir(parents=True, exist_ok=True)
    # A single remote listing beats a separate network stat for each item.
    try:
        with os.scandir(transcript_dir) as entries:
            available_srt = {
                item.name.casefold() for item in entries
                if item.name.casefold().endswith(".srt")
            }
    except (OSError, ValueError):
        available_srt = set()

    items: list[dict[str, Any]] = []
    for item in candidates:
        video_id = str(item["video_id"])
        transcript_path = transcript_dir / f"{video_id}.srt"
        package_path = package_dir / f"{video_id}.json"
        items.append(
            {
                **item,
                "transcript_ready": f"{video_id}.srt".casefold() in available_srt,
                "transcript_path": str(transcript_path),
                "package_path": str(package_path),
                "workflow": {
                    "status": "draft",
                    "preview_required": True,
                    "auto_apply": False,
                    "allowed_review_fields": [
                        "new_title",
                        "description",
                        "chapters",
                        "tags",
                        "title_variants",
                    ],
                },
            }
        )

    payload = {
        "schema_version": 1,
        "profile": profile,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "total_pending": total,
        "instructions": (
            "Підготувати глибоку оптимізацію за змістом відео/транскрипту. "
            "Кожен пакет лишається чернеткою до ручного перегляду в програмі. "
            "Не змінювати thumbnail. Не застосовувати автоматично."
        ),
        "items": items,
    }
    path = package_dir / f"deep_review_{profile}.json"
    staged = path.with_suffix(".json.tmp")
    staged.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Atomic replacement prevents readers from seeing a half-written manifest.
    staged.replace(path)
    # Commit queue state only after the manifest is safely present on storage.
    # Exporting again must not demote an operator-reviewed draft back to queued.
    previous = deep_review_state_map(conn, profile)
    for item in items:
        if previous.get(str(item["video_id"])) == "review":
            continue
        set_deep_review_state(
            conn,
            video_id=str(item["video_id"]),
            profile=profile,
            status="queued",
            note="deep_review_manifest",
        )
    return path, len(items), total
