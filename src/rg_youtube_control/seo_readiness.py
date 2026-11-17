"""Publication readiness is NOT the same as a technical audit score.

No YouTube requests, no filesystem writes, no Qt dependency.
The original technical metadata-only path is intentionally preserved.
"""
from __future__ import annotations
import json
from .dialogue_seo import ab_title_issues
from .seo_origin import is_metadata_only, is_unverified_legacy


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
    # Scheduled streams and safe description/tag-only optimization do not
    # replace the video title and therefore do not require A/B titles.
    if is_metadata_only(generation, quality_state):
        return not reasons, tuple(reasons)
    # A legacy AI or unlabelled manual draft is not publishable merely
    # because it was previously saved with status=ready and quality=safe.
    # Scheduled videos are not exempt from source provenance.
    if is_unverified_legacy(generation, quality_state):
        reasons.append(
            "Старий SEO-пакет без підтвердженого походження. "
            "Повторно звірте з SRT у редакторі."
        )
    if quality_state != "editor_approved":
        reasons.append("SEO не підтверджено редактором; залишити чернеткою.")
    # Scheduled streams do not need A/B title alternatives. They still
    # require explicit source and editorial approval for full SEO changes.
    if scheduled:
        return not reasons, tuple(reasons)
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


def persisted_quality_state(
    *,
    status: str,
    original_generation: str,
    original_quality_state: str,
    selected_generation: str,
    confirmed_srt: bool,
    technical_quality: str,
) -> str:
    """Persist proof of review, never upgrade a draft by status alone.

    The editor explicitly checks the complete SRT and chooses a verified
    provenance before full SEO can be marked editor_approved.
    """
    from .seo_origin import VERIFIED_EDITOR_SOURCES

    if status != "ready" or technical_quality != "safe":
        return "review"
    if is_metadata_only(original_generation, original_quality_state):
        return "safe_metadata"
    if selected_generation in VERIFIED_EDITOR_SOURCES and confirmed_srt:
        return "editor_approved"
    return "review"
