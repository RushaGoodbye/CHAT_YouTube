#!/usr/bin/env python3
"""NEWS RG one-pass private delivery wiring audit. Read-only and secret-safe."""
import pathlib,re,json,sys,ast,os,sqlite3,time
B=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
O=B/"operator"
CHECK=[
 B/"telegram_photo_review_flow.py",
 B/"rg_news2_private_final_guard_v1.py",
 O/"rg_news2_outbound_queue_v2.py",
 O/"telegram_photo_review_flow.py",
 O/"callback_v29.log",
 O/"news_rg_private_review_staging"/"150e71991883d7cd006bb2a9.json",
]
KEYS=("callback_query","callback_data","answerCallbackQuery","getUpdates","setWebhook","sendPhoto","sendMessage","deliver_one","moderation","photo_review","rg_private_only_tick")
def status(p):
 try:
  t=p.stat()
  return {"present":True,"bytes":t.st_size,"age_minutes":round((time.time()-t.st_mtime)/60,1)}
 except OSError:return {"present":False}
def codepaths(p):
 if not p.exists() or not p.is_file() or p.is_symlink() or p.suffix!=".py":return []
 s=p.read_text(errors="replace")
 lines=s.splitlines()
 return [{"line":i,"calls":[k for k in KEYS if k.lower() in line.lower()]} for i,line in enumerate(lines,1) if any(k.lower() in line.lower() for k in KEYS)][:65]
def find():
 out={"schema":"NEWS_RG_PRIVATE_DELIVERY_WIRING_V1","read_only":True,"telegram_calls":0,"db_writes":0,"publications":0}
 out["files"]={}
 for p in CHECK:
  info=status(p)
  if p.suffix==".py":info["routing_indicators"]=codepaths(p)
  out["files"][str(p.relative_to(B))]=info
 out["callback_handler_candidates"]=[]
 for folder in (B,O):
  for p in folder.iterdir():
   if not p.is_file() or p.suffix!=".py" or p.is_symlink() or p.stat().st_size>100000:continue
   text=p.read_text(errors="replace")
   score=sum(k in text for k in ("callback_query","ph1:a:","answerCallbackQuery","getUpdates"))
   if score:out["callback_handler_candidates"].append({"name":str(p.relative_to(B)),"routing_score":score})
 out["callback_handler_candidates"].sort(key=lambda d:-d["routing_score"])
 return out
if __name__=="__main__":
 if sys.argv[1:]==["selftest"]:
  assert "callback_query" in KEYS
  print("NEWS_RG_PRIVATE_DELIVERY_WIRING_SELFTEST_PASS")
 elif sys.argv[1:]==["inspect"]:
  try:print(json.dumps(find(),ensure_ascii=False,indent=2))
  except Exception as e:
   print(json.dumps({"status":"SAFE_STOP","error_class":type(e).__name__}));sys.exit(2)
 else:raise SystemExit("selftest|inspect")
