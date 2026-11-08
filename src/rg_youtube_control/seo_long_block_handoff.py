"""Split a long provisional SEO record into time-window review candidates.

No approval or source completeness is inferred from a model-generated summary.
Each window inherits provisional status until independently human-reviewed.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any


def replace_provisional_with_windows(
    *, handoff: dict[str, Any], video_id: str, block_record_id: int,
    source_audit: dict[str, Any], proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    records=handoff.get("records")
    if not isinstance(records,list):
        raise ValueError("INVALID_HANDOFF")
    old=[r for r in records if r.get("video_id")==video_id and r.get("record_id")==block_record_id]
    if len(old)!=1 or old[0].get("status")!="PROVISIONAL_SOURCE_REVIEW":
        raise ValueError("NO_UNIQUE_PROVISIONAL_BLOCK")
    windows=source_audit.get("windows")
    if (not isinstance(windows,list) or not windows or
            source_audit.get("complete_transcript_window_coverage") is not True):
        raise ValueError("INCOMPLETE_WINDOW_SOURCE")
    if len(proposals)!=len(windows):
        raise ValueError("MISSING_WINDOW_PROPOSAL")
    new=[]
    for n,(window,proposal) in enumerate(zip(windows,proposals),1):
        if (proposal.get("window_number")!=n or
                window.get("source_covered") is not True or
                proposal.get("current_risk_ai")!="low"):
            raise ValueError("WINDOW_NOT_INDEPENDENTLY_SCREENED")
        quote=window.get("verbatim_quote")
        if (not isinstance(quote,str) or len(quote.strip())<8 or
                quote not in window.get("context_excerpt","") or
                sha256(quote.encode("utf-8")).hexdigest()!=window.get("quote_sha256") or
                proposal.get("source_quote_sha256")!=window.get("quote_sha256")):
            raise ValueError("WINDOW_QUOTE_MISMATCH")
        topic=proposal.get("topic")
        summary=proposal.get("summary_uk")
        if (not isinstance(topic,str) or not 5<=len(topic)<=110 or
                not isinstance(summary,str) or not 15<=len(summary)<=350):
            raise ValueError("INVALID_WINDOW_EDITORIAL_CANDIDATE")
        item=deepcopy(old[0])
        item.update({
            "record_id":block_record_id*100+n,
            "start_s":window["start_s"],
            "end_s":window["end_s"],
            "source_quote":quote,
            "source_context":window["context_excerpt"],
            "initial_topic":item.get("initial_topic") or "",
            "revised_topic":topic,
            "revised_summary":summary,
            "candidate_topic":topic,
            "candidate_summary":summary,
            "status":"PROVISIONAL_SOURCE_REVIEW",
            "risk_ai_after":"low",
            "human_review":None,
            "editorial_approved":False,
            "publication_allowed":False,
            "source_window_index":n,
        })
        item.pop("binding",None)
        new.append(item)
    keys={(r.get("video_id"),r.get("record_id")) for r in records if r is not old[0]}
    if any((r["video_id"],r["record_id"]) in keys for r in new):
        raise ValueError("DUPLICATE_WINDOW_RECORD_ID")
    output=deepcopy(handoff)
    output["records"]=[r for r in records if r is not old[0]]+new
    output["publication_allowed"]=False
    output["holdout_evaluated"]=0
    return output
