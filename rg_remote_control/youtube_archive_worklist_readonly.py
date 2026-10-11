"""RG YouTube Control: comprehensive zero-quota, READ ONLY archive/draft snapshot.
Never writes SQLite, publishes videos, contacts API or touches thumbnails.
"""
from __future__ import annotations
import json, sqlite3, os, datetime
from pathlib import Path
db=Path(os.environ["LOCALAPPDATA"])/"RGYouTubeControl"/"rg_youtube_control.db"
if not db.is_file(): raise RuntimeError("Installed YouTube Control database missing")
report={"schema":"RG_YOUTUBE_ARCHIVE_WORKLIST_READONLY_V1",
        "snapshot_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "db_exists":True,"db_bytes":db.stat().st_size,
        "youtube_api_calls":0,"db_mutations":0,"published_changes":0,
        "thumbnail_changes":0}
with sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=10) as cn:
    cn.row_factory=sqlite3.Row
    cn.execute("PRAGMA query_only=ON")
    report["video_total"]=cn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    report["draft_total"]=cn.execute("SELECT COUNT(*) FROM optimization_drafts").fetchone()[0]
    report["deep_review_total"]=cn.execute("SELECT COUNT(*) FROM deep_review_state").fetchone()[0]
    settings=dict(cn.execute("SELECT key,value FROM settings").fetchall())
    report["quota_settings"]={
        k: settings.get(k) for k in
        ("youtube_quota_reserve_units","vidiq_daily_budget","local_ollama_model")
        if k in settings}
    report["profiles"]={}
    for profile in ("main","live"):
        row=cn.execute("""SELECT COUNT(*) AS n,
            SUM(CASE WHEN privacy_status='public' AND scheduled_publish_at IS NULL THEN 1 ELSE 0 END) AS public_archive,
            SUM(CASE WHEN scheduled_publish_at IS NOT NULL THEN 1 ELSE 0 END) AS scheduled,
            SUM(CASE WHEN privacy_status='private' THEN 1 ELSE 0 END) AS private_n
            FROM videos WHERE profile=?""",(profile,)).fetchone()
        status_counts=dict(cn.execute("""SELECT COALESCE(d.status,'none') AS status,COUNT(*)
            FROM videos v LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
            WHERE v.profile=? GROUP BY COALESCE(d.status,'none')""",(profile,)).fetchall())
        review_counts=dict(cn.execute("""SELECT status,COUNT(*)
            FROM deep_review_state WHERE profile=? GROUP BY status""",(profile,)).fetchall())
        ready=cn.execute("""SELECT v.video_id,v.title,v.views,v.published_at,v.audit_json,
            d.status,d.generation,d.quality_state,d.quality_reason,
            d.title_variants_json,d.updated_at,
            a.analytics_views,a.impressions,a.ctr_percent
            FROM videos v JOIN optimization_drafts d ON v.video_id=d.video_id
            LEFT JOIN video_analytics_cache a ON a.video_id=v.video_id
            WHERE v.profile=? AND v.privacy_status='public'
                AND v.scheduled_publish_at IS NULL AND d.status IN ('ready','draft')
            ORDER BY CASE WHEN d.status='ready' THEN 0 ELSE 1 END,
                     COALESCE(a.analytics_views,v.views,0) DESC LIMIT 25""",(profile,)).fetchall()
        work=[]
        for v in ready:
            try:variants=json.loads(v["title_variants_json"] or "[]")
            except (TypeError,ValueError): variants=[]
            try:audit=json.loads(v["audit_json"] or "{}")
            except (TypeError,ValueError): audit={}
            work.append({
                "video_id":v["video_id"],"title":str(v["title"])[:145],
                "draft_status":v["status"],"draft_generation":v["generation"],
                "quality_state":v["quality_state"],
                "review_reason":str(v["quality_reason"] or "")[:180],
                "variant_count":len(variants) if isinstance(variants,list) else 0,
                "views":v["views"],"audit_score":audit.get("score"),
                "audit_issue_count":len(audit.get("issues") or []),
                "analytics_views":v["analytics_views"],"impressions":v["impressions"],
                "ctr_percent":v["ctr_percent"],"draft_updated":v["updated_at"]
            })
        report["profiles"][profile]={
            "videos":row["n"],"public_archive":row["public_archive"] or 0,
            "scheduled_excluded":row["scheduled"] or 0,"private_excluded":row["private_n"] or 0,
            "draft_status_counts":status_counts,"deep_review_counts":review_counts,
            "worklist":work[:15],
            "ready_with_three_variants":cn.execute("""SELECT COUNT(*)
                FROM videos v JOIN optimization_drafts d ON d.video_id=v.video_id
                WHERE v.profile=? AND d.status='ready'
                AND json_valid(d.title_variants_json)
                AND json_array_length(d.title_variants_json)=3
                AND v.privacy_status='public' AND v.scheduled_publish_at IS NULL""",(profile,)).fetchone()[0]
        }
print(json.dumps(report,ensure_ascii=True,separators=(",",":")),flush=True)
