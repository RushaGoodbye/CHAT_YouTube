"""Offline QA of ten archive SEO packages. No database writes, no YouTube writes.
Uses the existing installed read-only channel database and source-checks each result.
"""
import json, os, sqlite3, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from rg_youtube_control.free_tools import fetch_transcript,load_srt_transcript,generate_seo_package_local,ollama_chat,DEFAULT_OLLAMA_MODEL
from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks,evidence_outline_text,ab_title_issues
base=Path(os.environ["LOCALAPPDATA"])/"RGYouTubeControl"
db_path=base/"rg_youtube_control.db"
output=Path(os.environ.get("RUNNER_TEMP",str(base)))/"rg_seo_ten_readonly.json"
report={"schema":"RG_SEO_TEN_READONLY_V1","youtube_writes":0,"db_writes":0,"app_changes":0,"entries":[]}
with sqlite3.connect(db_path.resolve().as_uri()+"?mode=ro",uri=True,timeout=15) as db:
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    candidates=db.execute("""SELECT v.video_id,v.title,v.duration FROM videos v
        WHERE v.profile='main' AND COALESCE(v.privacy_status,'public')='public'
        AND v.scheduled_publish_at IS NULL AND v.title IS NOT NULL
        ORDER BY v.views DESC LIMIT 100""").fetchall()
seen=set()
for v in candidates:
    if len([x for x in report["entries"] if x["status"]=="PASS"])>=10: break
    if len(report["entries"])>=25: break
    title=str(v["title"] or "")
    video_id=str(v["video_id"])
    if not title or video_id in seen: continue
    seen.add(video_id)
    item={"video_id":video_id,"source_title":title,"status":"BLOCKED"}
    report["entries"].append(item)
    try:
        rows=[]
        for loc in (base/"transcripts"/(video_id+".srt"),):
            if loc.exists():
                rows=load_srt_transcript(loc)
                if rows: break
        if not rows: rows=fetch_transcript(video_id)
        if not rows: raise RuntimeError("transcript_unavailable")
        evidence=analyze_all_timeline_blocks(rows,model=DEFAULT_OLLAMA_MODEL,
            chat=ollama_chat,cache_dir=None,max_chars=5000,max_span_seconds=300,timeout=180)
        if not evidence.get("blocks_with_evidence"): raise RuntimeError("no_verified_evidence")
        package=generate_seo_package_local(
            current_title=title,transcript=evidence_outline_text(evidence),
            public_context={"title":title,"duration":v["duration"]},
            fast_mode=False,timeout=300,evidence_report=evidence)
        ab=list(package.get("title_variants") or [])
        issues=ab_title_issues(ab,evidence)
        omitted=list(package.get("timeline_omitted_topics") or [])
        item.update({"status":"PASS" if len(ab)==3 and not issues and not omitted else "REVIEW",
            "transcript_rows":len(rows),"blocks":evidence.get("blocks_total"),
            "verified_blocks":evidence.get("blocks_with_evidence"),"ab_titles":ab,
            "ab_issues":issues,"omitted_topics":omitted,
            "title":package.get("title"),"description":package.get("description"),
            "tags":package.get("tags"),"review_reason":package.get("review_reason")})
    except Exception as exc:
        item["error"]=type(exc).__name__+": "+str(exc)[:300]
    print(json.dumps({"id":video_id,"status":item["status"],"error":item.get("error","")},ensure_ascii=False),flush=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
report["pass_count"]=sum(x["status"]=="PASS" for x in report["entries"])
report["status"]="PASS" if report["pass_count"]==10 else "INCOMPLETE"
output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"status":report["status"],"pass_count":report["pass_count"],"attempted":len(report["entries"]),"report":str(output)},ensure_ascii=False))
