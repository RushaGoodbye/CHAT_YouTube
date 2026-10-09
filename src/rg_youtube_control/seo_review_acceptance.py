"""Fail-closed manual acceptance of a fully evidenced local SEO draft.

A click alone never overrides semantic review. A trusted local timeline proof
must still match the video, and all its grounded topics must appear in the
draft description. No YouTube API and no source changes.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .seo_quality_gate import review_seo_package

SOURCE_GENERATION = "local-seo-evidence-0.7.9"


def load_local_evidence_report(data_dir: str | Path, video_id: str) -> dict[str, Any] | None:
    video_id = str(video_id or "")
    # YouTube IDs cannot contain a path separator. Never follow user-provided
    # path fragments or load evidence for a different video.
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None
    path = Path(data_dir) / "seo_evidence" / f"{video_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or payload.get("video_id") != video_id:
        return None
    return payload


def reviewed_seo_acceptance_issues(
    *,
    generation: str,
    video_id: str,
    title: str,
    description: str,
    variants: list[str],
    data_dir: str | Path,
) -> list[str]:
    """Empty list means evidence/AB content is eligible for *manual* approval.

    Additional YouTube metadata validation is required by the caller. This
    never approves, saves, posts or invokes a YouTube operation.
    """
    if generation != SOURCE_GENERATION:
        return ["Непідтверджене походження SEO-пакета."]
    cleaned = [str(item or "").strip() for item in variants]
    if len(cleaned) != 3 or len({x.casefold() for x in cleaned}) != 3:
        return ["Потрібні три різні A/B-назви."]
    report = load_local_evidence_report(data_dir, video_id)
    if not report:
        return ["Збережений доказовий звіт відео відсутній або не збігається."]
    return review_seo_package(
        title=str(title or ""),
        description=str(description or ""),
        variants=cleaned,
        evidence_report=report,
    )
