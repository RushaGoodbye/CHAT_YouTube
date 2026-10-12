"""QA only: real 9m53 Shoigu metadata from AlexPC. No DB or YouTube modifications."""
import json, os, sqlite3, sys, time, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from rg_youtube_control.dialogue_seo import ab_title_issues, evidence_outline_text
from rg_youtube_control.free_tools import (
    DEFAULT_OLLAMA_MODEL, _chapters_quality_error, fetch_transcript,
    generate_seo_package_local, transcript_sample_text,
)
from rg_youtube_control.optimization import safe_description_fix

VIDEO_ID="MEitKm687xo"
DATA=Path(os.environ["LOCALAPPDATA"])/"RGYouTubeControl"
DB=DATA/"rg_youtube_control.db"
OUT=Path(os.environ.get("RUNNER_TEMP",str(ROOT)))/"rg_real_shoigu_seo_qa.json"
start=time.monotonic()
result={"schema":"RG_REAL_SHOIGU_E2E_SEO_QA_V1","video_id":VIDEO_ID,"status":"STARTED",
        "source_branch":"fix/seo-quality-end-to-end-evidence-protection",
        "db_read_only":True,"youtube_api_writes":0,"thumbnail_mutations":0}

def log(stage,**data):
    print(json.dumps({"stage":stage,**data},ensure_ascii=True),flush=True)

try:
    conn=sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True,timeout=10)
    try:
        conn.row_factory=sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        row=conn.execute("SELECT title,duration,profile FROM videos WHERE video_id=?",(VIDEO_ID,)).fetchone()
        if not row or row["profile"]!="main": raise RuntimeError("Real main video not found")
        title=str(row["title"])
        old=conn.execute(
            "SELECT description,chapters,tags_json FROM optimization_drafts WHERE video_id=?",
            (VIDEO_ID,),
        ).fetchone()
        old_description=str(old["description"] or "") if old else ""
        old_chapters=str(old["chapters"] or "") if old else ""
        old_tags=json.loads(old["tags_json"] or "[]") if old else []
        result.update({"duration":row["duration"],"old_description_chars":len(old_description),
                       "saved_old_chapters":len(old_chapters.splitlines())})
    finally:
        conn.close()

    report_path=DATA/"seo_evidence"/(VIDEO_ID+".json")
    evidence=json.loads(report_path.read_text(encoding="utf-8"))
    if evidence.get("blocks_with_evidence")!=evidence.get("blocks_total"):
        raise RuntimeError("Evidence map not fully grounded, do not build package")
    result["verified_blocks"]=evidence["blocks_total"]
    result["evidence_topic_labels"]=sum(len(b.get("topics") or []) for b in evidence.get("blocks") or [])
    rows=fetch_transcript(VIDEO_ID)
    if len(rows)<100: raise RuntimeError("Fewer than 100 caption lines, cannot QA all video")
    original_chapter_timeline=transcript_sample_text(rows,max_chars=18000,segments=10)
    result["caption_rows"]=len(rows)
    result["chapter_timeline_chars"]=len(original_chapter_timeline)
    log("real_source_verified",**{key:result[key] for key in ("caption_rows","verified_blocks","evidence_topic_labels","saved_old_chapters")})

    package=generate_seo_package_local(
        current_title=title,
        current_description=old_description,
        current_tags=old_tags if isinstance(old_tags,list) else [],
        transcript=evidence_outline_text(evidence),
        public_context={"title":title,"duration":593,"description":""},
        is_short=False,
        fast_mode=False,
        timeout=180.0,
        evidence_report=evidence,
        chapter_transcript=original_chapter_timeline,
    )
    description=str(package.get("description") or "")
    final_description=safe_description_fix(description,str(package.get("title") or title)).after
    chapters=str(package.get("chapters") or "")
    titles=[str(x) for x in package.get("title_variants") or []]
    issues=ab_title_issues(titles,evidence)
    omitted=list(package.get("timeline_omitted_topics") or [])
    topics=[str(t.get("topic") or "") for b in evidence.get("blocks") or [] for t in b.get("topics") or []]
    absent=[t for t in topics if t and t.casefold() not in description.casefold()]
    checks={
       "full_caption_timeline":len(rows)>=100,
       "all_grounded_topic_labels_in_output":not absent,
       "no_omitted_topics":not omitted,
       "exactly_three_ab":len(titles)==3,
       "ab_quality_no_issues":not issues,
       "tags_eight_or_more":len(package.get("tags") or [])>=8,
       "chapter_timestamps_supported_by_actual_captions":not chapters or not _chapters_quality_error(chapters,original_chapter_timeline),
       "canonical_links":all(v in final_description for v in ("links.rginfoua.pp.ua","donate.rginfoua.pp.ua")),
       "three_hashtags":len([token for token in final_description.split() if token.startswith("#")])==3,
       "user_review_still_required":bool(package.get("needs_review")),
    }
    result.update({"status":"PASS" if all(checks.values()) else "REVIEW","checks":checks,
       "title":package.get("title"),"variants":titles,"ab_issues":issues,
       "description":description,"description_chars":len(description),
       "description_absent_topics":absent,"omitted_topics":omitted,
       "chapters":chapters,"tags":package.get("tags"),
       "review_reason":package.get("review_reason"),
       "elapsed_seconds":round(time.monotonic()-start,1)})
    log("generation_completed",status=result["status"],checks=checks,ab_issues=issues)
except Exception as exc:
    result.update({"status":"BLOCKED","error":str(exc)[:500],"traceback":traceback.format_exc()[-1200:],
                   "elapsed_seconds":round(time.monotonic()-start,1)})
    log("blocked",error=result["error"])
finally:
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True,separators=(",",":")),flush=True)
if result["status"]!="PASS":
    raise SystemExit(2)
