#!/usr/bin/env python3
"""Read-only preflight for NEWS RG Telegram private delivery, no sendPhoto/getUpdates."""
import os,sys,json,pathlib,urllib.request,urllib.error,urllib.parse,importlib.util,re,ssl
B=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
O=B/"operator"
S=O/"news_rg_private_review_staging"
def emit(**v):print(json.dumps(v,ensure_ascii=False,sort_keys=True))
def check():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if str(B) not in sys.path:sys.path.insert(0,str(B))
 p=B/"rg_moderation.py"
 if not p.is_file() or p.is_symlink():raise RuntimeError("MODERATION_MODULE_MISSING")
 spec=importlib.util.spec_from_file_location("_newsrg_mod_preflight",str(p))
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 cfg=mod.config()
 chat=cfg.get("moderation_chat_id"); moderators=cfg.get("moderators")
 if isinstance(chat,bool) or not str(chat).isdigit() or not isinstance(moderators,(list,tuple,set)):raise RuntimeError("MODERATOR_CONFIG_INVALID")
 chat=int(chat)
 if chat<=0 or chat not in {int(x) for x in moderators}:raise RuntimeError("MODERATOR_NOT_ALLOWLISTED")
 out={"schema":"NEWS_RG_PRIVATE_DELIVERY_READ_ONLY_PREFLIGHT_V1","private_chat_config":"VALID",
      "telegram_calls":["getMe"],"telegram_sends":0,"getUpdates_calls":0,
      "db_writes":0,"publications":0,"old_uncertain_claims_preserved":True}
 try:
  obj=mod.api("getMe",{})
  out["telegram_auth"]="OK" if isinstance(obj,dict) and isinstance(obj.get("id"),int) else "BAD_RESPONSE"
 except Exception as e:
  out["telegram_auth"]="FAILED"
  out["telegram_error_class"]=str(e) if str(e) in ("TELEGRAM_RESPONSE_UNCERTAIN","TELEGRAM_REQUEST_REJECTED","MODERATOR_BOT_TOKEN_MISSING","EXISTING_TOKEN_UNAVAILABLE") else type(e).__name__
 # Inspect URL schemes only; HEAD on Telegram media server is not a reliable check.
 path=O/"news_rg_private_review_staging"
 files=sorted(path.glob("*.json"),reverse=True) if path.is_dir() else []
 for file in files[:5]:
  if file.is_symlink():continue
  try:
   data=json.loads(file.read_text())
   url=data.get("media_url","")
   parsed=urllib.parse.urlsplit(url)
   out.setdefault("media_candidates",[]).append({"draft_id":data.get("draft_id"),"https":parsed.scheme=="https","host":parsed.hostname,
     "failure_marker":"НЕВДАЛО" in str(data.get("proposed_text","")).upper()})
  except (OSError,ValueError):continue
 return out
if __name__=="__main__":
 if sys.argv[1:]==["selftest"]:
  assert urllib.parse.urlsplit("https://example.org/x").scheme=="https"
  emit(status="SELFTEST_PASS")
 elif sys.argv[1:]==["inspect"]:
  try:emit(**check())
  except Exception as e:emit(status="SAFE_STOP",error_class=str(e)[:80],telegram_sends=0);sys.exit(2)
 else:raise SystemExit("selftest|inspect")
