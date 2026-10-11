"""Read-only candidate shortlist: real long videos, not Shorts or scheduled LIVE.
No mutation, no YouTube API, no thumbnails, no publishing.
"""
import json, os, re, sqlite3
from pathlib import Path

def duration_seconds(value):
    s=str(value or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    iso=re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",s,flags=re.I)
    if iso:
        return int(iso[1] or 0)*3600+int(iso[2] or 0)*60+int(iso[3] or 0)
    if re.fullmatch(r"\d{1,3}:\d{2}(?::\d{2})?",s):
        parts=list(map(int,s.split(":")))
        return sum(n*60**i for i,n in enumerate(reversed(parts)))
    return None

path=Path(os.environ["LOCALAPPDATA"])/"RGYouTubeControl"/"rg_youtube_control.db"
if not path.is_file(): raise RuntimeError("Missing application DB")
with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=15) as conn:
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    rs=conn.execute("""SELECT v.video_id,v.title,v.duration,v.views,v.published_at,
                      v.profile,v.privacy_status,v.scheduled_publish_at,v.audit_json,
                      COALESCE(d.status,'none') AS draft_status,
                      COALESCE(d.generation,'') AS generation,
                      COALESCE(d.quality_state,'') AS quality_state,
                      COALESCE(d.title_variants_json,'[]') AS title_variants_json
                      FROM videos v LEFT JOIN optimization_drafts d USING(video_id)
                      WHERE v.profile IN ('main','live')""").fetchall()
report={
    "schema":"RG_ARCHIVE_LONGFORM_PRIORITY_READONLY_V1",
    "youtube_api_calls":0, "sqlite_writes":0,"published_changes":0,
    "total_videos":len(rs),"profiles":{},
}
for profile in ("main","live"):
    allp=[r for r in rs if r["profile"]==profile]
    pool=[]
    excluded={"not_public":0,"scheduled":0,"short":0,"missing_duration":0}
    for r in allp:
        if r["privacy_status"]!="public":
            excluded["not_public"]+=1;continue
        if r["scheduled_publish_at"]:
            excluded["scheduled"]+=1;continue
        dur=duration_seconds(r["duration"])
        title=str(r["title"])
        if dur is None:
            excluded["missing_duration"]+=1;continue
        if dur<181 or re.search(r"(?:^|[\s#])shorts?(?:$|[\s#])",title,re.I):
            excluded["short"]+=1;continue
        try: variants=json.loads(r["title_variants_json"] or "[]")
        except Exception:variants=[]
        if not isinstance(variants,list):variants=[]
        try:audit=json.loads(r["audit_json"] or "{}")
        except Exception:audit={}
        pool.append({
            "id":r["video_id"],"title":title[:155],"duration_seconds":dur,
            "views":r["views"],"draft_status":r["draft_status"],
            "generation":r["generation"],"quality":r["quality_state"],
            "variant_count":len(variants),"audit_score":audit.get("score"),
            "issues":len(audit.get("issues") or []),
            "published_at":r["published_at"],
        })
    needs=[v for v in pool if v["generation"]!="local" or v["variant_count"]!=3 or v["quality"]!="passed"]
    needs.sort(key=lambda v:(-(v["views"] or 0),v["id"]))
    report["profiles"][profile]={
        "total":len(allp),"eligible_longform":len(pool),
        "needs_new_quality_gate":len(needs),"excluded":excluded,
        "top_candidates":needs[:12]
    }
print(json.dumps(report,ensure_ascii=True,separators=(",",":")),flush=True)
