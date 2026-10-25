"""Compare user-confirmed untimed SEO text with exact-ID timed captions.

Never treat an SRT filename or a shared named subject as proof of identity.
A timed candidate is an *offer* for explicit operator choice, not an automatic
replacement for an already confirmed text. Neither source is modified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .seo_source_alignment import check_title_against_transcript


@dataclass(frozen=True)
class TimedComparison:
    offer_timed: bool
    reason: str
    shared_stems: int = 0
    lexical_agreement: float = 0.0
    timed_cues: int = 0
    last_second: float = 0.0


def _source_text(rows: list[dict[str, Any]]) -> str:
    return " ".join(str(row.get("text") or "") for row in rows if isinstance(row, dict))


def _content_stems(text: str) -> set[str]:
    # RU/UA speech-recognition variation; trim inflections conservatively.
    folded = str(text).casefold().translate(str.maketrans({
        "ё": "е", "і": "и", "ї": "и", "є": "е", "ґ": "г",
    }))
    return {
        word[:6] for word in re.findall(r"[a-zа-я0-9]{6,}", folded)
        if not word.isdigit() and len(word) >= 6
    }



_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def published_duration_seconds(value: object) -> float:
    """Normalize synchronized YouTube ISO-8601 or legacy duration formats."""
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        seconds = float(raw)
        if 0 <= seconds < 1e9:
            return seconds
    except (TypeError, ValueError):
        pass
    if re.fullmatch(r"\d{1,4}:[0-5]?\d(?::[0-5]?\d)?", raw):
        seconds = 0
        for part in raw.split(":"):
            seconds = seconds * 60 + int(part)
        return float(seconds)
    match = _DURATION_RE.fullmatch(raw)
    if match:
        values = {key: float(amount or 0) for key, amount in match.groupdict().items()}
        return (values["days"] * 86400 + values["hours"] * 3600
                + values["minutes"] * 60 + values["seconds"])
    return 0.0


def compare_timed_to_verified(
    original_title: str,
    verified_untimed: list[dict[str, Any]],
    candidate_timed: list[dict[str, Any]],
    *,
    published_duration: float = 0,
) -> TimedComparison:
    """Offer alternative only when strong independent evidence agrees.

    The caller must still ask for explicit confirmation and preserve the
    original verified text. A mismatch fails closed to the verified source.
    """
    timed_cues = len(candidate_timed)
    if not verified_untimed or timed_cues < 10:
        return TimedComparison(False, "missing_source", timed_cues=timed_cues)
    if not all(isinstance(row, dict) for row in candidate_timed):
        return TimedComparison(False, "invalid_cue", timed_cues=timed_cues)
    try:
        starts = [float(row.get("start") or 0) for row in candidate_timed]
        last_second = max(
            float(row.get("start") or 0) + float(row.get("duration") or 0)
            for row in candidate_timed
        )
    except (TypeError, ValueError):
        return TimedComparison(False, "invalid_timing", timed_cues=timed_cues)
    if any(start < 0 for start in starts) or last_second < 90:
        return TimedComparison(False, "incomplete_timing", timed_cues=timed_cues)
    if published_duration > 0 and last_second < published_duration * 0.75:
        return TimedComparison(False, "short_coverage", timed_cues=timed_cues,
                               last_second=last_second)

    verified_text = _source_text(verified_untimed)
    timed_text = _source_text(candidate_timed)
    if (check_title_against_transcript(original_title, verified_text).missing
            or check_title_against_transcript(original_title, timed_text).missing):
        return TimedComparison(False, "subject_mismatch", timed_cues=timed_cues,
                               last_second=last_second)
    a, b = _content_stems(verified_text), _content_stems(timed_text)
    overlap = a & b
    # Coefficient over smaller vocabulary handles an abridged but faithful
    # ASR subtitle track. Name-only similarity cannot pass this threshold.
    agreement = len(overlap) / max(1, min(len(a), len(b)))
    if min(len(a), len(b)) < 35 or len(overlap) < 25 or agreement < 0.46:
        return TimedComparison(False, "content_mismatch", len(overlap),
                               round(agreement, 3), timed_cues, last_second)
    return TimedComparison(True, "verified_candidate", len(overlap),
                           round(agreement, 3), timed_cues, last_second)
