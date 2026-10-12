"""Read-only real-video SEO failure diagnostics on AlexPC (no model, network, or YouTube API)."""
import json, os, sqlite3, traceback
from pathlib import Path
BASE=Path(os.getenv("LOCALAPPDATA", ""))/"RGYouTubeControl"
DB=BASE/"rg_youtube_control.db"
ID="MEitKm687xo"
report={"schema":"RG_SHOIGU_REAL_SEO_FAILURE_AUDIT_V1","requested_id":ID,"read_only":True,"youtube_api_calls":0,"db_mutations":0,"model_calls":0}
try:
    with sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True,timeout=20) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        available={row["name"] for row in conn.execute("PRAGMA table_info(videos)")}
        fields=[name for name in ("video_id","profile","title","duration","description","scheduled_publish_at") if name in available]
        vids=conn.execute("SELECT "+",".join(fields)+" FROM videos WHERE video_id=? LIMIT 1",(ID,)).fetchall()
        report["videos"]=[{"video_id":v["video_id"],"profile":v["profile"],"title":v["title"],"duration":v["duration"],"published_description_chars":len(v["description"] or "") if "description" in fields else None, "scheduled":bool(v["scheduled_publish_at"])} for v in vids]
        vid=next((v["video_id"] for v in vids if v["video_id"]==ID),ID)
        report["actual_video_id"]=vid
        d=conn.execute("SELECT * FROM optimization_drafts WHERE video_id=?",(vid,)).fetchone()
        if d:
            d=dict(d)
            report["draft"]={
              "status":d.get("status"),"generation":d.get("generation"),
              "quality_state":d.get("quality_state"),"new_title":d.get("new_title"),
              "description_chars":len(d.get("description") or ""),
              "description_first":(d.get("description") or "")[:320],
              "description_has_links":"links.rginfoua.pp.ua" in (d.get("description") or ""),
              "description_has_donations":"donate.rginfoua.pp.ua" in (d.get("description") or ""),
              "chapters_count":len((d.get("chapters") or "").splitlines()),
              "variants":json.loads(d.get("title_variants_json") or "[]"),
              "updated_at":d.get("updated_at")
            }
        else:
            report["draft"]=None
        opt=conn.execute("SELECT value FROM settings WHERE key='nas_transcripts_path'").fetchone()
        report["nas_path_configured"]=bool(opt and opt[0])
    evidence_path=BASE/"seo_evidence"/(vid+".json")
    if not evidence_path.is_file():
        candidates=list((BASE/"seo_evidence").glob("*"+vid+"*"))
        evidence_path=candidates[0] if candidates else evidence_path
    report["evidence_file_exists"]=evidence_path.is_file()
    if evidence_path.is_file():
        ev=json.loads(evidence_path.read_text(encoding="utf-8"))
        report["evidence"]={
            "source":ev.get("transcript_source"),
            "blocks_total":ev.get("blocks_total"),
            "verified":ev.get("blocks_with_evidence"),
            "rows_covered":ev.get("rows_covered"),
            "unverified_blocks":ev.get("unverified_blocks"),
            "blocks":[{
                "index":b.get("index"),"start":b.get("start_stamp"),
                "end":b.get("end_stamp"),
                "verified":b.get("verified"),
                "topics":[{"topic":t.get("topic"),"summary":str(t.get("summary_uk") or "")[:300],"evidence":str(t.get("evidence") or "")[:160]} for t in b.get("topics") or []]
            } for b in ev.get("blocks") or []]
        }
    else:
        report["evidence"]=None
except Exception as exc:
    report["error"]=str(exc)[:500]
    report["traceback"]=traceback.format_exc()[-1100:]
print(json.dumps(report,ensure_ascii=False,separators=(",",":")),flush=True)
if "error" in report: raise SystemExit(2)
