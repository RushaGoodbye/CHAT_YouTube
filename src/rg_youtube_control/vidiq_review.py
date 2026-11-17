"""Validated, read-only vidIQ proposal inbox for desktop GUI.

The only author of title proposals is the connected vidIQ plugin.
Importing, viewing, or marking an item reviewed NEVER changes YouTube or
optimization_drafts. No automatic editorial/factual approval is implied.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
STATUSES = ("AWAITING_VIDIQ", "VIDIQ_SUGGESTED", "CONTENT_REVIEWED", "APPLIED")
SOURCE = "connected vidIQ plugin vidiq_generate_titles"


def validate_vidiq_proposals(raw: object, *, expected_channel_id: str = "") -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Expected a vidIQ export object")
    if raw.get("source") != SOURCE:
        raise ValueError("Only a connected vidIQ output may be imported")
    channel_id = str(raw.get("channel_id") or "")
    if expected_channel_id and channel_id != expected_channel_id:
        raise ValueError("Export is for another YouTube channel")
    if raw.get("publishing_enabled") is not False:
        raise ValueError("Publishing must be disabled for an import")
    videos = raw.get("videos")
    if not isinstance(videos, list) or not 1 <= len(videos) <= 1000:
        raise ValueError("Expected 1-1000 video records")
    out = []
    seen = set()
    for item in videos:
        if not isinstance(item, dict):
            raise ValueError("Invalid video record")
        video_id = str(item.get("video_id") or "")
        if not VIDEO_ID_RE.fullmatch(video_id) or video_id in seen:
            raise ValueError("Invalid or duplicate video ID")
        seen.add(video_id)
        titles = item.get("title_suggestions")
        if not isinstance(titles, list) or not 1 <= len(titles) <= 10:
            raise ValueError("Missing vidIQ title suggestions")
        options = []
        normalized_titles = set()
        for suggestion in titles:
            if not isinstance(suggestion, dict):
                raise ValueError("Invalid vidIQ title suggestion")
            title = str(suggestion.get("title") or "").strip()
            score = suggestion.get("vidiq_score")
            if not title or len(title) > 200 or not isinstance(score, (int, float)):
                raise ValueError("Missing title or score")
            if not 0 <= score <= 100 or title.casefold() in normalized_titles:
                raise ValueError("Repeated title or invalid score")
            normalized_titles.add(title.casefold())
            options.append({"title": title, "vidiq_score": score})
        out.append({"video_id": video_id, "title_suggestions": options,
                    "stage": "VIDIQ_SUGGESTED", "applied": False})
    return {"source": SOURCE, "channel_id": channel_id, "type": "titles_only",
            "created_on": str(raw.get("created_on") or ""),
            "publishing_enabled": False, "automatic_approval": False,
            "videos": out}


def save_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".vidiq_", suffix=".tmp",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_inbox(path: Path) -> dict:
    if not path.is_file():
        return {"source": SOURCE, "channel_id": "", "type": "titles_only",
                "publishing_enabled": False, "automatic_approval": False,
                "videos": []}
    original = json.loads(path.read_text(encoding="utf-8"))
    validated = validate_vidiq_proposals(original)
    by_id = {v["video_id"]: v for v in original["videos"]}
    for video in validated["videos"]:
        stored = by_id[video["video_id"]]
        stage = str(stored.get("stage") or "VIDIQ_SUGGESTED")
        if stage not in STATUSES:
            raise ValueError("Unknown vidIQ review stage")
        video["stage"] = stage
        if stage == "CONTENT_REVIEWED" and stored.get("editor_reviewed_at"):
            video["editor_reviewed_at"] = stored["editor_reviewed_at"]
    return validated


def import_proposals(source_path: Path, inbox_path: Path, *,
                     expected_channel_id: str,
                     allowed_video_ids: set[str]) -> dict:
    incoming = validate_vidiq_proposals(
        json.loads(source_path.read_text(encoding="utf-8")),
        expected_channel_id=expected_channel_id,
    )
    unknown = {v["video_id"] for v in incoming["videos"]} - allowed_video_ids
    if unknown:
        raise ValueError("Import contains videos not found in the selected channel")
    existing = load_inbox(inbox_path)
    if existing["channel_id"] not in ("", expected_channel_id):
        raise ValueError("Existing inbox belongs to another channel")
    merged = {v["video_id"]: v for v in existing["videos"]}
    for item in incoming["videos"]:
        prior = merged.get(item["video_id"])
        if prior and prior.get("stage") in ("CONTENT_REVIEWED", "APPLIED"):
            # Fresh suggestions never silently undo an approval or
            # overwrite an already-reconciled editorial decision.
            continue
        merged[item["video_id"]] = item
    incoming["videos"] = list(merged.values())
    save_json_atomic(inbox_path, incoming)
    return {"imported": len(incoming["videos"]),
            "newly_supplied": len(incoming["videos"]) - len(existing["videos"]),
            "channel_id": expected_channel_id,
            "publishing": False}


def set_editorial_reviewed(inbox_path: Path, video_id: str, *,
                           confirmed_content: bool) -> bool:
    if not confirmed_content:
        raise ValueError("Explicit manual factual review is required")
    data = load_inbox(inbox_path)
    for video in data["videos"]:
        if video["video_id"] == video_id:
            if video.get("stage") == "APPLIED":
                raise ValueError("Applied video may not be edited")
            video["stage"] = "CONTENT_REVIEWED"
            video["editor_reviewed_at"] = datetime.now(timezone.utc).isoformat()
            save_json_atomic(inbox_path, data)
            return True
    return False
