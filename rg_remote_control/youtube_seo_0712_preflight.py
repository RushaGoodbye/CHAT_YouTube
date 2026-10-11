"""Read-only installed environment preflight before real SEO generation. No YouTube API."""
from __future__ import annotations
import importlib.util
import json
import os
import sqlite3
import urllib.request
from pathlib import Path

video_id="LM0vkW9YoKg"
local=Path(os.environ.get("LOCALAPPDATA",""))/"RGYouTubeControl"
db=local/"rg_youtube_control.db"
out={"schema":"RG_SEO_0712_PREFLIGHT_V1","video_id":video_id,"db_exists":db.is_file(),
     "libraries":{},"model":{},"source":{},"youtube_api_calls":0,"db_changes":0}
for name in ("youtube_transcript_api","yt_dlp","rapidfuzz","PySide6"):
    try: out["libraries"][name]=importlib.util.find_spec(name) is not None
    except Exception: out["libraries"][name]=False
try:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=3) as response:
        data=json.load(response)
    out["model"]={"ollama_ready":True,"qwen3_8b_present":any("qwen3:8b" in str(x.get("name","")) for x in data.get("models",[])),
                  "available_models":[str(x.get("name",""))[:90] for x in data.get("models",[])[:12]]}
except Exception as exc:
    out["model"]={"ollama_ready":False,"error":str(exc)[:250]}
if db.is_file():
    with sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        row=conn.execute("SELECT video_id,title,profile,duration FROM videos WHERE video_id=?",(video_id,)).fetchone()
        out["source"]["video_exists"]=row is not None
        if row: out["source"]["video"]=dict(row)
        row=conn.execute("SELECT value FROM settings WHERE key='nas_transcripts_path'").fetchone()
        out["source"]["nas_srt_setting"]=str(row[0])[:350] if row else ""
        row=conn.execute("SELECT updated_at,generation,status FROM optimization_drafts WHERE video_id=?",(video_id,)).fetchone()
        if row:out["source"]["previous_draft"]=dict(row)
print(json.dumps(out,ensure_ascii=True,separators=(",",":")))
