#!/usr/bin/env python3
"""News2 package 4: test the installed gated runner without Telegram calls.
Verifies closed gates, syntax and *actual* fail-closed behavior.
Never invokes the runner if any activation gate is open.
"""
import datetime,json,os,pathlib,subprocess,sys
N=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
R=N/"operator/moderation_tick.sh"
G=N/"NAS_EXCLUSIVE_OWNER_VERIFIED"
D=N/"MODERATION_DELIVERY_ENABLED"
P=N/"PUBLISH_ENABLED"
L=pathlib.Path("/volume1/docker/RG_SECRETS/rg_nas_telegram_cutover_enabled")
def main():
 out={"schema":"RG_NEWS2_BATCH4_FAIL_CLOSED_QA_V1","time":datetime.datetime.now(datetime.timezone.utc).isoformat(),
      "no_telegram_api":True,"channel_sends":0,"writes_to_news_database":0}
 if not R.is_file() or R.is_symlink():
  out["result"]="BLOCKED_RUNNER_MISSING";print(json.dumps(out));return 1
 if any(x.exists() or x.is_symlink() for x in (G,D,P,L)):
  out["result"]="BLOCKED_GATES_NOT_ALL_CLOSED";print(json.dumps(out));return 1
 syntax=subprocess.run(["/bin/sh","-n",str(R)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 out["shell_syntax_pass"]=syntax.returncode==0
 if syntax.returncode:
  out["result"]="BLOCKED_SHELL_SYNTAX";print(json.dumps(out));return 1
 # Cannot reach any Telegram invocation because the first gate is absent.
 probe=subprocess.run(["/bin/sh",str(R)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
 out["runner_denied_execution"]=probe.returncode==20
 out["actual_runner_exit_code"]=probe.returncode
 if probe.returncode!=20:
  out["result"]="BLOCKED_UNEXPECTED_FAIL_CLOSED_BEHAVIOR";print(json.dumps(out));return 1
 out["result"]="FAIL_CLOSED_QA_PASS"
 out["next"]="A separate, independently verified sole-owner cutover is still required before live moderation."
 print(json.dumps(out,ensure_ascii=False,indent=2))
 return 0
if __name__=="__main__":
 try:sys.exit(main())
 except Exception as e:
  print(json.dumps({"result":"BLOCKED","class":type(e).__name__}));sys.exit(1)
