"""Publication readiness is NOT the same as a technical audit score.

No YouTube requests, no filesystem writes, no Qt dependency.
The original technical metadata-only path is intentionally preserved.
"""
from __future__ import annotations
import json
from .dialogue_seo import ab_title_issues


def ready_for_youtube(
    *,
    status: str,
    generation: str,
    quality_state: str,
    variants: list[str] | str | None,
    scheduled: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    """Fail closed for legacy or unreviewed full SEO packages."""
    if status != "ready":
        return False, ("Пакет не має статусу готовності.",)
    generation = (generation or "").strip()
    quality_state = (quality_state or "").strip()
    # Scheduled streams and safe description/tag-only optimization do not
    # replace the video title and therefore do not require A/B titles.
    if scheduled:
        return True, ()
    if generation.startswith("safe-metadata") and quality_state == "safe_metadata":
        return True, ()
    if quality_state not in {"safe", "editor_approved"}:
        return False, ("SEO не підтверджено редактором; залишити чернеткою.",)
    if isinstance(variants, str):
        try:
            parsed = json.loads(variants)
        except (ValueError, TypeError):
            parsed = []
        variants = parsed
    if not isinstance(variants, list):
        variants = []
    names = [str(x).strip() for x in variants if str(x).strip()]
    if len(names) != 3:
        return False, ("Для повного SEO потрібні три A/B назви.",)
    issues = ab_title_issues(names)
    if issues:
        return False, tuple(issues)
    return True, ()


def exact_video_id_search(search_text: str) -> str:
    """Only actual YouTube 11-character IDs bypass saved queue filters."""
    import re
    text = str(search_text or "").strip()
    return text if re.fullmatch(r"[A-Za-z0-9_-]{11}", text) else ""
