"""Verify a caption file against an acquisition record, without trusting its filename.

A record must be created at acquisition time from the actual download response.
Never synthesize verified provenance from an old file name or from SEO text.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from typing import Any

from .seo_source_integrity import audit_source

ACQUISITION_METHODS = {"youtube_original", "youtube_auto", "youtube_direct", "verified_local"}


def make_source_manifest(
    *, video_id: str, srt_bytes: bytes, source_url: str,
    acquisition_method: str, acquired_at: str, duration_s: float,
    verification: str,
) -> dict[str, Any]:
    """Record evidence at acquisition. Validity is rechecked before use."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("INVALID_VIDEO_ID")
    address = urlparse(source_url)
    allowed_domains = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
    if address.scheme != "https" or address.hostname not in allowed_domains or (
        address.username is not None or address.password is not None
    ):
        raise ValueError("SOURCE_URL_NOT_YOUTUBE")
    source_video_id = (
        parse_qs(address.query).get("v", [""])[0]
        if address.hostname != "youtu.be" and address.path == "/watch"
        else address.path.lstrip("/") if address.hostname == "youtu.be" else ""
    )
    if source_video_id != video_id:
        raise ValueError("SOURCE_URL_ID_MISMATCH")
    if not isinstance(duration_s, (int, float)) or not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("INVALID_SOURCE_DURATION")
    try:
        timestamp = datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("NAIVE_ACQUISITION_TIME")
    except (TypeError, AttributeError) as exc:
        raise ValueError("INVALID_ACQUISITION_TIME") from exc
    if acquisition_method not in ACQUISITION_METHODS:
        raise ValueError("UNKNOWN_ACQUISITION_METHOD")
    if verification not in {"youtube_caption_response", "manual_audio_match"}:
        raise ValueError("UNVERIFIED_ACQUISITION")
    if not acquired_at.strip():
        raise ValueError("MISSING_ACQUISITION_TIME")
    return {
        "schema_version": 1,
        "video_id": video_id,
        "source_url": source_url,
        "acquisition_method": acquisition_method,
        "acquired_at": acquired_at,
        "verification": verification,
        "duration_s": duration_s,
        "sha256": hashlib.sha256(srt_bytes).hexdigest(),
    }


def audit_caption_file(
    *, video_id: str, path: Path, duration_s: float,
    verified_topic_anchors: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Fail closed when a file or its exact-byte acquisition record is absent."""
    path = Path(path)
    record_path = path.with_suffix(".source.json")
    if not path.is_file() or not record_path.is_file():
        return {"status": "BLOCKED_SOURCE", "issues": ["MISSING_SRT_OR_MANIFEST"],
                "publication_allowed": False}
    raw = path.read_bytes()
    try:
        manifest = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("INVALID_MANIFEST")
        if manifest.get("schema_version") != 1:
            raise ValueError("INVALID_MANIFEST_VERSION")
        if not isinstance(manifest.get("sha256"), str) or (
            hashlib.sha256(raw).hexdigest() != manifest["sha256"]
        ):
            raise ValueError("CAPTION_HASH_MISMATCH")
        verified = make_source_manifest(
            video_id=manifest["video_id"], srt_bytes=raw,
            source_url=manifest["source_url"],
            acquisition_method=manifest["acquisition_method"],
            acquired_at=manifest["acquired_at"],
            duration_s=manifest["duration_s"],
            verification=manifest["verification"],
        )
        if verified != manifest:
            raise ValueError("MANIFEST_CONTENT_MISMATCH")
        if not (0.95 <= float(duration_s) / float(manifest["duration_s"]) <= 1.05):
            raise ValueError("VIDEO_DURATION_MISMATCH")
        return audit_source(
            requested_video_id=video_id,
            transcript_video_id=manifest["video_id"],
            transcript_provenance=manifest["acquisition_method"],
            srt_content=raw.decode("utf-8-sig"),
            video_duration_s=duration_s,
            verified_topic_anchors=verified_topic_anchors,
        )
    except (ValueError, TypeError, KeyError, UnicodeError, OSError, ZeroDivisionError) as exc:
        return {"status": "BLOCKED_SOURCE",
                "issues": [str(exc) if isinstance(exc, ValueError) else type(exc).__name__],
                "publication_allowed": False}
