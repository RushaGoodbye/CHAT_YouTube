"""Read-only coverage audit on existing local/NAS SRTs (NO public transcript data).

No Ollama or YouTube API calls; no writes except aggregate JSON into job
workspace. Log/report contains NO transcripts, quotes, video IDs or filenames.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

from rg_youtube_control.config import (
    DEFAULT_NAS_TRANSCRIPTS_PATH, app_data_dir, normalize_nas_unc_path,
)
from rg_youtube_control.free_tools import load_srt_transcript
from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks

OUTPUT = Path("rg_youtube_real_srt_preflight.json")


def _coverage_only(*_args, **_kwargs) -> str:
    # Absolutely no AI call. No verified semantic topics are claimed here.
    return '{"topics":[]}'


def inspect(*, db_path: Path | None = None, transcript_dir: Path | None = None) -> dict:
    result = {
        "schema": "RG_REAL_SRT_PREFLIGHT_V1",
        "status": "NOT_READY",
        "mode": "READ_ONLY_NO_OLLAMA_NO_YOUTUBE",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profiles": {},
        "transcripts_uploaded": False,
        "transcripts_logged": False,
        "semantic_quality_verified": False,
        "source_modified": False,
    }
    db = db_path or (app_data_dir() / "rg_youtube_control.db")
    if not db.is_file():
        result["reason"] = "Local synchronized video database was not found"
        return result
    try:
        connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            """SELECT video_id, profile FROM videos
               WHERE profile IN ('main','live')
                 AND scheduled_publish_at IS NULL"""
        ).fetchall()
        settings = connection.execute(
            "SELECT value FROM settings WHERE key='nas_transcripts_path'"
        ).fetchone()
        connection.close()
    except sqlite3.Error:
        result["reason"] = "Local metadata database read-only query failed"
        return result

    raw = str(settings[0] or "").strip() if settings else ""
    root = transcript_dir or Path(
        normalize_nas_unc_path(raw, DEFAULT_NAS_TRANSCRIPTS_PATH)
    )
    if not root.is_dir():
        result["reason"] = "Configured NAS transcript directory is not reachable"
        return result
    try:
        # Directory enumeration once; no uploading or printing path/names.
        items = {
            item.stem: item
            for item in root.glob("*.srt")
            if item.is_file() and len(item.stem) == 11
        }
    except OSError:
        result["reason"] = "NAS transcript directory could not be listed"
        return result

    candidates = {profile: [] for profile in ("main", "live")}
    for video_id, profile in rows:
        if video_id in items and profile in candidates:
            candidates[profile].append(items[video_id])
    complete = 0
    for profile, available in candidates.items():
        entry = {"matched_srt_count": len(available), "status": "NO_SAMPLE"}
        for path in available[:5]:
            try:
                if path.stat().st_size > 40_000_000:
                    continue
                captions = load_srt_transcript(path)
                if not captions:
                    continue
                report = analyze_all_timeline_blocks(
                    captions,
                    model="read-only-coverage-preflight",
                    chat=_coverage_only,
                    max_chars=5000,
                    max_span_seconds=300,
                )
                entry = {
                    "status": "PASS" if report["source_integrity_verified"] else "FAIL",
                    "matched_srt_count": len(available),
                    "caption_rows": report["source_rows_with_text"],
                    "timeline_blocks": report["blocks_total"],
                    "timeline_blocks_processed": report["blocks_analyzed"],
                    "coverage_digest_equal": (
                        report["source_text_sha256"] == report["covered_text_sha256"]
                    ),
                }
                if entry["status"] == "PASS":
                    complete += 1
                break
            except (ValueError, OSError, RuntimeError):
                entry["status"] = "INVALID_SRT"
        result["profiles"][profile] = entry
    result["status"] = "PASS" if complete == 2 else "PARTIAL" if complete else "NOT_READY"
    if complete < 2:
        result["reason"] = "No usable matched SRT for one or both channel profiles"
    return result


def main() -> int:
    try:
        report = inspect()
    except Exception:
        report = {
            "schema": "RG_REAL_SRT_PREFLIGHT_V1",
            "status": "NOT_READY",
            "reason": "Unexpected read-only preflight failure",
            "transcripts_uploaded": False,
            "semantic_quality_verified": False,
        }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # These aggregate fields disclose no SRT text, video IDs or file names.
    print("REAL SRT PREFLIGHT STATUS:", report["status"], flush=True)
    for profile, item in (report.get("profiles") or {}).items():
        print("PROFILE:", profile, "STATUS:", item["status"],
              "MATCHED:", item["matched_srt_count"], flush=True)
    if report.get("reason"):
        print("REASON:", report["reason"], flush=True)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
