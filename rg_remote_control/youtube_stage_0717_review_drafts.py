"""Safely stage THREE human-review-only SEO drafts in installed app database.
- Backup entire SQLite via backup API first.
- Only videos without any existing draft, main channel, public, unscheduled.
- Require real public description/tags and channel/title provenance via yt-dlp.
- Enforce all quality checks and source-quote editorial REVIEW state.
- No YouTube Data API writes, thumbnails, scheduled settings, or publishing.
"""
from __future__ import annotations
import os,sys,sqlite3,json,datetime,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from rg_youtube_control.db import save_optimization_draft
from rg_youtube_control.free_tools import fetch_public_metadata

IDS=("Ati19utM7Ck","6R4GpTmVJLc","pW9YJnCY7FU")
folder=Path(os.environ["LOCALAPPDATA"])/"RGYouTubeControl"
db=folder/"rg_youtube_control.db"
diagnostics=folder/"diagnostics"
diagnostics.mkdir(parents=True,exist_ok=True)
out={"schema":"RG_STAGE_SAFE_SEO_REVIEW_DRAFTS_0717_V1",
     "no_youtube_data_api_calls":True,"no_youtube_writes":True,
     "no_thumbnail_changes":True,"no_visibility_changes":True,
     "staged":[],"skipped":[]}
payloads=[]
with sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=10) as rd:
    rd.row_factory=sqlite3.Row
    rd.execute("PRAGMA query_only=ON")
    for video_id in IDS:
        row=rd.execute("""SELECT video_id,title,profile,channel_id,privacy_status,
                                 scheduled_publish_at
                            FROM videos WHERE video_id=?""",(video_id,)).fetchone()
        exists=rd.execute("SELECT 1 FROM optimization_drafts WHERE video_id=?",(video_id,)).fetchone()
        if not row or row["profile"]!="main" or row["privacy_status"]!="public" or row["scheduled_publish_at"]:
            out["skipped"].append({"video_id":video_id,"reason":"not eligible public unscheduled main video"})
            continue
        if exists:
            out["skipped"].append({"video_id":video_id,"reason":"existing SEO draft protected"})
            continue
        qa=diagnostics/f"full_seo_0717_QA_{video_id}.json"
        if not qa.is_file():
            out["skipped"].append({"video_id":video_id,"reason":"full QA proof missing"})
            continue
        data=json.loads(qa.read_text(encoding="utf-8"))
        package=dict(data.get("package") or {})
        checks=dict(data.get("checks") or {})
        titles=list(package.get("title_variants") or [])
        if data.get("status")!="PASS" or not checks or not all(checks.values()) or len(titles)!=3:
            out["skipped"].append({"video_id":video_id,"reason":"QA result not fully PASS"})
            continue
        if not package.get("needs_review"):
            out["skipped"].append({"video_id":video_id,"reason":"non-review SEO output not staged without approval"})
            continue
        try:
            public=fetch_public_metadata(video_id)
        except Exception as exc:
            out["skipped"].append({"video_id":video_id,"reason":"public source metadata inaccessible: "+str(exc)[:160]})
            continue
        official_title=str(public.get("title") or "").strip()
        original_title=str(row["title"] or "").strip()
        if not official_title or official_title.casefold()!=original_title.casefold():
            out["skipped"].append({"video_id":video_id,"reason":"live YouTube title differs from local DB: manual resync required"})
            continue
        if row["channel_id"] and public.get("channel_id") and row["channel_id"] != public["channel_id"]:
            out["skipped"].append({"video_id":video_id,"reason":"channel ID mismatch"})
            continue
        official_description=str(public.get("description") or "")
        if not official_description.strip():
            out["skipped"].append({"video_id":video_id,"reason":"cannot snapshot public description, no write"})
            continue
        if len(str(package.get("title") or ""))>100 or not package.get("description"):
            out["skipped"].append({"video_id":video_id,"reason":"invalid SEO content"})
            continue
        payloads.append((video_id,package,official_title,official_description,list(public.get("tags") or [])))
if not payloads:
    print(json.dumps(out,ensure_ascii=True,separators=(",",":")),flush=True)
    raise SystemExit(0)
stamp=datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
backup=diagnostics/f"local-seo-prestage-0717-{stamp}.db"
with sqlite3.connect(db,timeout=10) as conn, sqlite3.connect(backup) as b:
    conn.backup(b)
out["backup"]=str(backup)
with sqlite3.connect(db,timeout=10) as conn:
    conn.row_factory=sqlite3.Row
    for video_id,package,old_title,old_description,old_tags in payloads:
        if conn.execute("SELECT 1 FROM optimization_drafts WHERE video_id=?",(video_id,)).fetchone():
            out["skipped"].append({"video_id":video_id,"reason":"new draft detected after backup; protected"})
            continue
        save_optimization_draft(
            conn,video_id,
            str(package.get("title") or ""),
            str(package.get("description") or ""),
            str(package.get("chapters") or ""),
            list(package.get("tags") or []),
            status="draft",
            title_variants=list(package.get("title_variants") or []),
            generation="local-seo-evidence-0.7.17-batch-qa",
            quality_state="needs_review",
            quality_reason="Потрібно перевірити головний сюжет і A/B: автоматичний опис може пропускати сильний гачок початкової назви.",
            source_title=old_title,
            source_description=old_description,
            source_tags=old_tags,
        )
        saved=conn.execute("SELECT status,quality_state,title_variants_json FROM optimization_drafts WHERE video_id=?",(video_id,)).fetchone()
        if not saved or saved["status"]!="draft" or saved["quality_state"]!="needs_review" or len(json.loads(saved["title_variants_json"]))!=3:
            raise RuntimeError("Post-write verification failed for "+video_id)
        out["staged"].append({"video_id":video_id,"status":"draft","quality_state":"needs_review","variants":3})
print(json.dumps(out,ensure_ascii=True,separators=(",",":")),flush=True)
