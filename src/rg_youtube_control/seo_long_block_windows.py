"""Source-only multi-window evidence packet for long caption blocks.

Time coverage and exact quotation are verifiable facts; editorial meaning is
not. A packet is always review-only and never creates SEO approvals.
"""
from __future__ import annotations

import hashlib
from typing import Sequence

from .seo_source_integrity import CaptionCue


def audit_long_block_windows(
    *, cues: Sequence[CaptionCue], start_s: float, end_s: float,
    window_s: float = 60.0, min_cues: int = 3,
) -> dict:
    if not (0 <= start_s < end_s <= 172800 and 15 <= window_s <= 300):
        raise ValueError("INVALID_WINDOW_RANGE")
    if min_cues < 1:
        raise ValueError("INVALID_MIN_CUES")
    if any(a.start_s > b.start_s for a, b in zip(cues, cues[1:])):
        raise ValueError("UNSORTED_SOURCE_CUES")
    windows=[]
    left=start_s
    while left < end_s:
        right=min(end_s,left+window_s)
        matches=[c for c in cues if left <= c.start_s < right and c.text.strip()]
        candidates=sorted(matches,key=lambda c:(
            c.text.rstrip().endswith((".","?","!","…")),
            len(c.text.split()),len(c.text)),reverse=True)
        representative=candidates[0] if candidates else None
        context=" ".join(c.text.strip() for c in matches)
        if representative is not None and representative.text not in context:
            raise ValueError("SOURCE_QUOTE_NOT_IN_CONTEXT")
        windows.append({
            "start_s":round(left,3),"end_s":round(right,3),
            "cue_count":len(matches),
            "verbatim_quote":representative.text if representative else "",
            "quote_start_s":round(representative.start_s,3) if representative else None,
            "context_excerpt":context[:3200],
            "quote_sha256":hashlib.sha256(representative.text.encode("utf-8")).hexdigest()
               if representative else None,
            "source_covered":len(matches)>=min_cues,
            "semantic_verified":False,
            "editorial_approved":False,
            "publication_allowed":False,
        })
        left=right
    total=sum(x["cue_count"] for x in windows)
    complete=all(x["source_covered"] for x in windows)
    return {
        "schema":"RG_G2_MULTIWINDOW_SOURCE_AUDIT_V1",
        "start_s":start_s,"end_s":end_s,"windows":windows,
        "total_cues":total,
        "complete_transcript_window_coverage":complete,
        "semantic_verified":False,
        "editorial_approved":False,
        "publication_allowed":False,
    }
