"""Read-only ranked ordinary-video archive candidates. No YouTube/API/DB changes."""
import os,sqlite3,json,datetime,re
from pathlib import Path
db=Path(os.environ["LOCALAPPDATA"])/"RGYouTubeControl"/"rg_youtube_control.db"
def seconds(value):
    if value is None:return 0.0
    try:return max(0.0,float(value))
    except (ValueError,TypeError):pass
    # YouTube ISO-8601 durations (PT25S, PT1H10M, P1DT2H, ...)
    match=re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",str(value),re.I)
    if not match:return 0.0
    day,hour,minute,second=match.groups()
    return int(day or 0)*86400+int(hour or 0)*3600+int(minute or 0)*60+float(second or 0)

out={"schema":"RG_YOUTUBE_FIRST_ARCHIVE_BATCH_V1","youtube_api_calls":0,"db_writes":0,"profiles":{}}
with sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=8) as con:
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    for profile in ("main","live"):
        base="""FROM videos v LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
                WHERE v.profile=? AND v.privacy_status='public'
                AND v.scheduled_publish_at IS NULL
                AND lower(v.title) NOT LIKE '%#shorts%'
                AND lower(v.title) NOT LIKE '%#short%'
                """
        q="""SELECT v.video_id,v.title,v.duration,v.views,v.published_at,
            d.status,d.generation,d.quality_state,d.title_variants_json,d.updated_at
            """+base+"""
            AND COALESCE(d.status,'none') NOT IN ('applied')
            ORDER BY COALESCE(v.views,0) DESC"""
        rows=[]
        for raw in con.execute(q,(profile,)).fetchall():
            v=dict(raw)
            duration_seconds=seconds(v.get("duration"))
            if duration_seconds < 240:
                continue
            try:variants=json.loads(v.pop("title_variants_json") or "[]")
            except (ValueError,TypeError):variants=[]
            v["variants"]=len(variants) if isinstance(variants,list) else 0
            v["minutes"]=round(duration_seconds/60,1)
            rows.append(v)
        # Select popular ordinary videos rather than already-published
        # scheduled streams, shorts and already-applied SEO.
        out["profiles"][profile]={"eligible_public_regular":len(rows),
                                  "top20_candidates":rows[:20],
                                  "top10_missing_ab":[x for x in rows if x["variants"]<3][:10],
                                  "top10_has_ab":[x for x in rows if x["variants"]==3][:10]}
print(json.dumps(out,ensure_ascii=True,separators=(",",":")))
