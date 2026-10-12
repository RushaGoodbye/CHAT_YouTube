"""Real Shoigu SEO dry run on ALEXPC. No YouTube write, no DB writes.

Run from a checked-out source revision after regression tests have passed.
Uses the already cached, source-quoted evidence map and local Ollama only.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rg_youtube_control.dialogue_seo import ab_title_issues, evidence_outline_text
from rg_youtube_control.free_tools import generate_seo_package_local
from rg_youtube_control.optimization import safe_description_fix

VIDEO_ID = "MEitKm687xo"
started = time.monotonic()
base = Path(os.environ["LOCALAPPDATA"]) / "RGYouTubeControl"
database = base / "rg_youtube_control.db"
evidence_path = base / "seo_evidence" / f"{VIDEO_ID}.json"
result = {
    "schema": "RG_SHOIGU_SEO_NO_WRITE_QA_V1",
    "video_id": VIDEO_ID,
    "read_only": True,
    "youtube_api_calls": 0,
    "youtube_writes": 0,
    "db_mutations": 0,
    "installed_app_changes": 0,
    "draft_overwrites": 0,
}
try:
    with sqlite3.connect(database.resolve().as_uri()+"?mode=ro", uri=True, timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        video = db.execute("SELECT title,profile,duration FROM videos WHERE video_id=?", (VIDEO_ID,)).fetchone()
        if video is None or video["profile"] != "main":
            raise RuntimeError("Shoigu video unavailable on main channel")
        draft = db.execute("SELECT description,tags_json FROM optimization_drafts WHERE video_id=?", (VIDEO_ID,)).fetchone()
        if not draft:
            raise RuntimeError("Original SEO draft unavailable; nothing changed")
        title = str(video["title"] or "")
        description_before = str(draft["description"] or "")
        tags_before = json.loads(draft["tags_json"] or "[]")
    if not evidence_path.is_file():
        raise RuntimeError("Existing grounded evidence map not found")
    report = json.loads(evidence_path.read_text(encoding="utf-8"))
    if report.get("blocks_total") != 2 or report.get("blocks_with_evidence") != 2:
        raise RuntimeError("Unexpected evidence map; stop rather than guess")
    source_topics = [
        str(item.get("topic") or "")
        for block in report.get("blocks") or []
        for item in block.get("topics") or []
    ]
    package = generate_seo_package_local(
        current_title=title,
        current_description=description_before,
        current_tags=tags_before,
        transcript=evidence_outline_text(report),
        public_context={"title": title, "description": "", "duration": 593},
        is_short=False, fast_mode=False,
        timeout=240.0, evidence_report=report,
    )
    ab = list(package.get("title_variants") or [])
    synopsis = str(package.get("description") or "")
    final_preview = safe_description_fix(synopsis, str(package.get("title") or title)).after
    issues = ab_title_issues(ab, report)
    result.update({
        "status": "PASS" if (
            len(ab) == 3 and not issues and not package.get("timeline_omitted_topics")
            and len(package.get("tags") or []) >= 8
            and len(synopsis) > 400
            and "links.rginfoua.pp.ua" in final_preview
            and "donate.rginfoua.pp.ua" in final_preview
        ) else "REVIEW",
        "source_blocks": int(report["blocks_total"]),
        "source_topic_count": len(source_topics),
        "source_topics": source_topics,
        "title": str(package.get("title") or ""),
        "titles_ab": ab,
        "ab_quality_issues": issues,
        "description": synopsis[:3800],
        "description_chars": len(synopsis),
        "description_links": "links.rginfoua.pp.ua" in final_preview,
        "donation_links": "donate.rginfoua.pp.ua" in final_preview,
        "omitted_topics": package.get("timeline_omitted_topics"),
        "tags": package.get("tags"),
        "chapters": package.get("chapters"),
        "needs_editorial_review": bool(package.get("needs_review")),
        "review_reason": package.get("review_reason"),
        "old_draft_chars_unchanged": len(description_before),
    })
except Exception as exc:
    result["status"] = "BLOCKED"
    result["error"] = f"{type(exc).__name__}: {exc}"[:900]
finally:
    result["elapsed_seconds"] = round(time.monotonic() - started, 1)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")), flush=True)
if result["status"] == "BLOCKED":
    raise SystemExit(2)
