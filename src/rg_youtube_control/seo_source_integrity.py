"""Universal, fail-closed preflight for associating captions with a YouTube video.

This module checks provenance and structural integrity. Keyword evidence is only
a supporting signal: it cannot prove that two videos contain the same dialogue.
No YouTube changes, model calls, or network requests are performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class CaptionCue:
    start_s: float
    end_s: float
    text: str


def parse_srt(content: str) -> list[CaptionCue]:
    """Parse basic SRT time ranges; fail instead of silently dropping bad cues."""
    blocks = re.split(r"\r?\n\s*\r?\n", str(content or "").strip())
    cues: list[CaptionCue] = []
    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().splitlines()
        time_line = next((line for line in lines if " --> " in line), None)
        if time_line is None:
            raise ValueError("INVALID_SRT_BLOCK")
        match = re.fullmatch(
            r"\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s+-->\s+"
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})(?:\s+.*)?",
            time_line,
        )
        if match is None:
            raise ValueError("INVALID_SRT_TIMESTAMP")
        values = [int(value) for value in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        position = lines.index(time_line)
        text = " ".join(lines[position + 1:]).strip()
        if not text or end <= start:
            raise ValueError("INVALID_SRT_CUE")
        cues.append(CaptionCue(start, end, text))
    return cues


def audit_source(
    *,
    requested_video_id: str,
    transcript_video_id: str | None,
    transcript_provenance: str,
    srt_content: str,
    video_duration_s: float,
    verified_topic_anchors: Iterable[str] = (),
    min_duration_coverage: float = 0.55,
) -> dict[str, object]:
    """Produce BLOCKED_SOURCE or NEEDS_REVIEW; never infer editorial approval.

    transcript_video_id MUST come from verified download provenance, not from a
    renamed file. Anchor strings are taken from independently verified source
    metadata or editorial notes; an empty list means semantic match is unknown.
    """
    issues: list[str] = []
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", requested_video_id or ""):
        issues.append("INVALID_VIDEO_ID")
    if not transcript_video_id or requested_video_id != transcript_video_id:
        issues.append("SOURCE_ID_MISMATCH_OR_UNVERIFIED")
    if transcript_provenance not in {"youtube_original", "youtube_auto", "youtube_direct", "verified_local"}:
        issues.append("UNKNOWN_CAPTION_PROVENANCE")
    if not isinstance(video_duration_s, (int, float)) or not 0 < video_duration_s < 172800:
        issues.append("INVALID_VIDEO_DURATION")
    try:
        cues = parse_srt(srt_content)
    except ValueError as exc:
        cues = []
        issues.append(str(exc))
    if len(cues) < 5:
        issues.append("INSUFFICIENT_CAPTIONS")
    if cues and isinstance(video_duration_s, (int, float)) and video_duration_s > 0:
        if any(cue.start_s < 0 or cue.end_s > video_duration_s + 5 for cue in cues):
            issues.append("CUE_OUT_OF_BOUNDS")
        if any(right.start_s < left.start_s for left, right in zip(cues, cues[1:])):
            issues.append("NON_MONOTONIC_TIMESTAMPS")
        if cues[-1].end_s / video_duration_s < min_duration_coverage:
            issues.append("INSUFFICIENT_TIMELINE_COVERAGE")
    text = " ".join(cue.text for cue in cues).casefold()
    anchors = [str(anchor).strip().casefold() for anchor in verified_topic_anchors
               if len(str(anchor).strip()) >= 4]
    if anchors and not any(anchor in text for anchor in anchors):
        issues.append("TOPIC_ANCHORS_NOT_FOUND")
    elif not anchors:
        issues.append("TOPIC_MATCH_UNVERIFIED")
    # Lack of topical proof requires a manual review, not automatic acceptance.
    hard = [issue for issue in issues if issue != "TOPIC_MATCH_UNVERIFIED"]
    return {
        "status": "BLOCKED_SOURCE" if hard else "NEEDS_REVIEW",
        "issues": issues,
        "cue_count": len(cues),
        "captions_duration_s": round(cues[-1].end_s, 3) if cues else 0,
        "editorial_approved": False,
        "publication_allowed": False,
    }
