#!/usr/bin/env python3
"""RG News2 batch #2: check staged runner's interface, safety, and poll ownership.
Read-only, no Telegram API, no changes or secrets printed. Python 3.7+.
"""
import ast, datetime, json, os, pathlib, re, sqlite3, subprocess, sys
R=pathlib.Path("/volume1/docker")
N=R/"RG_TELEGRAM_NEWS_2"
S=N/"operator/moderation_tick.sh"
M=N/"rg_moderation.py"
SCHED=R/"RG_NAS_SCHEDULER_TICK.sh"
def safe_read(p):
 if not p.is_file() or p.is_symlink():return ""
 return p.read_text(encoding="utf-8",errors="replace")
def main():
 report={"schema":"RG_NEWS2_BATCH2_READONLY","utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"telegram_api_calls":0,"telegram_sends":0,"writes":0,"activation_permitted":False,"checks":{},"blockers":[]}
 c=report["checks"]; issues=report["blockers"]
 src=safe_read(M); staged=safe_read(S); sched=safe_read(SCHED)
 c["runner_staged"]=bool(staged); c["news2_moderation_module"]=bool(src);c["scheduler_exists"]=bool(sched)
 c["legacy_cutover_gate"]=(R/"RG_SECRETS/rg_nas_telegram_cutover_enabled").exists()
 c["news2_owner_gate"]=(N/"NAS_EXCLUSIVE_OWNER_VERIFIED").exists()
 c["news2_delivery_gate"]=(N/"MODERATION_DELIVERY_ENABLED").exists()
 c["publisher_gate"]=(N/"PUBLISH_ENABLED").exists()
 if c["legacy_cutover_gate"]:issues.append("LEGACY_BOT_GATE_OPEN")
 if not src:issues.append("MODERATION_MODULE_MISSING")
 else:
  try:
   tree=ast.parse(src,filename=str(M))
   funcs={node.name for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
   c["functions_present"]={name:name in funcs for name in ("send_one","poll_once","process_callback")}
   if not all(c["functions_present"].values()):issues.append("MODERATION_INTERFACE_INCOMPLETE")
   c["has_send_photo"]="sendPhoto" in src
   c["has_getupdates"]="getUpdates" in src
   c["has_gate_names"]=all(x in src for x in ("NAS_EXCLUSIVE_OWNER_VERIFIED","MODERATION_DELIVERY_ENABLED"))
   c["has_callback_actions"]=all(x in src for x in ("approve","reject"))
  except SyntaxError:issues.append("MODERATION_MODULE_SYNTAX_ERROR")
 if staged:
  c["runner_gate_checks"]=all(x in staged for x in ("NAS_EXCLUSIVE_OWNER_VERIFIED","MODERATION_DELIVERY_ENABLED"))
  c["runner_has_lock"]="moderation_tick.lock" in staged
  c["runner_calls_poll"]="poll-once" in staged
  c["runner_calls_send"]="send-one" in staged
  if not all((c["runner_gate_checks"],c["runner_has_lock"],c["runner_calls_poll"],c["runner_calls_send"])):issues.append("RUNNER_CONTRACT_INCOMPLETE")
 else:issues.append("RUNNER_NOT_STAGED")
 c["old_native_bot_scheduler_reference"]="rg_telegram_nas_native_bot_v01.py" in sched
 c["news2_scheduler_reference"]="moderation_tick.sh" in sched
 if c["news2_scheduler_reference"]:issues.append("NEWS2_ALREADY_SCHEDULED_REVIEW_NEEDED")
 db=N/"news.sqlite3"
 if db.is_file():
  try:
   with sqlite3.connect("file:"+str(db)+"?mode=ro",uri=True,timeout=3) as con:
    c["queue"]=dict(con.execute("SELECT status,count(*) FROM candidates GROUP BY status"))
    c["dispatch"]=dict(con.execute("SELECT state,count(*) FROM moderation_dispatch GROUP BY state"))
  except sqlite3.Error:issues.append("NEWS2_DB_READ_ERROR")
 else:issues.append("NEWS2_DB_MISSING")
 c["sole_getupdates_owner_verified"]=False
 issues.append("EXCLUSIVE_GETUPDATES_OWNER_UNVERIFIED")
 print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
if __name__=="__main__":
 main()
