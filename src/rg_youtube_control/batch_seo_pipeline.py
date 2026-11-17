"""Quota-free, bounded transcript acquisition and read-only SEO evidence audit.

Never modifies video metadata, optimization_drafts, or YouTube.
This is not an automated editorial approval engine.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _seconds(duration: str) -> int:
    value = str(duration or "").strip()
    if value.isdigit():
        return int(value)
    if ":" in value:
        try:
            total = 0
            for part in value.split(":"):
                total = total * 60 + int(part)
            return total
        except ValueError:
            return 0
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return 0
    days, hours, mins, secs = [int(v or 0) for v in match.groups()]
    return days * 86400 + hours * 3600 + mins * 60 + secs


def srt_text(rows: list[dict]) -> str:
    def stamp(seconds: float) -> str:
        millis = max(0, round(float(seconds) * 1000))
        hh, remain = divmod(millis, 3600000)
        mm, remain = divmod(remain, 60000)
        ss, ms = divmod(remain, 1000)
        return f"{hh:02}:{mm:02}:{ss:02},{ms:03}"

    out = []
    for row in rows:
        words = " ".join(str(row.get("text") or "").split())
        if not words:
            continue
        start = max(0.0, float(row.get("start") or 0))
        end = start + max(0.1, float(row.get("duration") or 0))
        out.append(f"{len(out)+1}\n{stamp(start)} --> {stamp(end)}\n{words}")
    return "\n\n".join(out) + ("\n" if out else "")


def inspect_srt(content: str, duration: int = 0) -> dict:
    from .free_tools import parse_srt_transcript
    rows = parse_srt_transcript(content)
    text_len = sum(len(str(r.get("text") or "")) for r in rows)
    last_end = max((float(r["start"]) + float(r["duration"]) for r in rows), default=0)
    first_start = min((float(r["start"]) for r in rows), default=0)
    coverage = round(last_end / duration, 3) if duration > 0 else None
    issues = []
    if len(rows) < 8 or text_len < 200:
        issues.append("not_enough_transcript_text")
    if duration >= 180 and last_end < duration * 0.90:
        issues.append("transcript_truncated")
    if duration >= 180 and first_start > max(180, duration * 0.10):
        issues.append("transcript_missing_beginning")
    return {"segments": len(rows), "characters": text_len, "last_end": round(last_end, 1),
            "duration": duration, "end_coverage": coverage, "complete": not issues,
            "issues": issues}


def _fetch(video_id: str) -> tuple[list[dict], str]:
    from .free_tools import fetch_transcript, fetch_public_metadata, fetch_transcript_from_public_metadata
    errors = []
    try:
        rows = fetch_transcript(video_id, languages=("uk", "ru", "en"))
        if rows:
            return rows, "youtube-transcript-api"
    except Exception as exc:
        errors.append(f"transcript_api:{type(exc).__name__}")
    try:
        meta = fetch_public_metadata(video_id)
        rows = fetch_transcript_from_public_metadata(meta, languages=("uk", "ru", "en"))
        if rows:
            return rows, "yt-dlp-captions"
    except Exception as exc:
        errors.append(f"yt_dlp:{type(exc).__name__}")
    raise RuntimeError(";".join(errors) or "captions_unavailable")



def inspect_seo_draft(video: sqlite3.Row, transcript_content: str | None) -> dict:
    """Read-only SEO field audit. Never claims that reported facts are verified."""
    from .free_tools import parse_srt_transcript
    issues = []
    title = str(video["draft_title"] or video["title"] or "").strip()
    description = str(video["draft_description"] or "").strip()
    try:
        tags = json.loads(video["draft_tags"] or "[]")
        if not isinstance(tags, list):
            tags = []
    except (ValueError, TypeError):
        tags = []
    try:
        variants = json.loads(video["variants"] or "[]")
        if not isinstance(variants, list):
            variants = []
    except (ValueError, TypeError):
        variants = []
    if not title or len(title) > 100:
        issues.append("title_empty_or_over_100")
    if len(description) < 120:
        issues.append("description_too_short")
    if len([tag for tag in tags if str(tag).strip()]) < 8:
        issues.append("fewer_than_8_tags")
    if len(variants) != 3:
        issues.append("ab_requires_three_distinct_titles")
    else:
        from .dialogue_seo import ab_title_issues
        if ab_title_issues(variants):
            issues.append("ab_title_quality_requires_review")
    if transcript_content is None:
        issues.append("no_full_srt_evidence")
    else:
        segments = parse_srt_transcript(transcript_content)
        transcript_words = {
            word for segment in segments
            for word in re.findall(r"[\w\u0400-\u052f]{5,}",
                                   str(segment.get("text") or "").casefold())
        }
        title_words = {
            word for word in re.findall(r"[\w\u0400-\u052f]{5,}", title.casefold())
            if word not in {"рашагудбай", "россия", "росії", "раша", "гудбай"}
        }
        if title_words and len(title_words & transcript_words) / len(title_words) < 0.2:
            issues.append("title_low_lexical_support_in_srt")
    return {"seo_checks": issues, "seo_issues": ", ".join(issues),
            "seo_result": "editorial_review_required",
            "editorial_approval_automated": False}


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                 dir=str(path.parent), prefix=".rg_srt_", suffix=".tmp",
                                 delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _candidates(conn: sqlite3.Connection, profile: str, limit: int) -> list[sqlite3.Row]:
    # Prioritize stored unverified packages; ties resolved by views.
    return conn.execute(
        """SELECT v.video_id,v.title,v.duration,v.views, v.profile,
                  COALESCE(d.status,'') AS draft_status,
                  COALESCE(d.generation,'') AS generation,
                  COALESCE(d.quality_state,'') AS quality_state,
                  COALESCE(d.title_variants_json,'[]') AS variants,
                  COALESCE(d.new_title,'') AS draft_title,
                  COALESCE(d.description,'') AS draft_description,
                  COALESCE(d.tags_json,'[]') AS draft_tags
           FROM videos v
           LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
           WHERE v.profile=?
           ORDER BY CASE
             WHEN d.status='ready' AND (d.generation IS NULL
                  OR d.generation NOT IN ('vidiq-reviewed-srt-v1','manual-reviewed-srt-v1'))
                  THEN 0
             WHEN d.status='draft' THEN 1
             ELSE 2 END,
             COALESCE(v.views,0) DESC, v.video_id
           LIMIT ?""", (profile, max(1, limit)),
    ).fetchall()


def recent_failed_ids(report_dir: Path, profile: str, now: datetime | None = None) -> set[str]:
    """One-day retry cooldown so permanent failures cannot starve later videos."""
    current = now or datetime.now(timezone.utc)
    failed: set[str] = set()
    if not report_dir.is_dir():
        return failed
    reports = sorted(report_dir.glob("rg_batch_" + profile + "_*.json"), reverse=True)[:50]
    for path in reports:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("dry_run"):
                continue
            stamp = datetime.fromisoformat(str(payload["created_at"]).replace("Z","+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age = (current - stamp).total_seconds()
            if age < 0 or age >= 86400:
                continue
            for record in payload.get("records") or []:
                if record.get("srt_result") in ("fetch_failed", "incomplete", "paused_after_rate_limit"):
                    failed.add(str(record.get("video_id") or ""))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return failed


def run_batch(*, db_path: str | Path, srt_dir: str | Path, profile: str = "main",
              limit: int = 10, acquire: bool = False, pause: float = 1.5,
              progress: Callable[[str], None] | None = None) -> dict:
    """Bounded run. Read-only SQLite; no YouTube Data API; no SEO approval."""
    if profile not in {"main", "live"}:
        raise ValueError("Unknown channel profile")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be 1..50")
    database = Path(db_path)
    target = Path(srt_dir)
    if not database.is_file():
        raise FileNotFoundError(database)
    if not target.is_dir():
        raise FileNotFoundError(target)
    conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # Scan all candidates so populated SRTs do not block progress.
        candidates = _candidates(conn, profile, 100000)
        failed_recently = recent_failed_ids(target / '_batch_reports', profile) if acquire else set()
        pending = []
        for video in candidates:
            video_id = str(video["video_id"])
            if not VIDEO_ID.fullmatch(video_id) or video_id in failed_recently:
                continue
            path = target / (video_id + ".srt")
            if path.exists() and path.stat().st_size:
                data = inspect_srt(path.read_text(encoding="utf-8-sig", errors="replace"),
                                   _seconds(video["duration"]))
                if data["complete"]:
                    continue
            pending.append(video)
            if len(pending) == limit:
                break

        records = []
        blocked = False
        for index, video in enumerate(pending, 1):
            video_id = str(video["video_id"])
            path = target / (video_id + ".srt")
            duration = _seconds(video["duration"])
            row = {"video_id": video_id, "profile": profile,
                   "title": str(video["title"] or ""),
                   "draft_status": video["draft_status"], "origin": video["generation"],
                   "seo_result": "editorial_review_required", "source": "",
                   "srt_result": "", "error": ""}
            try:
                existing = path.exists() and path.stat().st_size > 0
                if existing:
                    content = path.read_text(encoding="utf-8-sig", errors="replace")
                    source = "existing_srt"
                elif not acquire:
                    row["srt_result"] = "missing_dry_run"
                    row.update(inspect_seo_draft(video, None))
                    records.append(row)
                    continue
                else:
                    if blocked:
                        row["srt_result"] = "paused_after_rate_limit"
                        records.append(row)
                        continue
                    fetched, source = _fetch(video_id)
                    content = srt_text(fetched)
                inspected = inspect_srt(content, duration)
                row.update(inspected)
                row["source"] = source
                if inspected["complete"]:
                    if not existing:
                        _write_atomic(path, content)
                    row["srt_result"] = "complete"
                else:
                    row["srt_result"] = "incomplete"
                    row["error"] = ",".join(inspected["issues"])
                    # Never overwrite an existing transcript or publish short/broken captures.
            except Exception as exc:
                row["srt_result"] = "fetch_failed"
                row["error"] = (type(exc).__name__ + ": " + str(exc))[:260]
                if any(token in row["error"].casefold()
                       for token in ("429", "ratelimit", "too many requests", "ipblocked")):
                    blocked = True
            content_for_audit = content if row['srt_result'] == 'complete' else None
            row.update(inspect_seo_draft(video, content_for_audit))
            records.append(row)
            if progress:
                progress(f"{index}/{len(pending)} {video_id}: {row['srt_result']}")
            if acquire and not blocked and index < len(pending):
                time.sleep(max(0, min(pause, 10)))

        # Read-only audit of existing full SRTs, including earlier batches.
        # This never changes stored SEO drafts or YouTube metadata.
        audited_existing = 0
        scanned_ids = {record["video_id"] for record in records}
        for video in candidates:
            if audited_existing >= 200:
                break
            video_id = str(video["video_id"])
            if video_id in scanned_ids or not VIDEO_ID.fullmatch(video_id):
                continue
            existing_path = target / (video_id + ".srt")
            if not existing_path.is_file():
                continue
            try:
                current_srt = existing_path.read_text(
                    encoding="utf-8-sig", errors="replace"
                )
                inspected = inspect_srt(current_srt, _seconds(video["duration"]))
                if not inspected["complete"]:
                    continue
                record = {
                    "video_id": video_id, "profile": profile,
                    "title": str(video["title"] or ""),
                    "draft_status": video["draft_status"],
                    "origin": video["generation"],
                    "source": "existing_srt",
                    "srt_result": "existing_complete",
                    "error": "",
                }
                record.update(inspected)
                record.update(inspect_seo_draft(video, current_srt))
                records.append(record)
                audited_existing += 1
            except (OSError, ValueError, TypeError):
                continue

        now = datetime.now(timezone.utc).isoformat()
        result = {"created_at": now, "profile": profile, "dry_run": not acquire,
                  "candidate_count": len(candidates), "pending_count": len(pending),
                  "audited_existing_srt": audited_existing,
                  "status_counts": dict(Counter(r["srt_result"] for r in records)),
                  "editorial_approval_automated": False,
                  "youtube_metadata_modified": False,
                  "youtube_data_api_units_used": 0,
                  "records": records}
        report_dir = target / "_batch_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        name = f"rg_batch_{profile}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
        _write_atomic(report_dir / (name + ".json"), json.dumps(result, ensure_ascii=False, indent=2))
        with (report_dir / (name + ".csv")).open("w", newline="", encoding="utf-8-sig") as handle:
            keys = ["video_id","title","profile","draft_status","origin","source",
                    "srt_result","segments","characters","end_coverage","seo_result","seo_issues","error"]
            writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        result["report_json"] = str(report_dir / (name + ".json"))
        result["report_csv"] = str(report_dir / (name + ".csv"))
        return result
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SRT batch + read-only SEO audit")
    parser.add_argument("--db", required=True)
    parser.add_argument("--srt-dir", required=True)
    parser.add_argument("--profile", choices=("main","live"), default="main")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--acquire", action="store_true")
    parser.add_argument("--pause", type=float, default=1.5)
    args = parser.parse_args(argv)
    result = run_batch(db_path=args.db,srt_dir=args.srt_dir,profile=args.profile,
                       limit=args.limit,acquire=args.acquire,pause=args.pause,progress=print)
    print(json.dumps({k:v for k,v in result.items() if k != "records"},ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
