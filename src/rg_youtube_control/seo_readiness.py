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
    # Collect *all* editorial failures, even while the editor displays
    # "Чернетка". An early return for status hid the actual A/B problem.
    reasons: list[str] = []
    if status != "ready":
        reasons.append("Пакет не має статусу готовності.")
    generation = (generation or "").strip()
    quality_state = (quality_state or "").strip()
    # Only the explicit safe-metadata path may bypass editorial A/B titles.
    # A scheduled video can still receive a full videos.update (including a
    # title change); scheduled=True alone is NOT proof of approval.
    if (
        generation.startswith("safe-metadata")
        and quality_state == "safe_metadata"
    ):
        return not reasons, tuple(reasons)
    if quality_state not in {"safe", "editor_approved"}:
        reasons.append("SEO не підтверджено редактором; залишити чернеткою.")
    if isinstance(variants, str):
        try:
            variants = json.loads(variants)
        except (ValueError, TypeError):
            variants = []
    if not isinstance(variants, list):
        variants = []
    names = [str(x).strip() for x in variants if isinstance(x, str) and x.strip()]
    if len(names) != 3:
        reasons.append("Для повного SEO потрібні три A/B назви.")
    else:
        reasons.extend(ab_title_issues(names))
    return not reasons, tuple(reasons)


def exact_video_id_search(search_text: str) -> str:
    """Only actual YouTube 11-character IDs bypass saved queue filters."""
    import re
    text = str(search_text or "").strip()
    return text if re.fullmatch(r"[A-Za-z0-9_-]{11}", text) else ""
