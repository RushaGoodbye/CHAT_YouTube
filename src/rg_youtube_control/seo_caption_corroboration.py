"""Compare two independently fetched caption representations for one video.

Independent *transport*, not independent speech-to-text verification. A match
corroborates caption retrieval; it does not prove the audio or spoken facts.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", str(text or "").casefold(), flags=re.UNICODE)


def compare_caption_rows(
    primary: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    *,
    min_tokens: int = 70,
    min_coverage: float = 0.58,
    min_windows: int = 3,
) -> dict[str, Any]:
    """Fail closed on clearly incompatible caption content.

    Compare across multiple timeline windows and allow slightly different ASR
    tokenization or overlapping caption segments. This is never approval.
    """
    if not primary or not reference:
        return {"status": "NEEDS_REVIEW", "reason": "INDEPENDENT_CAPTIONS_UNAVAILABLE",
                "publication_allowed": False}
    try:
        max_end = max(
            max(float(r["start"]) + float(r["duration"]) for r in primary),
            max(float(r["start"]) + float(r["duration"]) for r in reference),
        )
        if max_end <= 0:
            raise ValueError("INVALID_CAPTION_DURATION")
        window_count = max(min_windows, min(8, round(max_end / 160)))
        outcomes: list[float] = []
        total_tokens = 0
        for window in range(window_count):
            lo = max_end * window / window_count
            hi = max_end * (window + 1) / window_count
            def tokens(rows: list[dict[str, Any]]) -> list[str]:
                selected = []
                for row in rows:
                    start = float(row["start"])
                    if lo <= start < hi:
                        selected.extend(_words(str(row["text"])))
                return selected
            a = tokens(primary)
            b = tokens(reference)
            total_tokens += min(len(a), len(b))
            if min(len(a), len(b)) < 8:
                continue
            ac, bc = Counter(a), Counter(b)
            overlap = sum((ac & bc).values())
            outcomes.append(overlap / min(len(a), len(b)))
        if total_tokens < min_tokens or len(outcomes) < min_windows:
            return {"status": "NEEDS_REVIEW", "reason": "INSUFFICIENT_COMPARISON_EVIDENCE",
                    "matched_windows": len(outcomes), "publication_allowed": False}
        matched = sum(score >= min_coverage for score in outcomes)
        coverage = matched / len(outcomes)
        if coverage < 0.60:
            return {"status": "BLOCKED_SOURCE", "reason": "CAPTION_CONTENT_CONFLICT",
                    "matched_windows": matched, "compared_windows": len(outcomes),
                    "publication_allowed": False}
        return {"status": "NEEDS_REVIEW", "reason": "CAPTION_TRANSPORTS_CORROBORATE",
                "matched_windows": matched, "compared_windows": len(outcomes),
                "publication_allowed": False}
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {"status": "BLOCKED_SOURCE", "reason": "INVALID_COMPARISON_INPUT",
                "detail": type(exc).__name__, "publication_allowed": False}
