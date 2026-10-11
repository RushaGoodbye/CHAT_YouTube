"""Read-only installed RG YouTube Control SEO state verification; no imports from source runtime."""
from __future__ import annotations
import json
import os
import sqlite3
from pathlib import Path

VIDEO_ID = "LM0vkW9YoKg"
base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
db_path = base / "RGYouTubeControl" / "rg_youtube_control.db"
result = {
    "schema": "RG_YOUTUBE_INSTALLED_SEO_READONLY_V1",
    "database_exists": db_path.is_file(),
    "video_id": VIDEO_ID,
    "no_mutations": True,
    "youtube_api_calls": 0,
}
if db_path.is_file():
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        result["tables"] = {
            table: table in tables
            for table in ("videos", "optimization_drafts", "deep_review_state")
        }
        if "videos" in tables:
            result["videos_total"] = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            video = conn.execute(
                "SELECT video_id, profile, title, last_synced_at FROM videos WHERE video_id=?",
                (VIDEO_ID,),
            ).fetchone()
            result["real_video_found"] = bool(video)
            if video:
                result["real_video"] = dict(video)
        if "optimization_drafts" in tables:
            result["drafts_total"] = conn.execute(
                "SELECT COUNT(*) FROM optimization_drafts"
            ).fetchone()[0]
            row = conn.execute(
                """SELECT new_title, description, chapters, tags_json, title_variants_json,
                          status, generation, quality_state, quality_reason, updated_at
                   FROM optimization_drafts WHERE video_id=?""",
                (VIDEO_ID,),
            ).fetchone()
            result["real_video_draft_found"] = bool(row)
            if row:
                data = dict(row)
                try:
                    variants = json.loads(data.get("title_variants_json") or "[]")
                except (TypeError, ValueError):
                    variants = []
                try:
                    tags = json.loads(data.get("tags_json") or "[]")
                except (TypeError, ValueError):
                    tags = []
                description = data.get("description") or ""
                result["real_video_draft"] = {
                    "new_title": (data.get("new_title") or "")[:130],
                    "title_variants": [str(v)[:130] for v in variants[:3]]
                        if isinstance(variants, list) else [],
                    "variants_count": len(variants) if isinstance(variants, list) else 0,
                    "description_chars": len(description),
                    "chapters_chars": len(data.get("chapters") or ""),
                    "tags_count": len(tags) if isinstance(tags, list) else 0,
                    "hashtags": [word for word in description.split() if word.startswith("#")][:10],
                    "links_present": "links.rginfoua.pp.ua" in description,
                    "donations_present": "donate.rginfoua.pp.ua" in description,
                    "status": data.get("status"),
                    "generation": data.get("generation"),
                    "quality_state": data.get("quality_state"),
                    "quality_reason": (data.get("quality_reason") or "")[:240],
                    "updated_at": data.get("updated_at"),
                }
print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
