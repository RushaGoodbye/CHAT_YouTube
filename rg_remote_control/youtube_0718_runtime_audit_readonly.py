"""READ ONLY whole-program operating-data health check for installed AlexPC.
Counts only; never exposes viewer identities or comments; no external requests.
"""
from __future__ import annotations
import json
import os
import sqlite3
from pathlib import Path
root=Path(os.environ["LOCALAPPDATA"])/"RGYouTubeControl"
database=root/"rg_youtube_control.db"
report={
 "schema":"RG_YOUTUBE_0718_FULL_RUNTIME_READONLY_V1",
 "db_exists":database.is_file(),
 "youtube_api_calls":0,
 "db_writes":0,
 "published_changes":0,
 "thumbnail_changes":0,
 "profiles":{},
}
with sqlite3.connect(database.resolve().as_uri()+"?mode=ro",uri=True,timeout=10) as conn:
 conn.row_factory=sqlite3.Row
 conn.execute("PRAGMA query_only=ON")
 report["integrity_check"]=[str(x[0]) for x in conn.execute("PRAGMA quick_check").fetchall()][:8]
 for profile in ("main","live"):
  rows=conn.execute("""SELECT v.video_id,v.privacy_status,v.scheduled_publish_at,
     d.status,d.generation,d.quality_state,d.title_variants_json
     FROM videos v LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
     WHERE v.profile=?""",(profile,)).fetchall()
  problems={"legacy_ready_unapproved":[],"seo_ready_missing_three_ab":[],
   "unsafe_source_quotes_marked_ready":[],"broken_variants_json":[],
   "review_drafts":[],"already_applied":[]}
  counts={"all_videos":len(rows),"scheduled":0,"public":0,"drafts":0,
   "ready":0,"applied":0,"safe_metadata_ready":0,"full_seo_ready":0,
   "full_seo_with_three_ab":0,"review_drafts":0}
  for row in rows:
   if row["scheduled_publish_at"]:counts["scheduled"]+=1
   if row["privacy_status"]=="public":counts["public"]+=1
   status=str(row["status"] or "")
   if status in counts:counts[status]+=1
   if status=="draft":counts["drafts"]+=0
   generation=str(row["generation"] or "")
   quality=str(row["quality_state"] or "")
   try:
    variants=json.loads(row["title_variants_json"] or "[]")
    if not isinstance(variants,list):raise TypeError()
   except (ValueError,TypeError):
    variants=[]
    problems["broken_variants_json"].append(str(row["video_id"]))
   if status=="ready":
    if generation.startswith("safe-metadata") and quality=="safe_metadata":
     counts["safe_metadata_ready"]+=1
    elif not row["scheduled_publish_at"]:
     counts["full_seo_ready"]+=1
     if len(variants)!=3:
      problems["seo_ready_missing_three_ab"].append(str(row["video_id"]))
     else:counts["full_seo_with_three_ab"]+=1
     if quality not in ("safe","editor_approved"):
      problems["legacy_ready_unapproved"].append(str(row["video_id"]))
     if "source_quote" in quality.casefold() and quality in ("safe","editor_approved"):
      problems["unsafe_source_quotes_marked_ready"].append(str(row["video_id"]))
   if status=="draft" and quality in ("needs_review","review"):
    counts["review_drafts"]+=1
    problems["review_drafts"].append(str(row["video_id"]))
   if status=="applied":problems["already_applied"].append(str(row["video_id"]))
  report["profiles"][profile]={
   "counts":counts,
   "issue_counts":{key:len(value) for key,value in problems.items()},
   "issue_sample_ids":{key:value[:8] for key,value in problems.items()
                       if key in ("legacy_ready_unapproved","seo_ready_missing_three_ab","broken_variants_json")}
  }
print(json.dumps(report,ensure_ascii=True,separators=(",",":")),flush=True)
