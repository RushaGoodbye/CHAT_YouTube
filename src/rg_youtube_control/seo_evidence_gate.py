"""Fail-closed evidence checks for proposed SEO drafts.

Pure functions only. No network, database access, or publishing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_QUOTES = re.compile(r"[«“\"]([^»”\"]{5,})[»”\"]")
_WORD = re.compile(r"[\wіїєґё]+", re.UNICODE)


def _norm(value: str) -> str:
    return " ".join(_WORD.findall(str(value).casefold()))


@dataclass(frozen=True)
class EvidenceDecision:
    approved_for_review: bool
    issues: tuple[str, ...]


def check_seo_evidence(
    *,
    video_id: str | None,
    titles: Sequence[str],
    description: str,
    transcript: str,
    transcript_video_id: str | None,
    verified_video_mapping: bool = False,
    max_title_length: int = 100,
    expected_title_count: int = 3,
) -> EvidenceDecision:
    """Validate a draft for EDITOR REVIEW, never for publication.

    A positive result does NOT prove factual correctness or license edits.
    The transcript must belong to the mapped video; a dialogue/stream ID
    is not a substitute for a YouTube video ID.
    """
    problems: list[str] = []
    if not video_id or not _VIDEO_ID.fullmatch(video_id):
        problems.append("VIDEO_ID_MISSING_OR_INVALID")
    if not verified_video_mapping or transcript_video_id != video_id:
        problems.append("UNVERIFIED_VIDEO_MAPPING")
    if not transcript or len(_norm(transcript)) < 200:
        problems.append("INSUFFICIENT_TRANSCRIPT")
    if len(titles) != expected_title_count:
        problems.append("INVALID_TITLE_COUNT")
    cleaned = [_norm(t) for t in titles]
    if len(set(cleaned)) != len(cleaned) or any(not t for t in cleaned):
        problems.append("DUPLICATE_OR_EMPTY_TITLE")
    if any(len(t) > max_title_length for t in titles):
        problems.append("TITLE_TOO_LONG")
    if len(description.strip()) < 120:
        problems.append("DESCRIPTION_TOO_SHORT")
    source = _norm(transcript)
    for title in titles:
        for quote in _QUOTES.findall(title):
            if _norm(quote) not in source:
                problems.append("UNVERIFIED_DIRECT_QUOTE")
                break
    return EvidenceDecision(not problems, tuple(dict.fromkeys(problems)))


def as_review_record(decision: EvidenceDecision) -> Mapping[str, object]:
    """No output of this module is publish-ready, even when review passes."""
    return {
        "status": "REVIEW_REQUIRED",
        "eligible_for_editor_review": decision.approved_for_review,
        "eligible_for_youtube_write": False,
        "issues": list(decision.issues),
    }
