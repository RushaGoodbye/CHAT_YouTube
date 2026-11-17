"""Explicit origin policy for SEO drafts. Fail closed on old AI packages.

This module only classifies stored metadata and never infers whether vidIQ
was actually used. Attribution is declared by the human editor.
"""
from __future__ import annotations

METADATA_ONLY_PREFIX = "safe-metadata"
VERIFIED_EDITOR_SOURCES = {
    "vidiq-reviewed-srt-v1",
    "manual-reviewed-srt-v1",
}

def is_metadata_only(generation: str, quality_state: str) -> bool:
    return (str(generation or "").startswith(METADATA_ONLY_PREFIX)
            and str(quality_state or "") == "safe_metadata")

def is_unverified_legacy(generation: str, quality_state: str = "") -> bool:
    return (not is_metadata_only(generation, quality_state)
            and str(generation or "").strip() not in VERIFIED_EDITOR_SOURCES)

def source_label(generation: str, quality_state: str = "") -> str:
    value = str(generation or "").strip()
    if is_metadata_only(value, quality_state):
        return "Безпечне виправлення метаданих"
    if value == "vidiq-reviewed-srt-v1":
        return "vidIQ · перенесено й перевірено вручну"
    if value == "manual-reviewed-srt-v1":
        return "Редактор · перевірено за SRT"
    if not value or value == "legacy":
        return "Старий SEO-пакет · джерело невідоме"
    return "Старий SEO-пакет · непідтверджений (" + value[:64] + ")"
