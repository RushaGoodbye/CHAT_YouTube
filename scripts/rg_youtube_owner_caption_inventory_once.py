"""One-video read-only owner caption inventory with mandatory quota reserve.

For diagnostic use on ALEXPC only. Never download captions or video, and never
emit IDs, text, track IDs, channel names or authentication details. Uses one
captions.list request (accounted as 50 units) only if the local quota reserve
permits it. Writes only an accurate quota ledger entry in the local UI DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Callable

from rg_youtube_control.cached_metadata import cached_public_metadata
from rg_youtube_control.config import app_data_dir
from rg_youtube_control.service import (
    quota_budget_status, record_quota_units,
)
from rg_youtube_control.youtube_api import YouTubeClient
from rg_youtube_real_live_seo_qa import MIN_LONG_LIVE_SECONDS

OUTPUT = Path("rg_youtube_owner_caption_inventory_anonymous.json")
CAPTIONS_LIST_UNITS = 50


def run(*, db_path: Path | None = None, client_factory: Callable = YouTubeClient) -> dict:
    result = {
        "schema": "RG_OWNER_CAPTION_INVENTORY_ONCE_V1",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "NOT_READY",
        "mode": "ONE_OWNER_CAPTIONS_LIST_READ_ONLY",
        "youtube_modified": False,
        "nas_modified": False,
        "source_text_exported": False,
        "video_identifiers_exported": False,
        "caption_identifiers_exported": False,
        "credentials_exported": False,
        "caption_downloads": 0,
        "ollama_called": False,
        "owner_authorized": False,
        "budget_permitted": False,
        "long_candidates": 0,
        "caption_lists_requested": 0,
        "quota_units_accounted": 0,
        "available_tracks": 0,
        "asr_tracks": 0,
        "non_asr_tracks": 0,
    }
    db = db_path or app_data_dir() / "rg_youtube_control.db"
    if not db.is_file():
        result["reason"] = "Local LIVE metadata DB unavailable"
        return result
    try:
        with sqlite3.connect(str(db)) as conn:
            conn.row_factory = sqlite3.Row
            candidates = []
            rows = conn.execute(
                """SELECT video_id FROM videos
                   WHERE profile='live' AND scheduled_publish_at IS NULL
                     AND COALESCE(privacy_status,'public')='public'"""
            ).fetchall()
            for row in rows:
                video_id = str(row["video_id"] or "")
                if len(video_id) != 11:
                    continue
                meta = cached_public_metadata(conn, video_id, "live")
                duration = int(meta.get("duration") or 0)
                if duration >= MIN_LONG_LIVE_SECONDS:
                    candidates.append((duration, video_id))
            result["long_candidates"] = len(candidates)
            if not candidates:
                result["reason"] = "No eligible long LIVE candidates"
                return result
            candidates.sort(reverse=True)
            budget = quota_budget_status(conn)
            if budget["exhausted"] or int(budget["spendable"]) < CAPTIONS_LIST_UNITS:
                result["status"] = "SKIPPED_BUDGET"
                result["reason"] = "Owner caption read blocked by existing quota reserve"
                return result
            result["budget_permitted"] = True
            video_id = candidates[0][1]
            client = client_factory(profile="live")
            client.credentials()  # Existing saved credential; never authorize().
            result["owner_authorized"] = True
            tracks = []
            result["caption_lists_requested"] = 1
            try:
                tracks = list(client.caption_tracks(video_id) or [])
            except Exception:
                result["reason"] = "Owner captions.list unavailable"
            finally:
                # Conservative accounting even if YouTube refuses the request.
                record_quota_units(conn, CAPTIONS_LIST_UNITS, purpose="video")
                result["quota_units_accounted"] = CAPTIONS_LIST_UNITS
            result["available_tracks"] = len(tracks)
            result["asr_tracks"] = sum(
                str((track.get("snippet") or {}).get("trackKind") or "").casefold() == "asr"
                for track in tracks
            )
            result["non_asr_tracks"] = len(tracks) - result["asr_tracks"]
            if tracks:
                result["status"] = "TRACKS_FOUND"
                result["reason"] = "Owner caption tracks exist; download not attempted"
            elif "reason" not in result:
                result["reason"] = "No owned caption tracks available for sampled long LIVE"
    except Exception:
        result["status"] = "NOT_READY"
        result["reason"] = "Existing authorization or local quota ledger unavailable"
    return result


def main() -> int:
    result = run()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for key in (
        "status", "long_candidates", "owner_authorized", "budget_permitted",
        "caption_lists_requested", "quota_units_accounted",
        "available_tracks", "asr_tracks", "non_asr_tracks", "reason",
    ):
        print("OWNER CAPTIONS " + key.upper() + ":", result.get(key), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
