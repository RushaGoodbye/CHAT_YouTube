"""Run full transcript -> evidence -> SEO preview on AlexPC, without publishing or DB mutation."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks, ab_title_issues, evidence_outline_text
from rg_youtube_control.free_tools import (
    DEFAULT_OLLAMA_MODEL, _chapters_are_generic, fetch_transcript, generate_seo_package_local,
    load_srt_transcript, ollama_chat,
)

from rg_youtube_control.optimization import safe_description_fix

VIDEO_ID = "LM0vkW9YoKg"
started=time.monotonic()
data = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "RGYouTubeControl"
db = data / "rg_youtube_control.db"
result: dict = {
    "schema": "RG_FULL_SEO_0717_REALVIDEO_QA_V1",
    "video_id": VIDEO_ID,
    "model": DEFAULT_OLLAMA_MODEL,
    "source_code": "0.7.17 merged and Windows CI validated; QA remains preview only",
    "youtube_api_calls": 0,
    "db_mutations": 0,
    "publish_changes": 0,
    "ab_distinct_story_guard": True,
    "status": "started",
}
dest = data / "diagnostics" / "full_seo_0717_QA_LM0vkW9YoKg.json"
dest.parent.mkdir(parents=True, exist_ok=True)

def report(stage: str, **fields):
    result.update(fields)
    result["stage"] = stage
    result["elapsed_seconds"] = round(time.monotonic() - started, 1)
    print(json.dumps({"stage": stage, **fields}, ensure_ascii=True), flush=True)

try:
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=10) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        row = conn.execute("SELECT title,duration,profile FROM videos WHERE video_id=?", (VIDEO_ID,)).fetchone()
        if row is None: raise RuntimeError("Video absent from local database")
        title = str(row["title"])
        if row["profile"] != "main": raise RuntimeError("Unexpected profile")
        row = conn.execute(
            "SELECT description,source_description,tags_json FROM optimization_drafts WHERE video_id=?",
            (VIDEO_ID,),
        ).fetchone()
        old_description = str((row["source_description"] or row["description"]) if row else "")
        old_tags = []
        if row:
            try:
                old_tags = json.loads(str(row["tags_json"] or "[]"))
            except (ValueError, TypeError): pass
        setting = conn.execute("SELECT value FROM settings WHERE key='nas_transcripts_path'").fetchone()
        srt_dir = str(setting[0]) if setting and setting[0] else r"\\AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL\TRANSCRIPTS"
    report("local-metadata", current_title=title, old_description_chars=len(old_description))
    rows = []
    source = ""
    srt = Path(srt_dir) / (VIDEO_ID + ".srt")
    if srt.is_file():
        try:
            rows = load_srt_transcript(srt)
            source = "NAS SRT"
        except Exception as exc:
            report("nas-srt-error", problem=str(exc)[:200])
    if not rows:
        try:
            rows = fetch_transcript(VIDEO_ID)
            source = "youtube-transcript-api"
        except Exception as exc:
            report("youtube-transcript-error", problem=str(exc)[:400])
    if not rows:
        raise RuntimeError("No full transcript: neither NAS SRT nor YouTube transcript is accessible")
    report("full-transcript-loaded", transcript_source=source, transcript_rows=len(rows),
           transcript_chars=sum(len(str(r.get("text", ""))) for r in rows),
           final_start_second=float(rows[-1].get("start") or 0))
    with tempfile.TemporaryDirectory(prefix="rg_0717_qa_") as cache:
        last_progress = ""
        def progress(msg: str):
            nonlocal_stub = None
            global last_progress
            if msg != last_progress:
                last_progress = msg
                print(json.dumps({"stage": "evidence-progress", "message": msg}, ensure_ascii=True), flush=True)
        evidence = analyze_all_timeline_blocks(
            rows, model=DEFAULT_OLLAMA_MODEL, chat=ollama_chat,
            cache_dir=Path(cache), progress=progress,
            max_chars=5000, max_span_seconds=300, timeout=150.0,
        )
    result["evidence_blocks_total"] = evidence.get("blocks_total")
    result["evidence_blocks_verified"] = evidence.get("blocks_with_evidence")
    result["evidence_failed_blocks"] = evidence.get("failed_blocks")
    report("evidence-complete", total=evidence.get("blocks_total"),
           verified=evidence.get("blocks_with_evidence"),
           failed=evidence.get("failed_blocks"))
    if not evidence.get("blocks_with_evidence"):
        raise RuntimeError("None of the transcript segments yielded source-grounded evidence")
    package = generate_seo_package_local(
        current_title=title,
        current_description=old_description,
        current_tags=old_tags if isinstance(old_tags, list) else [],
        transcript=evidence_outline_text(evidence),
        public_context={"title": title, "duration": 3018, "description": old_description},
        is_short=False, fast_mode=False,
        timeout=240.0, evidence_report=evidence,
    )
    titles = [str(v) for v in (package.get("title_variants") or [])]
    issues = ab_title_issues(titles, evidence)
    description = str(package.get("description") or "")
    hashtags = [w for w in description.split() if w.startswith("#")]
    final_description = safe_description_fix(description, str(package.get("title") or title)).after
    final_hashtags = [w for w in final_description.split() if w.startswith("#")]
    raw_chapters = str(package.get("chapters") or "")
    extra_bullets = description.count("• ")
    generated_tags = [str(item) for item in (package.get("tags") or [])]
    weak_composite_tags = [t for t in generated_tags if t.casefold().startswith(("війна і ", "война и "))]
    checks = {
        "exactly_three_ab_titles": len(titles) == 3,
        "no_ab_evidence_issues": not issues,
        "main_title_under_100": 0 < len(str(package.get("title") or "")) <= 100,
        "description_not_empty": len(description) >= 200,
        "tags_present": len(package.get("tags") or []) >= 8,
        "full_transcript_input": len(rows) > 50,
        "source_evidence_present": evidence.get("blocks_with_evidence", 0) > 0,
        "no_giant_topic_list": extra_bullets <= 2,
        "concise_description": len(description) <= 1150,
        "no_weak_composite_tags": len(weak_composite_tags) == 0,
        "no_generic_chapters": not raw_chapters or not _chapters_are_generic(raw_chapters),
        "canonical_links": "links.rginfoua.pp.ua" in final_description and "donate.rginfoua.pp.ua" in final_description,
        "exactly_three_final_hashtags": len(final_hashtags) == 3,
        "fallback_requires_review": not bool(package.get("ab_source_quote_fallback_used")) or bool(package.get("needs_review")),
        "unchanged_title_flagged": (
            str(package.get("title") or "").casefold() != title.casefold()
            or bool(package.get("title_unchanged")) and bool(package.get("needs_review"))
        ),
    }
    result["checks"] = checks
    result["status"] = "PASS" if all(checks.values()) else "REVIEW"
    result["package"] = {
        "title": package.get("title"), "title_variants": titles,
        "description": description, "tags": package.get("tags"),
        "chapters": package.get("chapters"),
        "description_chars": len(description), "hashtags": hashtags,
        "final_preview_description": final_description,
        "final_preview_hashtags": final_hashtags,
        "extra_bullets": extra_bullets,
        "weak_composite_tags": weak_composite_tags,
        "title_unchanged": package.get("title_unchanged"),
        "needs_review": package.get("needs_review"),
        "review_reason": package.get("review_reason"),
        "ab_source_quote_fallback_used": bool(package.get("ab_source_quote_fallback_used")),
        "omitted_topic_count": len(package.get("timeline_omitted_topics") or []),
    }
    result["issues"] = issues
    result["full_evidence_coverage"] = evidence.get("blocks_with_evidence") == evidence.get("blocks_total")
    result["model_source_quote_fallback"] = bool(package.get("ab_source_quote_fallback_used"))
    report("generation-complete", status=result["status"], checks=checks, issues=issues)
except Exception as exc:
    result["status"]="BLOCKED"
    result["error"]=str(exc)[:500]
    report("blocked", error=result["error"])
finally:
    result["elapsed_seconds"]=round(time.monotonic()-started,1)
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"schema":result["schema"],"status":result["status"],"file":str(dest),
                      "elapsed_seconds":result["elapsed_seconds"],
                      "package":result.get("package"),
                      "checks":result.get("checks"),
                      "error":result.get("error")},ensure_ascii=True),flush=True)
if result["status"]=="BLOCKED":
    raise SystemExit(2)
