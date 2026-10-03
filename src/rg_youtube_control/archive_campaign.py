from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .db import deep_review_state_map, set_deep_review_state
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
        if (transcript_dir / f"{video_id}.srt").exists():
            transcripts += 1
        draft_status = str(row["draft_status"] or "")
        if draft_status == "ready":
            ready_packages += 1
        elif draft_status == "applied":
            applied_packages += 1

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

    items: list[dict[str, Any]] = []
    for item in candidates:
        video_id = str(item["video_id"])
        transcript_path = transcript_dir / f"{video_id}.srt"
        package_path = package_dir / f"{video_id}.json"
        set_deep_review_state(
            conn,
            video_id=video_id,
            profile=profile,
            status="queued",
            note="deep_review_manifest",
        )
        items.append(
            {
                **item,
                "transcript_ready": transcript_path.exists(),
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
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path, len(items), total
