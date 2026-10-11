"""Read-only Qwen chat diagnostic (one small prompt, no DB/YouTube changes)."""
from __future__ import annotations
import json
import sys
import time
import urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rg_youtube_control.free_tools import ollama_chat
start=time.monotonic()
out={"schema":"RG_OLLAMA_CHAT_DIAG_V1","model":"qwen3:8b","no_youtube_api":True,"no_db_write":True}
try:
    raw=ollama_chat([{"role":"system","content":"Return only JSON."},{"role":"user","content":"Return {\"ok\":true} as JSON."}],model="qwen3:8b",timeout=45,temperature=0.0,json_mode=True)
    out.update({"ok":True,"reply":raw[:200]})
except Exception as exc:
    chain=[]
    cur=exc
    for n in range(3):
        if cur is None:break
        record={"kind":type(cur).__name__,"message":str(cur)[:700]}
        if isinstance(cur,urllib.error.HTTPError):
            record["status"]=cur.code
            try:record["body"]=cur.read(1000).decode("utf-8","replace")
            except Exception:pass
        chain.append(record)
        cur=getattr(cur,"__cause__",None)
    out.update({"ok":False,"exception_chain":chain})
out["elapsed_seconds"]=round(time.monotonic()-start,2)
print(json.dumps(out,ensure_ascii=True,separators=(",",":")),flush=True)
