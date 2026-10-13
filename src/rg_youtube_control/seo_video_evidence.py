"""Per-video, evidence-anchored SEO report storage. No implicit writes.

Unlike the hashed block-level analysis cache, this index is keyed by video ID
and verified transcript fingerprint. Never use stale evidence from another cut.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path


def fingerprint_transcript(rows: list[dict]) -> str:
    stable = [{"start": row.get("start"), "text": str(row.get("text") or "")}
              for row in rows]
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")).hexdigest()


def evidence_path(root: str | Path, video_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        raise ValueError("invalid video id")
    return Path(root) / (video_id + ".json")


def build_video_evidence(video_id: str, transcript_rows: list[dict],
                         timeline_report: dict, *, transcript_source: str) -> dict:
    if not transcript_rows or not timeline_report.get("blocks_with_evidence"):
        raise ValueError("no_verified_timeline")
    verified = []
    for block in timeline_report.get("blocks") or []:
        for topic in block.get("topics") or []:
            if not isinstance(topic, dict):
                continue
            quote = str(topic.get("evidence") or "").strip()
            label = str(topic.get("topic") or "").strip()
            if label and quote:
                verified.append({"topic": label, "evidence": quote,
                                 "start": block.get("start"),
                                 "end": block.get("end")})
    if not verified:
        raise ValueError("no_quoted_topics")
    return {"schema": "RG_VIDEO_SEO_EVIDENCE_V1", "video_id": video_id,
            "transcript_sha256": fingerprint_transcript(transcript_rows),
            "transcript_source": transcript_source,
            "blocks_total": timeline_report.get("blocks_total"),
            "blocks_with_evidence": timeline_report.get("blocks_with_evidence"),
            "blocks": timeline_report.get("blocks"),
            "verified_topics": verified}


def store_video_evidence(directory: str | Path, video_id: str, payload: dict) -> Path:
    """Only called after successful independent QA; atomic explicit write."""
    path = evidence_path(directory, video_id)
    if payload.get("video_id") != video_id or payload.get("schema") != "RG_VIDEO_SEO_EVIDENCE_V1":
        raise ValueError("evidence_video_mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def read_video_evidence(directory: str | Path, video_id: str,
                        *, transcript_sha256: str | None = None) -> dict | None:
    path = evidence_path(directory, video_id)
    if not path.is_file():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema") != "RG_VIDEO_SEO_EVIDENCE_V1" or report.get("video_id") != video_id:
        return None
    if transcript_sha256 is not None and report.get("transcript_sha256") != transcript_sha256:
        return None
    return report
