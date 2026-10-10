"""ONE-SHOT, quota-budgeted owner caption fetch for a real 3h+ LIVE.

No GitHub artifacts contain source text, video identifiers, captions, links or
credentials. A complete SRT, if permitted by the owner's YouTube API access,
is staged privately on ALEXPC F: for further offline QA. Nothing is uploaded,
and no YouTube videos or NAS production content are modified.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import os
import sqlite3
from typing import Callable

from rg_youtube_control.cached_metadata import cached_public_metadata
from rg_youtube_control.config import app_data_dir
from rg_youtube_control.free_tools import parse_srt_transcript
from rg_youtube_control.service import quota_budget_status, record_quota_units
from rg_youtube_control.youtube_api import YouTubeClient
from rg_youtube_real_live_seo_qa import MIN_LONG_LIVE_SECONDS, _captions_span_full_long_live

OUTPUT = Path("rg_youtube_owner_caption_download_anonymous.json")
LIST_COST = 50
DOWNLOAD_COST = 200
MAX_SRT_BYTES = 15_000_000


def run(
    *, db_path: Path | None = None,
    private_root: Path | None = None,
    client_factory: Callable = YouTubeClient,
) -> dict:
    report = {
        "schema": "RG_OWNER_CAPTION_FETCH_ONCE_V1",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "NOT_READY",
        "mode": "OWNER_CAPTION_READ_ONLY_PRIVATE_STAGE",
        "youtube_modified": False,
        "nas_modified": False,
        "video_ids_exported": False,
        "source_text_exported": False,
        "caption_text_exported": False,
        "credentials_exported": False,
        "local_private_source_staged": False,
        "api_requests_sent": 0,
        "quota_units_accounted": 0,
        "long_candidates": 0,
        "track_count": 0,
        "caption_rows": 0,
        "full_span_coverage": False,
        "ollama_called": False,
    }
    db = db_path or app_data_dir() / "rg_youtube_control.db"
    if not db.is_file():
        report["reason"] = "Local channel database unavailable"
        return report
    try:
        with sqlite3.connect(str(db)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT video_id FROM videos
                   WHERE profile='live' AND scheduled_publish_at IS NULL
                     AND COALESCE(privacy_status,'public')='public'"""
            ).fetchall()
            candidates = []
            for row in rows:
                video_id = str(row["video_id"] or "")
                if len(video_id) != 11:
                    continue
                duration = int(cached_public_metadata(
                    conn, video_id, "live"
                ).get("duration") or 0)
                if duration >= MIN_LONG_LIVE_SECONDS:
                    candidates.append((duration, video_id))
            report["long_candidates"] = len(candidates)
            if not candidates:
                report["reason"] = "No eligible long LIVE"
                return report
            budget = quota_budget_status(conn)
            if budget["exhausted"] or int(budget["spendable"]) < LIST_COST + DOWNLOAD_COST:
                report["status"] = "SKIPPED_BUDGET"
                report["reason"] = "Not enough quota outside the protected reserve"
                return report
            candidates.sort(reverse=True)
            duration, video_id = candidates[0]
            client = client_factory(profile="live")
            client.credentials()
            report["api_requests_sent"] += 1
            try:
                tracks = list(client.caption_tracks(video_id) or [])
            except Exception:
                tracks = []
                report["reason"] = "Owner caption list failed"
            finally:
                record_quota_units(conn, LIST_COST, purpose="video")
                report["quota_units_accounted"] += LIST_COST
            report["track_count"] = len(tracks)
            if not tracks:
                report.setdefault("reason", "No owner caption tracks")
                return report
            # Prefer a human-reviewed track; ASR remains a valid fallback.
            tracks.sort(key=lambda t: (
                str((t.get("snippet") or {}).get("trackKind") or "").casefold() == "asr",
                str((t.get("snippet") or {}).get("language") or "") not in {"ru", "uk", "en"},
            ))
            caption_id = str(tracks[0].get("id") or "")
            if not caption_id:
                report["reason"] = "Caption track has no download identifier"
                return report
            report["api_requests_sent"] += 1
            try:
                srt_text = client.download_caption_srt(caption_id)
            except Exception:
                report["status"] = "DOWNLOAD_UNAVAILABLE"
                report["reason"] = "Owner caption download was not permitted"
                return report
            finally:
                record_quota_units(conn, DOWNLOAD_COST, purpose="video")
                report["quota_units_accounted"] += DOWNLOAD_COST
            if not srt_text or len(srt_text.encode("utf-8")) > MAX_SRT_BYTES:
                report["reason"] = "Caption source empty or exceeds private QA limit"
                return report
            captions = parse_srt_transcript(srt_text)
            report["caption_rows"] = len(captions)
            report["full_span_coverage"] = _captions_span_full_long_live(
                captions, duration
            )
            if not report["full_span_coverage"]:
                report["status"] = "INCOMPLETE_SOURCE"
                report["reason"] = "Owned captions do not span the 3h+ source"
                return report
            # Staging is local to ALEXPC: never the project checkout or
            # GitHub runner artifact, and never the NAS production transcript
            # directory. A generated update cannot accidentally publish it.
            dest_root = private_root or (
                Path("F:/RG_YOUTUBE_CONTROL_QA/private_source")
                if os.name == "nt" and Path("F:/").is_dir()
                else app_data_dir() / "private_source_qa"
            )
            dest_root.mkdir(parents=True, exist_ok=True)
            destination = dest_root / (video_id + ".srt")
            temp = dest_root / (video_id + ".pending")
            temp.write_text(srt_text, encoding="utf-8")
            temp.replace(destination)
            report["local_private_source_staged"] = True
            report["status"] = "SOURCE_STAGED"
            report["reason"] = "Verified long owner SRT staged privately on ALEXPC"
    except Exception:
        report["status"] = "NOT_READY"
        report["reason"] = "Owner access, local database or private storage unavailable"
    return report


def main() -> int:
    report = run()
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for key in (
        "status", "long_candidates", "track_count", "api_requests_sent",
        "quota_units_accounted", "caption_rows", "full_span_coverage",
        "local_private_source_staged", "reason",
    ):
        print("OWNER LONG SRT " + key.upper() + ":", report.get(key), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
