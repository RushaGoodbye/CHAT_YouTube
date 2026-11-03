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
    min_coverage: float = 0.80,
    min_windows: int = 3,
) -> dict[str, Any]:
    """Fail closed on clearly incompatible caption content.

    Compare across multiple timeline windows and allow slightly different ASR
    tokenization or overlapping caption segments. This is never approval.
    """
    if not primary or not reference:
        return {"status": "NEEDS_REVIEW", "reason": "INDEPENDENT_CAPTIONS_UNAVAILABLE",
                "publication_allowed": False}
    # A translated transcript may use an entirely different writing system.
    # Do not classify that as a source conflict without comparable-language
    # evidence. Different-language subtitles still require editorial review.
    def script_fraction(rows: list[dict[str, Any]]) -> tuple[float, float]:
        chars = [c for row in rows for c in str(row.get("text") or "") if c.isalpha()]
        if not chars:
            return 0.0, 0.0
        return (
            sum(0x0400 <= ord(c) <= 0x052F for c in chars) / len(chars),
            sum(("A" <= c <= "Z") or ("a" <= c <= "z") for c in chars) / len(chars),
        )
    primary_cyr, primary_lat = script_fraction(primary)
    reference_cyr, reference_lat = script_fraction(reference)
    if ((primary_cyr > 0.80 and reference_lat > 0.80) or
            (primary_lat > 0.80 and reference_cyr > 0.80)):
        return {"status": "NEEDS_REVIEW", "reason": "CAPTION_LANGUAGE_MISMATCH",
                "publication_allowed": False}
    try:
        max_end = max(
            max(float(r["start"]) + float(r["duration"]) for r in primary),
            max(float(r["start"]) + float(r["duration"]) for r in reference),
        )
        if max_end <= 0:
            raise ValueError("INVALID_CAPTION_DURATION")
        window_count = max(min_windows, min(8, round(max_end / 160)))
        # If both transports expose largely the same cue text, demand that
        # those captions also occur in the same part of the timeline.
        def all_cues(rows: list[dict[str, Any]]) -> set[str]:
            return {" ".join(_words(str(row["text"]))) for row in rows if row.get("text")}
        p_cues = all_cues(primary)
        r_cues = all_cues(reference)
        global_exact = len(p_cues & r_cues) / max(1, min(len(p_cues), len(r_cues)))
        require_timeline_agreement = global_exact >= 0.60
        if require_timeline_agreement:
            def cue_times(rows: list[dict[str, Any]]) -> dict[str, float]:
                return {" ".join(_words(str(row["text"]))): float(row["start"])
                        for row in rows if row.get("text")}
            p_times = cue_times(primary)
            r_times = cue_times(reference)
            shifts = sorted(abs(p_times[k] - r_times[k]) for k in p_times.keys() & r_times.keys())
            if len(shifts) >= 8 and shifts[len(shifts)//2] > 15:
                return {"status": "BLOCKED_SOURCE", "reason": "CAPTION_TIMELINE_CONFLICT",
                        "publication_allowed": False}
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
            # Exact cue correspondence is the strongest transport signal.
            def cue_texts(rows: list[dict[str, Any]]) -> set[str]:
                return {" ".join(_words(str(r["text"]))) for r in rows
                        if lo <= float(r["start"]) < hi and r.get("text")}
            a_cues = cue_texts(primary)
            b_cues = cue_texts(reference)
            exact = len(a_cues & b_cues) / max(1, min(len(a_cues), len(b_cues)))
            # A high lexical match can corroborate different segmentation, but
            # shared filler must not hide different subjects.
            ac, bc = Counter(a), Counter(b)
            overlap = sum((ac & bc).values()) / min(len(a), len(b))
            a_content = {w for w in a if len(w) >= 5 and not w.isdecimal()}
            b_content = {w for w in b if len(w) >= 5 and not w.isdecimal()}
            unique_match = (len(a_content & b_content) /
                            max(1, min(len(a_content), len(b_content))))
            score = exact if require_timeline_agreement else max(exact, min(overlap, unique_match))
            outcomes.append(score)
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
