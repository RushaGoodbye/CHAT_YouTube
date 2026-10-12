"""Read-only fresh full-timeline Shoigu QA: never use existing evidence cache.

Runs source pipeline: fresh captions -> analyze_all_timeline_blocks(cache_dir=None)
-> evidence_outline_text -> generate_seo_package_local -> GUI normalization-equivalent.
No DB or YouTube writes. No changes to installed app.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rg_youtube_control.dialogue_seo import (
    analyze_all_timeline_blocks, evidence_outline_text, ab_title_issues
)
from rg_youtube_control.free_tools import (
    fetch_transcript, load_srt_transcript, generate_seo_package_local,
    ollama_chat, DEFAULT_OLLAMA_MODEL,
)
from rg_youtube_control.optimization import safe_description_fix

VIDEO_ID = "MEitKm687xo"
started = time.monotonic()
base = Path(os.environ["LOCALAPPDATA"]) / "RGYouTubeControl"
result = {"schema": "RG_SHOIGU_FRESH_TIMELINE_READONLY_V1", "video_id": VIDEO_ID,
          "youtube_writes": 0, "db_mutations": 0, "installed_app_changes": 0,
          "existing_evidence_cache_used": False, "read_only": True}
try:
    db_path = base / "rg_youtube_control.db"
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        video = db.execute("SELECT title,profile FROM videos WHERE video_id=?", (VIDEO_ID,)).fetchone()
        if not video or video["profile"] != "main":
            raise RuntimeError("Original Shoigu video missing from main channel")
        title = str(video["title"] or "")
        draft = db.execute("SELECT description,tags_json FROM optimization_drafts WHERE video_id=?", (VIDEO_ID,)).fetchone()
        description = str(draft["description"] or "") if draft else ""
        tags = json.loads(draft["tags_json"] or "[]") if draft else []
    rows = []
    source = ""
    # The GUI prefers NAS SRT, then YouTube transcript API.
    # Use the configured NAS path when present, otherwise the public transcript API.
    for candidate in (base / "transcripts" / (VIDEO_ID + ".srt"),):
        if candidate.is_file():
            rows = load_srt_transcript(candidate)
            source = "local-srt"
            break
    if not rows:
        rows = fetch_transcript(VIDEO_ID)
        source = "youtube-transcript-api"
    if not rows:
        raise RuntimeError("Fresh transcript unavailable - cannot verify GUI path")
    report = analyze_all_timeline_blocks(
        rows, model=DEFAULT_OLLAMA_MODEL, chat=ollama_chat,
        cache_dir=None, max_chars=5000, max_span_seconds=300, timeout=180,
    )
    if not report.get("blocks_with_evidence"):
        raise RuntimeError("Fresh timeline contains no verified source evidence")
    package = generate_seo_package_local(
        current_title=title, current_description=description, current_tags=tags,
        transcript=evidence_outline_text(report),
        public_context={"title": title, "description": description, "duration": 593},
        is_short=False, fast_mode=False, timeout=300, evidence_report=report,
    )
    ab = list(package.get("title_variants") or [])
    issues = ab_title_issues(ab, report)
    omitted = list(package.get("timeline_omitted_topics") or [])
    result.update({
        "status": "PASS" if len(ab) == 3 and not issues and not omitted else "REVIEW",
        "transcript_source": source, "transcript_rows": len(rows),
        "timeline_blocks": report.get("blocks_total"),
        "verified_blocks": report.get("blocks_with_evidence"),
        "evidence_cache_hits": report.get("cache_hits"),
        "ab_titles": ab, "ab_quality_issues": issues,
        "omitted_count": len(omitted), "omitted_topics": omitted[:12],
        "description": str(package.get("description") or "")[:3200],
        "review_reason": package.get("review_reason"),
    })
except Exception as exc:
    result.update({"status": "BLOCKED", "error": (type(exc).__name__ + ": " + str(exc))[:600]})
finally:
    result["elapsed_seconds"] = round(time.monotonic() - started, 1)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")), flush=True)
if result["status"] != "PASS":
    raise SystemExit(1)
